from decimal import Decimal

import pytest

from agents.document_agent import DocumentAgent
from gemini import ModelOutputError
from memory.shared_memory import SharedMemory
from rag.models import IndexedDocument
from tests.fakes import GroundedMockLLM


@pytest.fixture
def document_agent(prepared_document, offline_retriever):
    # Real source cells and a small real Chroma index; mocked embeddings/LLM.
    chunks = tuple(c for c in prepared_document.chunks if c.kind == "table" or c.evidence.page == 155)
    offline_retriever.index(IndexedDocument(source=prepared_document.source, chunks=chunks, page_count=187))
    store = SharedMemory()
    store.register_source(prepared_document.source)
    llm = GroundedMockLLM()
    return store, llm, DocumentAgent(store, offline_retriever, llm, source_id=prepared_document.source.source_id)


def test_document_agent_writes_grounded_pending_primitives(document_agent):
    store, llm, agent = document_agent
    outcome = agent.extract_primitives("Analyze annual financial health")
    assert outcome.status == "success", outcome.issues
    assert len(outcome.claim_refs) == 6
    assert all(c.support_level == "single_source" and c.verification_status == "pending" for c in store.get_claims())
    assert all(store.resolve(r).evidence[0].page in (150, 152) for r in outcome.claim_refs)
    assert all(c.value.is_finite() and isinstance(c.value, Decimal) for c in store.get_claims())
    assert store.get_calculations() == []
    assert "UNTRUSTED DATA" in llm.calls[0]["system"]
    assert "annotations" not in repr(llm.calls[0]["payload"])
    assert agent.extract_primitives("Analyze annual financial health").claim_refs == outcome.claim_refs


@pytest.mark.parametrize(("field", "value"), [
    ("value", "999999"), ("value", "NaN"), ("chunk_id", "invented"),
    ("cell_id", "invented"), ("currency", "EUR"), ("scale", 1),
    ("unit", "shares"), ("period_end", "2020-01-01"),
])
def test_invented_number_or_locator_is_rejected(document_agent, field, value):
    store, llm, agent = document_agent
    def transform(response, _):
        response["primitives"][0][field] = value
        return response
    llm.transform = transform
    outcome = agent.extract_primitives("Analyze annual financial health")
    assert outcome.status == "partial"
    assert "invalid_source_cell" in {i.code for i in outcome.issues}
    assert len(store.get_claims()) == 5


def test_missing_facts_and_duplicate_inputs_are_visible(document_agent):
    store, llm, agent = document_agent
    def transform(response, _):
        response["primitives"] = response["primitives"][:1] * 2
        return response
    llm.transform = transform
    outcome = agent.extract_primitives("Analyze annual financial health")
    assert outcome.status == "partial" and len(store.get_claims()) == 1
    assert {"invalid_source_cell", "missing_primitives", "missing_metrics"}.issubset({i.code for i in outcome.issues})


def test_exact_source_fact_is_supported_but_paraphrase_rejected(document_agent):
    store, llm, agent = document_agent
    def transform(response, payload):
        chunk = next(c for c in payload["chunks"] if c["kind"] == "narrative")
        response["facts"] = [{"chunk_id": chunk["chunk_id"], "quote": chunk["text"][:60]},
                             {"chunk_id": chunk["chunk_id"], "quote": "An invented company fact with no source"}]
        return response
    llm.transform = transform
    outcome = agent.extract_primitives("Company overview")
    facts = [c for c in store.get_claims() if c.claim_type == "qualitative"]
    assert len(facts) == 1 and facts[0].claim == facts[0].evidence[0].quote
    assert outcome.status == "partial"


def test_no_evidence_does_not_call_model(document_agent):
    store, llm, agent = document_agent
    outcome = agent.extract_primitives("missing", {"page": 999})
    assert outcome.status == "failed" and outcome.issues[0].code == "missing_evidence"
    assert not llm.calls and not store.get_claims()


def test_model_failure_produces_explicit_partial_boundary(document_agent):
    store, llm, agent = document_agent
    def fail(*args, **kwargs):
        raise ModelOutputError("bad structured response")
    llm.generate = fail
    outcome = agent.extract_primitives("financial health")
    assert outcome.status == "failed" and not store.get_claims()


def test_cross_document_filter_is_rejected(document_agent):
    _, llm, agent = document_agent
    assert agent.extract_primitives("financial health", {"doc_id": "other"}).status == "failed"
    assert not llm.calls
