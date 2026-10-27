"""Sanitized metadata readiness; this module never generates content."""

import json
import os
from pathlib import Path
from datetime import datetime, timezone

from dotenv import dotenv_values
from google import genai
from google.genai import types

from config import ENV_PATH, PRIMARY_MODEL, DOCUMENT_MODEL
from gemini import credential, classify_provider_error

CANDIDATES = ("gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.1-flash-lite")


def credential_diagnostics():
    file_values = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    names = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    selected = next((name for name in names if os.getenv(name)), None)
    return {"dotenv_path": str(ENV_PATH), "dotenv_exists": ENV_PATH.exists(),
        "dotenv_key_names_present": {name: bool(file_values.get(name)) for name in names},
        "runtime_key_names_present": {name: bool(os.getenv(name)) for name in names},
        "selected_key_name": selected, "explicit_sdk_api_key": bool(selected),
        "selected_matches_dotenv": bool(selected and os.getenv(selected) == file_values.get(selected)),
        "process_environment_overrides_dotenv": True, "vertexai": False}


def probe(*, model_ids=None, client=None):
    identifiers = tuple(dict.fromkeys(model_ids or (PRIMARY_MODEL, DOCUMENT_MODEL)))
    if len(identifiers) > 5:
        raise ValueError("At most five metadata requests are allowed")
    result = {"created_utc": datetime.now(timezone.utc).isoformat(),
        "credential_present": bool(credential()), "credentials": credential_diagnostics(),
        "generation_requests": 0, "metadata_requests": 0, "sdk_retries": 0,
        "free_tier_confirmed": False, "quota_visibility": "unavailable", "models": []}
    if not credential() and client is None:
        result["blocker"] = "missing_credential"
        return result
    owned = client is None
    try:
        client = client or genai.Client(api_key=credential(), vertexai=False,
            http_options=types.HttpOptions(timeout=10000, retry_options=types.HttpRetryOptions(attempts=1)))
        for identifier in identifiers:
            result["metadata_requests"] += 1
            try:
                model = client.models.get(model=identifier)
                result["models"].append({"model_id": identifier, "available": True,
                    "input_limit": model.input_token_limit, "output_limit": model.output_token_limit,
                    "supported_actions": model.supported_actions})
            except Exception as exc:
                result["models"].append({"model_id": identifier, "available": False,
                    "classification": classify_provider_error(exc)})
    except Exception as exc:
        result["blocker"] = classify_provider_error(exc)
    finally:
        if owned and client is not None:
            client.close()
    return result


if __name__ == "__main__":
    result = probe(model_ids=CANDIDATES)
    output = Path("output/controller_batch1/provider_readiness.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
