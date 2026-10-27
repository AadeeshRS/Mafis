"""Offline provider failure/budget regressions and real isolated Chroma checks."""

from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from gemini import GeminiAdapter, GeminiSettings, ModelUnavailable, classify_provider_error, credential
from memory.shared_memory import EvidenceModel
from scripts.live_readiness import probe


class Answer(EvidenceModel):
    answer: str


def test_explicit_credential_precedence(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-primary")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-secondary")
    assert credential() == "test-primary"


def test_sdk_receives_selected_key_and_disables_nested_retries(monkeypatch):
    import gemini
    monkeypatch.setenv("GEMINI_API_KEY", "test-primary")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    captured = {}
    def factory(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()
    monkeypatch.setattr(gemini.genai, "Client", factory)
    GeminiAdapter(allow_live=True)._get_client()
    assert captured["api_key"] == "test-primary" and captured["vertexai"] is False
    assert captured["http_options"].retry_options.attempts == 1


def test_sdk_constructor_error_is_sanitized(monkeypatch):
    import gemini
    monkeypatch.setenv("GEMINI_API_KEY", "test-primary")
    def fail(**kwargs):
        raise ValueError("secret")
    monkeypatch.setattr(gemini.genai, "Client", fail)
    with pytest.raises(ModelUnavailable, match="schema_or_config") as caught:
        GeminiAdapter(allow_live=True)._get_client()
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(("code", "message", "expected"), [
    (400, "API key not valid. secret", "invalid_credential"),
    (403, "secret", "model_or_project_access"),
    (404, "secret", "model_or_project_access"),
    (429, "secret", "quota_exhaustion_or_rate_limit"),
    (403, "billing required secret", "billing_restriction"),
    (400, "schema secret", "schema_or_config"),
    (503, "secret", "network_or_sdk_error"),
])
def test_sanitized_classification(code, message, expected):
    assert classify_provider_error(errors.APIError(code, {"error": {"message": message}})) == expected


def test_failed_attempt_consumes_budget_and_zero_retries(caplog):
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        raise httpx.ConnectError("secret credential-bearing URL")
    budget = [1]
    adapter = GeminiAdapter(GeminiSettings(max_retries=0),
        client=SimpleNamespace(models=SimpleNamespace(generate_content=fail)), request_budget=budget)
    with pytest.raises(ModelUnavailable) as caught:
        adapter.generate(Answer, system="public", payload={})
    with pytest.raises(ModelUnavailable, match="budget exhausted"):
        adapter.generate(Answer, system="public", payload={})
    assert budget == [0] and len(calls) == 1 and len(adapter.telemetry) == 1
    assert "secret" not in str(caught.value) + caplog.text


def test_unexpected_sdk_failure_is_sanitized_and_not_retried():
    def fail(**kwargs):
        raise RuntimeError("secret")
    adapter = GeminiAdapter(client=SimpleNamespace(models=SimpleNamespace(generate_content=fail)))
    with pytest.raises(ModelUnavailable, match="network_or_sdk_error") as caught:
        adapter.generate(Answer, system="public", payload={})
    assert "secret" not in str(caught.value) and len(adapter.telemetry) == 1


def test_usage_includes_thinking_tokens():
    response = SimpleNamespace(text='{"answer":"Paris"}', candidates=[], model_version="test",
        usage_metadata=SimpleNamespace(prompt_token_count=3, candidates_token_count=4,
            total_token_count=12, thoughts_token_count=5))
    adapter = GeminiAdapter(client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw: response)))
    assert adapter.generate(Answer, system="public", payload={}).answer == "Paris"
    assert adapter.telemetry[0].thinking_tokens == 5 and adapter.telemetry[0].total_tokens == 12


def test_metadata_limit_and_secret_sanitization():
    def fail(**kw):
        raise errors.APIError(403, {"error": {"message": "secret"}})
    client = SimpleNamespace(models=SimpleNamespace(get=fail))
    with pytest.raises(ValueError):
        probe(model_ids=list("abcdef"), client=client)
    result = probe(model_ids=["test", "test"], client=client)
    assert result["metadata_requests"] == 1 and result["generation_requests"] == 0
    assert result["models"][0]["classification"] == "model_or_project_access"
    assert "secret" not in str(result)


def test_constructor_chroma_failure_is_explicit():
    from chromadb.errors import InternalError
    from rag.retriever import SharedRetriever, RetrievalUnavailable
    class BrokenClient:
        def get_or_create_collection(self, **kwargs):
            raise InternalError("backend detail")
    with pytest.raises(RetrievalUnavailable):
        SharedRetriever(client=BrokenClient(), embedder=lambda x: [])


def test_pageless_metadata_preserves_payload(offline_retriever):
    from memory.shared_memory import Evidence, SourceDocument
    from rag.models import SourceChunk, IndexedDocument
    from rag.retriever import SharedRetriever
    source = SourceDocument(title="Public snapshot", entity="Test", source_url="https://example.org/news",
        source_type="news", sha256="a" * 64)
    evidence = Evidence(source=source.title, source_id=source.source_id, source_url=source.source_url,
        source_type="news", locator="text-snapshot;chars=0:14", quote="Public content")
    chunk = SourceChunk(chunk_id="snapshot-1", source=source, kind="narrative", text="Public content", evidence=evidence)
    metadata = SharedRetriever._metadata(chunk)
    assert metadata["page"] == 0
    assert '"page":null' in metadata["payload"]
    assert offline_retriever.index(IndexedDocument(source=source, chunks=(chunk,), page_count=0)) == 1
    assert offline_retriever.page_chunks(source.source_id, None) == (chunk,)
    assert offline_retriever.retrieve("Public", {"doc_id": source.source_id})[0].chunk.evidence.page is None
    assert offline_retriever.validate_evidence(evidence.model_copy(update={"locator": evidence.locator + ";quote-offset=0"}))


def test_isolated_chroma_lifecycle():
    from scripts.diagnose_chroma import diagnose
    result = diagnose()
    assert result["status"] == "passed", result
    assert len(result["checks"]) == 5 and result["rows"] == 420


@pytest.mark.parametrize("change", [None, "text", "metadata", "source"])
def test_old_source_payload_defaults_preserve_semantic_immutability(offline_retriever, change):
    import json
    from datetime import datetime, timezone
    from memory.shared_memory import Evidence, SourceDocument
    from rag.models import SourceChunk, IndexedDocument

    source = SourceDocument(title="PDF source", entity="Test", source_url="https://example.org/report.pdf",
        source_type="annual_report", sha256="b" * 64)
    evidence = Evidence(source=source.title, source_id=source.source_id, source_url=source.source_url,
        source_type="annual_report", page=1, locator="pdf-page=1", quote="Original public report text")
    chunk = SourceChunk(chunk_id="old-pdf-1", source=source, kind="narrative", text=evidence.quote, evidence=evidence)
    metadata = offline_retriever._metadata(chunk)
    old_payload = json.loads(metadata["payload"])
    for field in ("published_at", "retrieved_at", "as_of_date"):
        old_payload["source"].pop(field)
    metadata["payload"] = json.dumps(old_payload)
    if change == "metadata":
        metadata["page"] = 2
    offline_retriever.collection.add(ids=[chunk.chunk_id], documents=[chunk.text],
        metadatas=[metadata], embeddings=offline_retriever._embed([chunk.text]))
    if change == "text":
        chunk = chunk.model_copy(update={"text": chunk.text + " changed"})
    elif change == "source":
        source = source.model_copy(update={"published_at": datetime(2024, 1, 1, tzinfo=timezone.utc)})
        chunk = chunk.model_copy(update={"source": source})
    document = IndexedDocument(source=source, chunks=(chunk,), page_count=1)
    if change is None:
        assert offline_retriever.index(document) == 0
    else:
        with pytest.raises(ValueError, match="identity/context|collides"):
            offline_retriever.index(document)
    # Comparison neither migrates defaults nor changes original metadata.
    stored = offline_retriever.collection.get(ids=[chunk.chunk_id], include=["metadatas"])
    assert stored["metadatas"] == [metadata]
    assert offline_retriever.collection.count() == 1
