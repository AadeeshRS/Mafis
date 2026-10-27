"""Single official Google GenAI SDK adapter with explicit live-call opt-in."""

import json
import logging
import os
from time import perf_counter, sleep
from typing import TypeVar
from uuid import uuid4

from google import genai
from google.genai import errors, types
import httpx
from pydantic import BaseModel, Field, ValidationError

from config import DOCUMENT_MODEL
from memory.shared_memory import EvidenceModel


T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("mafis.gemini")


class ModelUnavailable(RuntimeError):
    pass


class ModelOutputError(RuntimeError):
    pass


def credential():
    """MAFIS explicitly prefers GEMINI_API_KEY over GOOGLE_API_KEY."""
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def classify_provider_error(exc):
    """Return allowlisted diagnostics; never propagate provider exception text."""
    code = getattr(exc, "code", None)
    message = str(exc).lower()  # inspect locally, never persist or log
    if "billing" in message or "payment" in message:
        return "billing_restriction"
    if "api_key_invalid" in message or "api key not valid" in message or code == 401:
        return "invalid_credential"
    if code == 429:
        return "quota_exhaustion_or_rate_limit"
    if code in (403, 404):
        return "model_or_project_access"
    if code == 400 or isinstance(exc, (ValueError, TypeError, ValidationError)):
        return "schema_or_config"
    return "network_or_sdk_error"


class GeminiSettings(EvidenceModel):
    model_id: str = Field(default=DOCUMENT_MODEL, min_length=1)
    temperature: float = Field(default=0, ge=0, le=2)
    max_output_tokens: int = Field(default=4096, ge=128, le=65536)
    timeout_ms: int = Field(default=30000, ge=1000, le=120000)
    max_retries: int = Field(default=2, ge=0, le=3)

    @classmethod
    def from_env(cls, model_id=DOCUMENT_MODEL):
        return cls(model_id=model_id, temperature=float(os.getenv("MAFIS_TEMPERATURE", "0")),
            max_output_tokens=int(os.getenv("MAFIS_MAX_OUTPUT_TOKENS", "4096")),
            timeout_ms=int(os.getenv("MAFIS_TIMEOUT_MS", "30000")),
            max_retries=int(os.getenv("MAFIS_TRANSPORT_RETRIES", "2")))


class CallTelemetry(EvidenceModel):
    request_id: str
    model_id: str
    attempt: int
    status: str
    latency_ms: float
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    thinking_tokens: int | None = None
    model_version: str | None = None


class GeminiAdapter:
    def __init__(self, settings: GeminiSettings | None = None, *, client=None, allow_live=False, sleeper=sleep, request_budget=None):
        self.settings = settings or GeminiSettings.from_env()
        self._client = client
        self.allow_live = allow_live
        self.mode = "injected SDK client (mocked)" if client is not None else "live enabled" if allow_live else "live disabled"
        self._sleep = sleeper
        self.request_budget = request_budget
        self.telemetry: list[CallTelemetry] = []

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.allow_live:
            raise ModelUnavailable("Live Gemini calls are disabled; inject an offline model or explicitly enable live usage")
        key = credential()
        if not key:
            raise ModelUnavailable("GEMINI_API_KEY or GOOGLE_API_KEY is required")
        # Disable nested SDK retries so the configured transport bound is exact.
        try:
            self._client = genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(
                timeout=self.settings.timeout_ms, retry_options=types.HttpRetryOptions(attempts=1)))
        except Exception as exc:
            raise ModelUnavailable(f"Gemini client unavailable ({classify_provider_error(exc)})") from None
        return self._client

    def _record(self, request_id, attempt, started, status, response=None):
        usage = getattr(response, "usage_metadata", None)
        event = CallTelemetry(request_id=request_id, model_id=self.settings.model_id,
            attempt=attempt, status=status, latency_ms=(perf_counter() - started) * 1000,
            prompt_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            total_tokens=getattr(usage, "total_token_count", None),
            thinking_tokens=getattr(usage, "thoughts_token_count", None),
            model_version=getattr(response, "model_version", None))
        self.telemetry.append(event)
        # No credentials, prompts, retrieved source text, or raw exceptions in logs.
        logger.info(event.model_dump_json())

    def generate(self, schema: type[T], *, system: str, payload: dict) -> T:
        client = self._get_client()
        request_id = str(uuid4())
        contents = json.dumps(payload, ensure_ascii=True)
        for attempt in range(1, self.settings.max_retries + 2):
            if self.request_budget is not None:
                if self.request_budget[0] <= 0:
                    raise ModelUnavailable("Shared generation request budget exhausted")
                self.request_budget[0] -= 1
            started = perf_counter()
            try:
                response = client.models.generate_content(model=self.settings.model_id, contents=contents,
                    config=types.GenerateContentConfig(system_instruction=system,
                        temperature=self.settings.temperature, max_output_tokens=self.settings.max_output_tokens,
                        response_mime_type="application/json", response_json_schema=schema.model_json_schema()))
            except (errors.APIError, httpx.TransportError) as exc:
                code = getattr(exc, "code", None)
                transient = isinstance(exc, httpx.TransportError) or code in (429, 500, 502, 503, 504)
                self._record(request_id, attempt, started, f"transport_error:{code or type(exc).__name__}")
                if not transient or attempt > self.settings.max_retries:
                    raise ModelUnavailable(f"Gemini transport failed ({classify_provider_error(exc)}; status={code if isinstance(code, int) else 'unknown'}); no model substitution") from None
                self._sleep(min(2 ** (attempt - 1), 4))
                continue
            except Exception as exc:
                self._record(request_id, attempt, started, classify_provider_error(exc))
                raise ModelUnavailable(f"Gemini request failed ({classify_provider_error(exc)}); no model substitution") from None
            try:
                candidates = getattr(response, "candidates", None)
                reason = getattr(candidates[0], "finish_reason", None) if candidates else None
                if reason is not None and str(getattr(reason, "value", reason)) != "STOP":
                    raise ModelOutputError("Gemini did not complete a structured response")
                if not response.text:
                    raise ModelOutputError("Gemini returned no structured content")
                result = schema.model_validate_json(response.text)
            except (ValidationError, ValueError, ModelOutputError):
                self._record(request_id, attempt, started, "malformed_output", response)
                raise ModelOutputError("Invalid, blocked, or incomplete structured Gemini output") from None
            self._record(request_id, attempt, started, "success", response)
            return result
        raise AssertionError("Unreachable retry state")
