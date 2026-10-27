import json
from types import SimpleNamespace

from google.genai import errors
import httpx
import pytest

from gemini import GeminiAdapter, GeminiSettings, ModelOutputError, ModelUnavailable
from memory.shared_memory import EvidenceModel


class Answer(EvidenceModel):
    text: str


class SDKClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.models = self
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def response(text='{"text":"grounded"}', reason="STOP"):
    return SimpleNamespace(text=text, candidates=[SimpleNamespace(finish_reason=reason)],
        usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=3, total_token_count=15),
        model_version="configured-model-version")


def test_official_sdk_arguments_schema_and_telemetry(caplog):
    client = SDKClient([response()])
    adapter = GeminiAdapter(GeminiSettings(model_id="gemini-3.5-flash-lite"), client=client)
    with caplog.at_level("INFO", logger="mafis.gemini"):
        result = adapter.generate(Answer, system="system rules", payload={"untrusted": "private source text"})
    assert result.text == "grounded"
    call = client.calls[0]
    assert call["model"] == "gemini-3.5-flash-lite"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_json_schema == Answer.model_json_schema()
    assert adapter.telemetry[0].total_tokens == 15 and adapter.telemetry[0].latency_ms >= 0
    assert "private source text" not in caplog.text
    assert json.loads(call["contents"])["untrusted"] == "private source text"


@pytest.mark.parametrize("bad", [response("not JSON"), response('{"text":"ok","extra":1}'),
    response(""), response(reason="MAX_TOKENS"), response('{"text":123}')])
def test_malformed_output_is_not_retried(bad):
    client = SDKClient([bad])
    adapter = GeminiAdapter(client=client)
    with pytest.raises(ModelOutputError):
        adapter.generate(Answer, system="rules", payload={})
    assert len(client.calls) == 1 and adapter.telemetry[0].status == "malformed_output"


def test_transport_retries_are_bounded_and_never_switch_model():
    client = SDKClient([httpx.ConnectError("blocked")] * 3)
    delays = []
    adapter = GeminiAdapter(GeminiSettings(max_retries=2), client=client, sleeper=delays.append)
    with pytest.raises(ModelUnavailable):
        adapter.generate(Answer, system="rules", payload={})
    assert len(client.calls) == 3 and delays == [1, 2]
    assert len({c["model"] for c in client.calls}) == 1
    assert len(adapter.telemetry) == 3


def test_transient_failure_then_success():
    client = SDKClient([errors.APIError(503, {"error": {"message": "busy", "status": "UNAVAILABLE"}}), response()])
    adapter = GeminiAdapter(client=client, sleeper=lambda _: None)
    assert adapter.generate(Answer, system="rules", payload={}).text == "grounded"
    assert len(client.calls) == 2


def test_nontransient_error_has_no_retry_or_secret_log(caplog):
    client = SDKClient([errors.APIError(403, {"error": {"message": "SECRET-KEY", "status": "DENIED"}})])
    adapter = GeminiAdapter(client=client)
    with caplog.at_level("INFO", logger="mafis.gemini"), pytest.raises(ModelUnavailable) as caught:
        adapter.generate(Answer, system="rules", payload={})
    assert len(client.calls) == 1
    assert "SECRET-KEY" not in str(caught.value) + caplog.text


def test_live_is_disabled_even_if_a_key_exists(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    with pytest.raises(ModelUnavailable, match="disabled"):
        GeminiAdapter().generate(Answer, system="rules", payload={})


def test_missing_live_credentials(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ModelUnavailable, match="required"):
        GeminiAdapter(allow_live=True).generate(Answer, system="rules", payload={})


def test_generation_settings_are_explicit_environment_overrides(monkeypatch):
    monkeypatch.setenv("MAFIS_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("MAFIS_TRANSPORT_RETRIES", "1")
    settings = GeminiSettings.from_env("explicit-model")
    assert settings.model_id == "explicit-model" and settings.max_output_tokens == 2048
    assert settings.max_retries == 1
