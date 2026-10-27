from decimal import Decimal
import json
from pathlib import Path
import shutil

import pytest

from agents.report_agent import ReportAgent
from gemini import GeminiAdapter, GeminiSettings
from graph import DocumentInput, build_graph, run_pipeline, save_outputs
from memory.shared_memory import SharedMemory
from rag.retriever import RetrievalUnavailable, SharedRetriever
from tests.conftest import HashTestEmbedder
from tests.fakes import GroundedMockLLM, ReplaySDKClient


@pytest.fixture(scope="module")
def end_to_end(tmp_path_factory):
    root = tmp_path_factory.mktemp("full_phase1")
    source = Path(__file__).parent / "fixtures/nvidia_2024"
    # The inference input directory contains only document bytes, no gold files.
    pdf = root / "unlabelled-document.bin"
    shutil.copyfile(source / "annual_report.pdf", pdf)
    identity = DocumentInput(path=str(pdf),
        source_url="https://s201.q4cdn.com/141608511/files/doc_financials/2024/ar/NVIDIA-2024-Annual-Report.pdf",
        title="NVIDIA FY2024 Annual Report (including Form 10-K)", entity="NVIDIA Corporation")
    index = SharedRetriever(path=root / "chroma_db", embedder=HashTestEmbedder(), embedding_model="test-hash-v1")
    client = ReplaySDKClient()
    document = GeminiAdapter(GeminiSettings(model_id="gemini-3.5-flash-lite"), client=client)
    financial = GeminiAdapter(GeminiSettings(model_id="gemini-3.8-flash"), client=client)
    state = run_pipeline("Assess FY2024 financial health, revenue growth, profitability and liquidity",
        identity, retriever=index, document_llm=document, financial_llm=financial)
    return state, index, client, (document, financial), root


def test_full_pdf_rag_sdk_memory_engine_langgraph_report(end_to_end):
    state, index, client, adapters, _ = end_to_end
    assert state["report"].status == "success", state["analysis_map"].issues
    assert state["document_result"].status == state["financial_result"].status == "success"
    assert set(state["stage_timings_ms"]) == {"planner", "ingest", "document_agent", "financial_agent", "analysis_map", "report"}
    store = state["memory"]
    assert len(store.get_calculations()) == 4
    assert len([c for c in store.get_claims() if c.claim_type == "raw_primitive"]) == 6
    assert any(c.claim_type == "qualitative" for c in store.get_claims())
    assert len(client.calls) == 6 and sum(len(a.telemetry) for a in adapters) == 6
    assert "mocked" in state["report"].markdown
    assert store.get_claims(verification_status="verified") == []
    ReportAgent(store, index).validate_report(state["report"])
    gold = json.loads((Path(__file__).parent / "fixtures/nvidia_2024/annotations.json").read_text())
    raw = [c for c in store.get_claims() if c.claim_type == "raw_primitive"]
    for expected in gold["values"]:
        claim = next(c for c in raw if c.metric == expected["metric"] and c.period.end_date.isoformat() == expected["period_end"])
        assert claim.value == Decimal(expected["value"]) and claim.evidence[0].page == expected["pdf_page"]
    expected_display = {"revenue_growth": "125.8545", "operating_margin": "54.1217", "net_margin": "48.8493", "current_ratio": "4.1713"}
    assert {a.operation: str(a.display_value) for a in store.get_calculations()} == expected_display


def test_outputs_are_reviewable_and_keep_exact_artifacts(end_to_end):
    state, _, _, adapters, root = end_to_end
    save_outputs(state, root / "outputs", adapters=adapters)
    assert (root / "outputs/report.md").read_text(encoding="utf-8") == state["report"].markdown
    exported = json.loads((root / "outputs/evidence.json").read_text())
    assert len(exported["calculations"]) == 4 and exported["run_id"] == state["memory"].run_id
    assert len(exported["claims"]) == 11 and exported["sources"][0]["sha256"]
    summary = json.loads((root / "outputs/run_summary.json").read_text())
    assert "mocked" in summary["execution_mode"] and summary["report_status"] == "success"
    assert all(t["total_tokens"] is None for t in summary["model_telemetry"])


def test_missing_document_returns_partial_without_model_calls(offline_retriever):
    llm = GroundedMockLLM()
    state = run_pipeline("financial health", retriever=offline_retriever, document_llm=llm, financial_llm=llm)
    assert state["report"].status == "partial" and not llm.calls
    assert "missing_document" in state["report"].markdown
    assert set(state["stage_timings_ms"]) == {"planner", "analysis_map", "report"}


def test_unsupported_question_stops_before_ingestion(offline_retriever):
    llm = GroundedMockLLM()
    document = DocumentInput(path="absent.pdf", source_url="https://example.test/report.pdf", title="Report", entity="Company")
    state = run_pipeline("Perform a DCF valuation", document, retriever=offline_retriever, document_llm=llm, financial_llm=llm)
    assert state["plan"].status == "unsupported" and state["report"].status == "partial"
    assert not llm.calls and "ingest" not in state["stage_timings_ms"]


def test_unreadable_document_fails_visibly(offline_retriever):
    llm = GroundedMockLLM()
    document = DocumentInput(path="absent.pdf", source_url="https://example.test/report.pdf", title="Report", entity="Company")
    state = run_pipeline("financial health", document, retriever=offline_retriever, document_llm=llm, financial_llm=llm)
    assert state["report"].status == "partial" and "ingestion_failed" in state["report"].markdown
    assert not llm.calls


def test_embedding_failure_does_not_build_on_invalid_foundation(offline_retriever, monkeypatch):
    def fail(*args, **kwargs):
        raise RetrievalUnavailable("Embedding model unavailable")
    monkeypatch.setattr("graph.ingest_document", fail)
    document = DocumentInput(path="unused.pdf", source_url="https://example.test/report.pdf", title="Report", entity="Company")
    llm = GroundedMockLLM()
    state = run_pipeline("financial health", document, retriever=offline_retriever, document_llm=llm, financial_llm=llm)
    assert state["report"].status == "partial" and not llm.calls
    assert "document_agent" not in state["stage_timings_ms"]


def test_runs_remain_isolated_and_existing_memory_is_not_overwritten(end_to_end, offline_retriever):
    original = end_to_end[0]["memory"]
    count = len(original.get_claims())
    llm = GroundedMockLLM()
    state = run_pipeline("financial health", retriever=offline_retriever, document_llm=llm, financial_llm=llm)
    assert state["memory"].run_id != original.run_id and not state["memory"].get_claims()
    assert len(original.get_claims()) == count
    with pytest.raises(ValueError, match="empty run store"):
        run_pipeline("financial health", retriever=offline_retriever, memory=original)


def test_graph_has_only_phase1_nodes(offline_retriever):
    app = build_graph(retriever=offline_retriever, document_llm=GroundedMockLLM(), financial_llm=GroundedMockLLM())
    assert set(app.get_graph().nodes) == {"__start__", "__end__", "planner", "ingest", "document_agent", "financial_agent", "analysis_map", "report"}


def test_invalid_document_metadata_returns_a_partial_result(offline_retriever):
    llm = GroundedMockLLM()
    state = run_pipeline("financial health", {"path": "file.pdf", "source_url": "not a URL"},
        retriever=offline_retriever, document_llm=llm, financial_llm=llm)
    assert state["report"].status == "partial" and not llm.calls
    assert "invalid_document_input" in state["report"].markdown


def test_disabled_gemini_produces_partial_report_without_financial_calls(prepared_document, offline_retriever, monkeypatch):
    def cached_ingest(*args, **kwargs):
        kwargs["retriever"].index(prepared_document)
        return prepared_document
    monkeypatch.setattr("graph.ingest_document", cached_ingest)
    llm = GroundedMockLLM()
    document = DocumentInput(path="already-parsed.pdf", source_url=str(prepared_document.source.source_url),
        title=prepared_document.source.title, entity=prepared_document.source.entity)
    state = run_pipeline("financial health", document, retriever=offline_retriever,
        document_llm=GeminiAdapter(), financial_llm=llm)
    assert state["report"].status == "partial" and not llm.calls
    assert not state["memory"].get_claims() and "financial_agent" not in state["stage_timings_ms"]
    assert "extraction_unavailable" in state["report"].markdown


def test_missing_calculation_input_is_a_partial_end_to_end_report(prepared_document, offline_retriever, monkeypatch):
    def cached_ingest(*args, **kwargs):
        kwargs["retriever"].index(prepared_document)
        return prepared_document
    def omit_net_income(response, payload):
        if payload["task"] == "document_extraction":
            response["primitives"] = [p for p in response["primitives"] if p["metric"] != "net_income"]
        return response
    monkeypatch.setattr("graph.ingest_document", cached_ingest)
    document = DocumentInput(path="already-parsed.pdf", source_url=str(prepared_document.source.source_url),
        title=prepared_document.source.title, entity=prepared_document.source.entity)
    llm = GroundedMockLLM(transform=omit_net_income)
    state = run_pipeline("financial health", document, retriever=offline_retriever, document_llm=llm, financial_llm=llm)
    assert state["report"].status == "partial" and len(state["memory"].get_calculations()) == 3
    assert "net_margin |" not in state["report"].markdown and "missing_metrics" in state["report"].markdown
