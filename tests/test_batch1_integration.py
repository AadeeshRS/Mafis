"""Batch 1 integration over actual issuer PDF content and official Fed text.

Language model selection is an explicit offline mock. Chroma is real with a
test-only deterministic hash embedder; no generation or network calls occur.
"""
from datetime import date
from decimal import Decimal
import json
from pathlib import Path

import pytest

from agents.planner import PlannerAgent
from agents.report_agent import ReportAgent
from agents.verification_agent import VerificationAgent
from graph import (
    DocumentInput, build_extended_graph, run_extended_pipeline, save_outputs,
    verification_health_gate,
)
from memory.shared_memory import Claim, SharedMemory
from rag.market_sources import ingest_market_snapshot
from tests.fakes import GroundedMockLLM


SNAPSHOT = Path("tests/fixtures/market_snapshots/fomc_2024_01_31.json")


@pytest.fixture
def extended_inputs(prepared_document, offline_retriever, monkeypatch):
    def cached_ingest(*args, **kwargs):
        kwargs["retriever"].index(prepared_document)
        return prepared_document
    monkeypatch.setattr("graph.ingest_document", cached_ingest)
    snapshot = ingest_market_snapshot(SNAPSHOT, retriever=offline_retriever)
    document = DocumentInput(path="actual-pdf-prepared-by-session-fixture.pdf",
        source_url=prepared_document.source.source_url, title=prepared_document.source.title,
        entity=prepared_document.source.entity)
    return document, offline_retriever, snapshot


def run_case(inputs, **options):
    document, retriever, snapshot = inputs
    model = GroundedMockLLM(include_overview=True)
    state = run_extended_pipeline("Assess FY2024 financial health and macro risk assessment", document,
        retriever=retriever, document_llm=model, financial_llm=model,
        market_filters={"doc_id": snapshot.source.source_id, "kind": "narrative"},
        risk_categories=("financial", "macro"), **options)
    return state, model


def test_extended_plan_keeps_phase1_and_orders_version_sensitive_inputs():
    planner = PlannerAgent()
    assert planner.build_graph("risk assessment", True).status == "unsupported"
    plan = planner.build_extended_plan("risk assessment", True)
    assert plan.status == "ready" and len(plan.operations) == 4
    tasks = {t.name: t.depends_on for t in plan.tasks}
    assert tasks["financial"] == ("verify_primitives",)
    assert tasks["risk"] == ("verify_findings",)
    assert tasks["health_gate"] == ("verify_risk",)
    assert not any(word in tasks for word in ("bull", "bear", "critic", "retry"))


def test_extended_workflow_verifies_before_artifacts_and_pins_current_dependencies(extended_inputs):
    state, model = run_case(extended_inputs)
    store = state["memory"]
    assert state["health_gate"].decision == "passed", state["issues"]
    assert state["report"].status == "success", state["analysis_map"].issues
    assert len(store.get_calculations()) == 4 and len(model.calls) == 6
    for artifact in store.get_calculations():
        assert store.get_calculation_freshness(artifact.calculation_ref) == "current"
        for item in artifact.inputs:
            assert store.reference(item.claim_ref.claim_id) == item.claim_ref
            assert store.resolve(item.claim_ref).verification_status == "verified"
            assert item.claim_ref.version == 2
    for claim in store.get_claims():
        assert claim.verification_status == "verified"
        assert claim.agent != "Verification"  # Original authors are preserved.
        assert store.get_history(claim.claim_id)[0].verification_status == "pending"
        assert len(store.get_history(claim.claim_id)) == 2
        assert store.get_dependency_freshness(claim.claim_id) == "current"
    for key in ("document_result", "financial_result", "market_result", "risk_result"):
        assert all(store.reference(r.claim_id) == r for r in state[key].claim_refs)
    assert state["reanalysis_request"] is None
    assert not {"bull", "bear", "critic", "retry"} & set(state["stage_timings_ms"])
    assert "Market Context" in state["report"].markdown and "Risk Assessment" in state["report"].markdown
    assert "causal effects are unproven" in state["report"].markdown
    assert "Independent verification is pending" not in state["report"].markdown
    ReportAgent(store, extended_inputs[1], extended=True).validate_report(state["report"])


def test_rechecking_unchanged_claims_does_not_stale_accepted_artifacts(extended_inputs):
    state, _ = run_case(extended_inputs)
    store = state["memory"]
    before = len(store.get_verification_records())
    VerificationAgent(store, extended_inputs[1]).verify_all()
    assert len(store.get_verification_records()) == before
    assert all(store.get_calculation_freshness(a.calculation_ref) == "current" for a in store.get_calculations())


def test_outputs_include_history_checks_gate_and_exact_dependency_refs(extended_inputs, tmp_path):
    state, _ = run_case(extended_inputs)
    save_outputs(state, tmp_path)
    evidence = json.loads((tmp_path / "evidence.json").read_text())
    summary = json.loads((tmp_path / "run_summary.json").read_text())
    assert len(evidence["verification_records"]) == len(state["memory"].get_claims())
    assert len(evidence["claims"]) == 2 * len(state["memory"].get_claims())
    assert all(c["candidate_claim_refs"] for c in evidence["claims"] if c["agent"] == "RiskAgent")
    assert summary["health_gate"]["decision"] == "passed"
    assert summary["reanalysis_request"] is None
    assert "injected mock" in summary["execution_mode"]


def test_missing_document_fails_closed_without_models_or_retry(offline_retriever):
    model = GroundedMockLLM()
    state = run_extended_pipeline("financial health", retriever=offline_retriever,
        document_llm=model, financial_llm=model)
    assert not model.calls
    assert state["health_gate"].decision == "blocked" and state["health_gate"].total == 0
    assert state["report"].status == "partial"
    assert state["reanalysis_request"]["retry_executed"] is False
    assert state["reanalysis_request"]["trigger"] == "health_gate"
    assert "gate_blocked" in state["stage_timings_ms"]


def test_temporal_cutoff_preserves_missing_context_and_blocks_gate(extended_inputs):
    state, _ = run_case(extended_inputs, as_of=date(2024, 1, 30))
    assert not state["market_result"].claim_refs
    assert state["health_gate"].decision == "blocked"
    assert state["report"].status == "partial"
    assert "market_evidence_rejected" in state["report"].markdown
    assert "Historical source context as of 2024-01-31:" not in state["report"].markdown


def test_later_source_revision_invalidates_calculation_and_risk_report(extended_inputs):
    state, _ = run_case(extended_inputs)
    store = state["memory"]
    raw = next(c for c in store.get_claims() if c.claim_type == "raw_primitive")
    store.append(Claim.model_validate({**raw.model_dump(round_trip=True), "version": raw.version + 1,
        "verification_status": "pending"}))
    report_agent = ReportAgent(store, extended_inputs[1], extended=True)
    with pytest.raises(ValueError):
        report_agent.validate_report(state["report"])
    replacement = report_agent.generate_report()
    assert replacement.status == "partial" and replacement.analysis_map.excluded_claim_refs
    assert "Excluded claim" in replacement.markdown


def test_report_rejects_tampered_risk_prose(extended_inputs):
    state, _ = run_case(extended_inputs)
    agent = ReportAgent(state["memory"], extended_inputs[1], extended=True)
    changed = state["report"].model_copy(update={"markdown": state["report"].markdown + "Guaranteed losses.\n"})
    with pytest.raises(ValueError, match="rendering"):
        agent.validate_report(changed)


def test_empty_memory_and_threshold_configuration_are_checked_before_execution(extended_inputs):
    state, _ = run_case(extended_inputs)
    with pytest.raises(ValueError, match="empty run store"):
        run_extended_pipeline("financial health", memory=state["memory"])
    with pytest.raises(ValueError, match="threshold"):
        build_extended_graph(retriever=extended_inputs[1], health_threshold=float("nan"))
    assert verification_health_gate({}) == "unresolved"


def test_failed_primitive_check_cannot_supply_financial_artifacts(extended_inputs, monkeypatch):
    from agents.document_agent import DocumentAgent
    original = DocumentAgent.extract_primitives
    def tampered_after_extraction(agent, *args, **kwargs):
        result = original(agent, *args, **kwargs)
        current = next(c for c in agent.memory.get_claims() if c.metric == "revenue" and c.period.end_date.year == 2024)
        agent.memory.append(current.model_copy(update={"version": current.version + 1, "value": Decimal("999")}))
        return result
    monkeypatch.setattr(DocumentAgent, "extract_primitives", tampered_after_extraction)
    state, _ = run_case(extended_inputs)
    store = state["memory"]
    assert state["health_gate"].decision == "blocked" and state["report"].status == "partial"
    assert {a.operation for a in store.get_calculations()} == {"current_ratio"}
    failed = next(c for c in store.get_claims() if c.metric == "revenue" and c.period.end_date.year == 2024)
    assert failed.verification_status == "flagged" and failed.value == Decimal("999")
    assert "| 999 |" not in state["report"].markdown
    assert any("source_value" in gap for gap in state["reanalysis_request"]["missing_evidence"])


def test_extended_graph_has_conditional_health_edge_and_no_batch2_nodes(offline_retriever):
    app = build_extended_graph(retriever=offline_retriever,
        document_llm=GroundedMockLLM(), financial_llm=GroundedMockLLM())
    graph = app.get_graph()
    assert {"verify_primitives", "market_agent", "risk_agent", "health_gate", "gate_blocked"} <= set(graph.nodes)
    assert not {"bull_agent", "bear_agent", "critic", "retry"} & set(graph.nodes)
    assert any(edge.source == "health_gate" and edge.conditional for edge in graph.edges)


@pytest.mark.parametrize("case_id", ("apple_2024", "coca_cola_2024"))
def test_actual_other_issuer_pdfs_complete_extended_workflow(case_id, offline_retriever, tmp_path):
    """Exercise actual ingestion, annual-header contexts and all Batch 1 nodes."""
    case = next(c for c in json.loads(Path("tests/fixtures/phase1_cases.json").read_text())["cases"]
                if c["case_id"] == case_id)
    snapshot = ingest_market_snapshot(SNAPSHOT, retriever=offline_retriever)
    model = GroundedMockLLM()
    state = run_extended_pipeline(case["question"], case["document"], retriever=offline_retriever,
        document_llm=model, financial_llm=model,
        market_filters={"doc_id": snapshot.source.source_id, "kind": "narrative"},
        risk_categories=("financial", "macro"))
    save_outputs(state, tmp_path / case_id)
    assert state["health_gate"].decision == "passed", state["issues"]
    assert state["report"].status == "success", state["analysis_map"].issues
    assert len(state["memory"].get_calculations()) == 4
    assert all(state["memory"].is_current_verified(c.claim_id) for c in state["memory"].get_claims())
    assert all(state["memory"].get_calculation_freshness(a.calculation_ref) == "current"
               for a in state["memory"].get_calculations())
