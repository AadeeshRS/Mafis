"""Compatible Phase 1 flow and opt-in Batch 1 verified analysis workflow."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from time import perf_counter
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import Field, HttpUrl

from config import MAX_REANALYSIS_ITERATIONS, VERIFICATION_HEALTH_GATE_THRESHOLD
from config import DOCUMENT_MODEL, FINANCIAL_MODEL
from agents.contracts import AgentIssue
from agents.document_agent import DocumentAgent, DocumentResult
from agents.financial_agent import FinancialAgent, FinancialResult
from agents.market_agent import MarketResult
from agents.risk_agent import RiskResult
from agents.verification_gate import GateResult
from agents.planner import Phase1Plan, PlannerAgent
from agents.report_agent import AnalysisMap, FinancialReport, ReportAgent
from gemini import GeminiAdapter, GeminiSettings
from memory.shared_memory import EvidenceModel, SharedMemory, VerificationRecord
from rag.ingest import ingest_document
from rag.retriever import RetrievalUnavailable, get_shared_retriever


class DocumentInput(EvidenceModel):
    path: str = Field(min_length=1)
    source_url: HttpUrl
    title: str = Field(min_length=1)
    entity: str = Field(min_length=1)


class Phase1State(TypedDict, total=False):
    question: str
    document: DocumentInput | None
    memory: SharedMemory
    plan: Phase1Plan
    source_id: str
    document_result: DocumentResult
    financial_result: FinancialResult
    analysis_map: AnalysisMap
    report: FinancialReport
    issues: tuple[AgentIssue, ...]
    stage_timings_ms: dict[str, float]


class ExtendedState(Phase1State, total=False):
    market_result: MarketResult
    risk_result: RiskResult
    verification_records: tuple[VerificationRecord, ...]
    health_gate: GateResult
    reanalysis_request: dict[str, Any] | None
    bull_result: Any
    bear_result: Any
    critic_result: Any
    retry_decision: Any
    retry_execution: Any


def build_graph(*, retriever=None, document_llm=None, financial_llm=None):
    """Compile the sequential Phase 1 flow; claims never live in graph copies."""
    retriever = retriever if retriever is not None else get_shared_retriever()
    document_llm = document_llm if document_llm is not None else GeminiAdapter()
    financial_llm = financial_llm if financial_llm is not None else GeminiAdapter(GeminiSettings.from_env(FINANCIAL_MODEL))

    def planner(state):
        memory = state.get("memory") or SharedMemory()
        supplied = state.get("document")
        input_issues = ()
        try:
            payload = supplied.model_dump(round_trip=True) if isinstance(supplied, DocumentInput) else supplied
            document = DocumentInput.model_validate(payload) if payload is not None else None
        except (ValueError, TypeError):
            document = None
            input_issues = (AgentIssue(code="invalid_document_input", message="Document metadata needs a path, HTTP source URL, title, and entity"),)
        plan = PlannerAgent().build_graph(state.get("question", ""), document is not None)
        return {"memory": memory, "document": document, "plan": plan,
                "issues": state.get("issues", ()) + input_issues + plan.issues}

    def ingest(state):
        doc = state["document"]
        try:
            result = ingest_document(doc.path, source_url=str(doc.source_url), title=doc.title,
                                     entity=doc.entity, retriever=retriever)
            state["memory"].register_source(result.source)
            return {"source_id": result.source.source_id, "issues": state["issues"] + tuple(
                AgentIssue(code="ingestion_limitation", message=text) for text in result.limitations)}
        except (OSError, ValueError, RetrievalUnavailable) as exc:
            return {"issues": state["issues"] + (AgentIssue(code="ingestion_failed", message=str(exc)),)}

    def document(state):
        result = DocumentAgent(state["memory"], retriever, document_llm, source_id=state["source_id"]).extract_primitives(
            state["question"], metrics=state["plan"].metrics)
        return {"document_result": result, "issues": state["issues"] + result.issues}

    def financial(state):
        result = FinancialAgent(state["memory"], financial_llm).analyze(state["question"],
            operations=state["plan"].operations,
            primitive_claim_ids=[r.claim_id for r in state["document_result"].claim_refs
                                 if state["memory"].resolve(r).claim_type == "raw_primitive"],
            target_year=state["plan"].target_year)
        return {"financial_result": result, "issues": state["issues"] + result.issues}

    def analysis_map(state):
        mode = (f"Document model: {getattr(document_llm, 'mode', 'injected mock')}; "
                f"Financial model: {getattr(financial_llm, 'mode', 'injected mock')}; "
                f"embeddings: {retriever.embedding_model}")
        result = ReportAgent(state["memory"], retriever).build_analysis_map(state["issues"], execution_mode=mode)
        return {"analysis_map": result}

    def report(state):
        return {"report": ReportAgent(state["memory"], retriever).generate_report(state["analysis_map"])}

    def timed(name, function):
        def invoke(state):
            start = perf_counter()
            update = function(state)
            update["stage_timings_ms"] = {**state.get("stage_timings_ms", {}), name: (perf_counter() - start) * 1000}
            return update
        return invoke

    builder = StateGraph(Phase1State)
    for name, function in (("planner", planner), ("ingest", ingest), ("document_agent", document),
                           ("financial_agent", financial), ("analysis_map", analysis_map), ("report", report)):
        builder.add_node(name, timed(name, function))
    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", lambda s: "ingest" if s["plan"].status == "ready" else "analysis_map")
    builder.add_conditional_edges("ingest", lambda s: "document_agent" if s.get("source_id") else "analysis_map")
    builder.add_conditional_edges("document_agent", lambda s: "financial_agent" if s["plan"].operations
                                 and s["document_result"].claim_refs else "analysis_map")
    builder.add_edge("financial_agent", "analysis_map")
    builder.add_edge("analysis_map", "report")
    builder.add_edge("report", END)
    return builder.compile()


def run_pipeline(question: str, document: DocumentInput | dict | None = None, *, retriever=None,
                 document_llm=None, financial_llm=None, memory: SharedMemory | None = None) -> Phase1State:
    """A fresh per-run store plus one shared source index; no checkpoint database."""
    memory = memory if memory is not None else SharedMemory()
    if memory.get_claims() or memory.get_calculations():
        raise ValueError("Start a pipeline invocation with an empty run store")
    app = build_graph(retriever=retriever, document_llm=document_llm, financial_llm=financial_llm)
    return app.invoke({"question": question, "document": document, "memory": memory, "issues": ()})


def build_extended_graph(*, retriever=None, document_llm=None, financial_llm=None,
                         market_filters=None, risk_categories=None, as_of: date | None = None,
                         health_threshold: float = VERIFICATION_HEALTH_GATE_THRESHOLD, _full=False, _prepared=None):
    """Compile Batch 1: fresh checks, deterministic analysis, dated context, Risk.

    This is an explicit opt-in. A failed gate produces a partial report and a
    structured request only; it never executes a targeted retry or Batch 2 agent.
    """
    from agents.market_agent import MarketAgent
    from agents.risk_agent import RiskAgent
    from agents.verification_agent import VerificationAgent
    from agents.verification_gate import VerificationHealthGate

    retriever = retriever if retriever is not None else get_shared_retriever()
    document_llm = document_llm if document_llm is not None else GeminiAdapter()
    financial_llm = financial_llm if financial_llm is not None else GeminiAdapter(GeminiSettings.from_env(FINANCIAL_MODEL))
    # Validate configuration before ingestion or any possible model call.
    VerificationHealthGate(SharedMemory(), unsupported_threshold=health_threshold)

    def planner(state):
        memory = state.get("memory") or SharedMemory()
        supplied, issues = state.get("document"), state.get("issues", ())
        try:
            payload = supplied.model_dump(round_trip=True) if isinstance(supplied, DocumentInput) else supplied
            doc = DocumentInput.model_validate(payload) if payload is not None else None
        except (ValueError, TypeError):
            doc = None
            issues += (AgentIssue(code="invalid_document_input", message="Document metadata needs a path, HTTP source URL, title, and entity"),)
        plan = (PlannerAgent().build_full_plan if _full else PlannerAgent().build_extended_plan)(state.get("question", ""), doc is not None)
        return {"memory": memory, "document": doc, "plan": plan, "issues": issues + plan.issues,
                "verification_records": (), "reanalysis_request": None}

    def ingest(state):
        doc = state["document"]
        try:
            result = _prepared if _prepared is not None else ingest_document(doc.path, source_url=str(doc.source_url), title=doc.title,
                                     entity=doc.entity, retriever=retriever)
            if _prepared is not None:
                from hashlib import sha256
                if (result.source.sha256 != sha256(Path(doc.path).read_bytes()).hexdigest()
                        or str(result.source.source_url) != str(doc.source_url) or result.source.entity != doc.entity
                        or result.source.title != doc.title):
                    raise ValueError("Prepared source bundle does not match the requested document")
            state["memory"].register_source(result.source)
            return {"source_id": result.source.source_id, "issues": state["issues"] + tuple(
                AgentIssue(code="ingestion_limitation", message=text) for text in result.limitations)}
        except (OSError, ValueError, RetrievalUnavailable) as exc:
            return {"issues": state["issues"] + (AgentIssue(code="ingestion_failed", message=str(exc)),)}

    def document(state):
        result = DocumentAgent(state["memory"], retriever, document_llm, source_id=state["source_id"]).extract_primitives(
            state["question"], metrics=state["plan"].metrics)
        return {"document_result": result, "issues": state["issues"] + result.issues}

    def verify(state, identifiers):
        VerificationAgent(state["memory"], retriever).verify_all(identifiers)
        return {"verification_records": tuple(state["memory"].get_verification_records())}

    def verify_primitives(state):
        update = verify(state, [r.claim_id for r in state["document_result"].claim_refs])
        update["document_result"] = state["document_result"].model_copy(update={
            "claim_refs": tuple(state["memory"].reference(r.claim_id) for r in state["document_result"].claim_refs)})
        return update

    def financial(state):
        # Verification status revisions are already current before artifacts pin
        # inputs. Failed source checks cannot become numerical engine inputs.
        ids = [r.claim_id for r in state["document_result"].claim_refs
               if state["memory"].get_current(r.claim_id).claim_type == "raw_primitive"
               and state["memory"].get_current(r.claim_id).verification_status == "verified"]
        if not ids:
            issue = AgentIssue(code="no_verified_primitives", message="Financial analysis requires independently verified source inputs")
            return {"financial_result": FinancialResult(status="failed", issues=(issue,)),
                    "issues": state["issues"] + (issue,)}
        result = FinancialAgent(state["memory"], financial_llm, stable_ids=_full).analyze(state["question"],
            operations=state["plan"].operations, primitive_claim_ids=ids, target_year=state["plan"].target_year)
        return {"financial_result": result, "issues": state["issues"] + result.issues}

    def market(state):
        filters = dict(market_filters) if market_filters is not None else {"doc_id": state["source_id"], "kind": "narrative"}
        result = MarketAgent(state["memory"], retriever).research(state["question"], filters=filters, as_of=as_of)
        return {"market_result": result, "issues": state["issues"] + result.issues}

    def verify_findings(state):
        refs = tuple(state.get("financial_result", FinancialResult(status="success")).claim_refs) + state["market_result"].claim_refs
        update = verify(state, [r.claim_id for r in refs])
        for key in ("financial_result", "market_result"):
            if key in state:
                update[key] = state[key].model_copy(update={
                    "claim_refs": tuple(state["memory"].reference(r.claim_id) for r in state[key].claim_refs)})
        return update

    def risk(state):
        financial_refs = list(state["financial_result"].claim_refs) if "financial_result" in state else []
        result = RiskAgent(state["memory"], retriever, stable_ids=_full).assess_risk(financial_refs,
            list(state["market_result"].claim_refs), categories=risk_categories, as_of=as_of)
        return {"risk_result": result, "issues": state["issues"] + result.issues}

    def verify_risk(state):
        update = verify(state, [r.claim_id for r in state["risk_result"].claim_refs])
        update["risk_result"] = state["risk_result"].model_copy(update={
            "claim_refs": tuple(state["memory"].reference(r.claim_id) for r in state["risk_result"].claim_refs)})
        return update

    def gate(state):
        result = VerificationHealthGate(state["memory"], unsupported_threshold=health_threshold).evaluate(issues=state["issues"])
        gaps = [f"{i.code}: {i.message}" for i in state["issues"]]
        for reference in result.failing_claim_refs:
            records = state["memory"].get_verification_records(reference.claim_id)
            failed_checks = [f"{reference.claim_id}: {c.code}: {c.message}" for c in records[-1].checks
                             if c.outcome != "passed"] if records else []
            gaps.extend(failed_checks or [f"{reference.claim_id}: current independent verification or dependency freshness is missing"])
        request = None if result.decision == "passed" else {
            "trigger": "health_gate", "reanalysis_scope": list(result.reanalysis_scope),
            "failure_types": list(result.failure_types), "missing_evidence": gaps or [result.reason],
            "failing_claim_refs": [r.model_dump(mode="json") for r in result.failing_claim_refs],
            "retry_executed": False}
        return {"health_gate": result, "reanalysis_request": request}

    def blocked(state):
        return {"issues": state["issues"] + (AgentIssue(code="health_gate_blocked", message=state["health_gate"].reason),)}

    def analysis_map(state):
        mode = (f"Batch 1 extended; Document model: {getattr(document_llm, 'mode', 'injected mock')}; "
                f"Financial model: {getattr(financial_llm, 'mode', 'injected mock')}; "
                f"embeddings: {retriever.embedding_model}; Market: constrained source quotes; Risk: constrained templates")
        return {"analysis_map": ReportAgent(state["memory"], retriever, extended=True).build_analysis_map(
            state["issues"], execution_mode=mode, health_gate=state["health_gate"])}

    def report(state):
        return {"report": ReportAgent(state["memory"], retriever, extended=True).generate_report(state["analysis_map"])}

    def timed(name, function):
        def invoke(state):
            start = perf_counter()
            update = function(state)
            update["stage_timings_ms"] = {**state.get("stage_timings_ms", {}), name: (perf_counter() - start) * 1000}
            return update
        return invoke

    builder = StateGraph(ExtendedState)
    nodes = (("planner", planner), ("ingest", ingest), ("document_agent", document),
        ("verify_primitives", verify_primitives), ("financial_agent", financial), ("market_agent", market),
        ("verify_findings", verify_findings), ("risk_agent", risk), ("verify_risk", verify_risk),
        ("health_gate", gate), ("gate_blocked", blocked), ("analysis_map", analysis_map), ("report", report))
    for name, function in nodes:
        builder.add_node(name, timed(name, function))
    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", lambda s: "ingest" if s["plan"].status == "ready" else "health_gate",
                                  {"ingest": "ingest", "health_gate": "health_gate"})
    builder.add_conditional_edges("ingest", lambda s: "document_agent" if s.get("source_id") else "health_gate",
                                  {"document_agent": "document_agent", "health_gate": "health_gate"})
    builder.add_edge("document_agent", "verify_primitives")
    builder.add_conditional_edges("verify_primitives", lambda s: "financial_agent" if s["plan"].operations else "market_agent",
                                  {"financial_agent": "financial_agent", "market_agent": "market_agent"})
    builder.add_edge("financial_agent", "market_agent")
    builder.add_edge("market_agent", "verify_findings")
    builder.add_edge("verify_findings", "risk_agent")
    builder.add_edge("risk_agent", "verify_risk")
    builder.add_edge("verify_risk", "health_gate")
    builder.add_conditional_edges("health_gate", verification_health_gate,
                                  {"proceed": "analysis_map", "unresolved": "gate_blocked"})
    builder.add_edge("gate_blocked", "analysis_map")
    builder.add_edge("analysis_map", "report")
    builder.add_edge("report", END)
    return builder.compile()


def run_extended_pipeline(question: str, document: DocumentInput | dict | None = None, *, retriever=None,
                          document_llm=None, financial_llm=None, memory: SharedMemory | None = None,
                          market_filters=None, risk_categories=None, as_of: date | None = None,
                          health_threshold: float = VERIFICATION_HEALTH_GATE_THRESHOLD) -> ExtendedState:
    """Run only the extended Batch 1 workflow in a fresh isolated memory store."""
    memory = memory if memory is not None else SharedMemory()
    if memory.get_claims() or memory.get_calculations() or memory.get_verification_records():
        raise ValueError("Start a pipeline invocation with an empty run store")
    app = build_extended_graph(retriever=retriever, document_llm=document_llm, financial_llm=financial_llm,
        market_filters=market_filters, risk_categories=risk_categories, as_of=as_of, health_threshold=health_threshold)
    return app.invoke({"question": question, "document": document, "memory": memory, "issues": ()})


def save_outputs(state: Phase1State, directory: str | Path, *, adapters=()) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.md").write_text(state["report"].markdown, encoding="utf-8")
    (directory / "analysis_map.json").write_text(state["analysis_map"].model_dump_json(indent=2), encoding="utf-8")
    claims = state["memory"].get_claims(min_version_only=False)
    source_ids = {e.source_id for c in claims for e in c.evidence}
    evidence_export = {"run_id": state["memory"].run_id,
        "sources": [state["memory"].get_source(s).model_dump(mode="json") for s in sorted(source_ids)],
        "claims": [c.model_dump(mode="json") for c in claims],
        "calculations": [c.model_dump(mode="json") for c in state["memory"].get_calculations()]}
    if "health_gate" in state:
        evidence_export["verification_records"] = [r.model_dump(mode="json") for r in state["memory"].get_verification_records()]
    if "critic_result" in state or "retry_decision" in state:
        evidence_export["contradictions"] = [r.model_dump(mode="json") for r in state["memory"].get_contradictions(history=True)]
        evidence_export["retry_decisions"] = [r.model_dump(mode="json") for r in state["memory"].get_retry_decisions()]
        evidence_export["gate_history"] = state["memory"].get_health_gate_history()
        evidence_export["retry_execution"] = state.get("retry_execution")
    (directory / "evidence.json").write_text(json.dumps(evidence_export, indent=2,
        default=lambda item:item.model_dump(mode="json")) + "\n", encoding="utf-8")
    adapters=tuple({id(adapter):adapter for adapter in adapters}.values())
    summary = {"run_id": state["memory"].run_id, "report_status": state["report"].status,
        "execution_mode": state["analysis_map"].execution_mode,
        "claim_count": len(state["memory"].get_claims()),
        "calculation_count": len(state["memory"].get_calculations()), "stage_timings_ms": state["stage_timings_ms"],
        "issues": [i.model_dump() for i in state["analysis_map"].issues],
        "model_telemetry": [e.model_dump() for adapter in adapters for e in getattr(adapter, "telemetry", [])]}
    if "health_gate" in state:
        summary["health_gate"] = state["health_gate"].model_dump(mode="json")
        summary["reanalysis_request"] = state.get("reanalysis_request")
    (directory / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Run the approved Phase 1 pipeline. Model calls require explicit --live.")
    for name in ("pdf", "source-url", "title", "entity", "question"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--output", default="output/phase1")
    parser.add_argument("--live", action="store_true", help="Explicitly enable API requests; account billing/quota must be checked by the caller")
    parser.add_argument("--extended", action="store_true", help="Opt into Batch 1 independent verification, dated Market, Risk and Health Gate")
    parser.add_argument("--full", action="store_true", help="Opt into Bull/Bear/Critic and the single targeted retry")
    parser.add_argument("--free-tier-confirmed",action="store_true",help="Caller attestation required for full live flow")
    parser.add_argument("--request-budget",type=int,default=12,help="Full flow shared generation transport attempt cap (1-12)")
    parser.add_argument("--as-of", type=date.fromisoformat, help="Optional Market/Risk evidence cutoff, YYYY-MM-DD")
    parser.add_argument("--health-threshold", type=float, default=VERIFICATION_HEALTH_GATE_THRESHOLD)
    parser.add_argument("--market-snapshot", help="Official text snapshot manifest to index through the shared retriever (extended only)")
    parser.add_argument("--risk-category", action="append", choices=("financial", "operational", "market", "regulatory", "macro", "governance", "competitive"),
                        help="Constrain requested risk coverage; repeat for multiple categories (extended only)")
    args = parser.parse_args()
    if args.full and args.extended:
        parser.error("--full and --extended are mutually exclusive")
    if args.full and (not 1 <= args.request_budget <= 12 or args.live and not args.free_tier_confirmed):
        parser.error("Full live flow requires free-tier attestation and a shared 1-12 attempt budget")
    if not (args.extended or args.full) and (args.market_snapshot or args.risk_category or args.as_of):
        parser.error("--market-snapshot, --risk-category and --as-of require --extended")
    document_adapter = GeminiAdapter(GeminiSettings.from_env(DOCUMENT_MODEL), allow_live=args.live)
    financial_adapter = GeminiAdapter(GeminiSettings.from_env(FINANCIAL_MODEL), allow_live=args.live)
    if args.full:
        budget=[args.request_budget]
        document_adapter.request_budget=financial_adapter.request_budget=budget
    runner = run_full_pipeline if args.full else run_extended_pipeline if args.extended else run_pipeline
    options = {"as_of": args.as_of, "health_threshold": args.health_threshold,
               "risk_categories": tuple(args.risk_category) if args.risk_category else None} if args.extended or args.full else {}
    if args.full:
        options.update({key:GeminiAdapter(document_adapter.settings,allow_live=args.live,request_budget=budget)
                        for key in ("bull_llm","bear_llm","critic_llm")})
    if args.market_snapshot:
        from rag.market_sources import ingest_market_snapshot
        retriever = get_shared_retriever()
        snapshot = ingest_market_snapshot(args.market_snapshot, retriever=retriever)
        options.update(retriever=retriever, market_filters={"doc_id": snapshot.source.source_id, "kind": "narrative"})
    state = runner(args.question, DocumentInput(path=args.pdf, source_url=args.source_url, title=args.title, entity=args.entity),
        document_llm=document_adapter, financial_llm=financial_adapter, **options)
    adapters = (document_adapter, financial_adapter) + tuple(options[k] for k in ("bull_llm", "bear_llm", "critic_llm") if k in options)
    save_outputs(state, args.output, adapters=adapters)
    print(json.dumps({"status": state["report"].status, "output": str(Path(args.output).resolve()),
                      "execution_mode": state["analysis_map"].execution_mode}))


def verification_health_gate(state: dict[str, Any]) -> str:
    """Route on aggregate unsupported/contradicted rate.

    Args:
        state: Graph state including verification stats.

    Returns:
        Route label: 'proceed' (below threshold) or 'reanalysis'/'unresolved'.
    """
    result = state.get("health_gate")
    return "proceed" if result is not None and result.decision == "passed" else "unresolved"


def should_reanalyze(state: dict[str, Any]) -> str:
    """Critic-gated re-analysis decision respecting the shared iteration cap.

    Args:
        state: Graph state including retry count and contradictions.

    Returns:
        Route label: 'reanalyze', 'unresolved', or 'report'.
    """
    decision = state.get("retry_decision")
    if decision is None:
        return "report"
    return "reanalyze" if decision.outcome == "executed" else "unresolved"


def build_full_graph(*, retriever=None, document_llm=None, financial_llm=None, bull_llm=None, bear_llm=None, critic_llm=None,
                     market_filters=None,risk_categories=None,as_of=None,health_threshold=VERIFICATION_HEALTH_GATE_THRESHOLD,
                     reanalysis=True, bull_bear=True, critic=True, prepared_document=None):
    from agents.full_workflow import requests_for, run_reasoning, execute_targeted
    from agents.verification_gate import VerificationHealthGate
    retriever = retriever if retriever is not None else get_shared_retriever()
    document_llm = document_llm if document_llm is not None else GeminiAdapter()
    financial_llm = financial_llm if financial_llm is not None else GeminiAdapter()
    bull_llm = bull_llm if bull_llm is not None else GeminiAdapter()
    bear_llm = bear_llm if bear_llm is not None else GeminiAdapter()
    critic_llm = critic_llm if critic_llm is not None else GeminiAdapter()
    # Apply one transport counter even to callers of the Python entry point.
    # Offline doubles have no SDK requests; the CLI supplies this same object.
    adapters = [a for a in (document_llm,financial_llm,bull_llm,bear_llm,critic_llm) if isinstance(a,GeminiAdapter)]
    supplied = [a.request_budget for a in adapters if a.request_budget is not None]
    if supplied and (any(b is not supplied[0] for b in supplied) or len(supplied[0])!=1
                     or not isinstance(supplied[0][0],int) or not 0 <= supplied[0][0] <= 12):
        raise ValueError("Full flow requires one shared generation counter bounded by 12 attempts")
    shared_budget = supplied[0] if supplied else [12]
    for adapter in adapters:
        adapter.request_budget = shared_budget
    initial = build_extended_graph(retriever=retriever,document_llm=document_llm,financial_llm=financial_llm,
        market_filters=market_filters,risk_categories=risk_categories,as_of=as_of,health_threshold=health_threshold,_full=True,_prepared=prepared_document)
    def refresh(s):
        factual_issues = tuple(i for i in s["issues"] if not i.code.startswith(("bull_","bear_","critic_","health_gate_blocked")))
        s["health_gate"] = VerificationHealthGate(s["memory"],health_threshold).evaluate(issues=factual_issues)
        return s
    def evidence(s):
        return initial.invoke(s)
    def reasoning(s):
        if bull_bear:
            run_reasoning(s,retriever,bull_llm,bear_llm,critic_llm,critic=critic)
        elif critic:
            run_reasoning(s,retriever,bull_llm,bear_llm,critic_llm,stances=(),critic=True)
        return refresh(s)
    def allocate(s):
        requests = requests_for(s)
        if requests:
            s["retry_decision"] = PlannerAgent().allocate_retry(s["memory"],requests,enabled=reanalysis)
        return s
    def targeted(s):
        decision = s["retry_decision"]
        execute_targeted(s,decision,retriever,document_llm,financial_llm,market_filters,risk_categories,as_of)
        refresh(s)
        s["retry_execution"]["nodes"] += ("health_gate",)
        if s["health_gate"].decision == "passed":
            stances = tuple(c for c in ("Bull","Bear") if c in decision.rerun_nodes
                or not s.get(c.lower()+"_result") or any(not s["memory"].is_current_verified(r.claim_id) for r in s[c.lower()+"_result"].claim_refs))
            if bull_bear or critic:
                run_reasoning(s,retriever,bull_llm,bear_llm,critic_llm,stances=stances if bull_bear else (),critic=critic)
                s["retry_execution"]["nodes"] += (stances if bull_bear else ()) + (("critic",) if critic else ())
        elif critic and s["memory"].get_contradictions():
            from agents.critic_agent import CriticAgent
            s["critic_result"]=CriticAgent(s["memory"]).check_contradictions(run_iteration=1,exhausted=True)
            s["retry_execution"]["nodes"] += ("critic:mechanical",)
        return refresh(s)
    def final(s):
        remaining = requests_for(s)
        if remaining and s.get("retry_decision") and s["retry_decision"].outcome == "executed":
            s["terminal_retry_decision"] = PlannerAgent().allocate_retry(s["memory"],remaining)
        if s["health_gate"].decision == "blocked" and not any(i.code == "health_gate_blocked" for i in s["issues"]):
            s["issues"] += (AgentIssue(code="health_gate_blocked",message=s["health_gate"].reason),)
        agent = ReportAgent(s["memory"],retriever,full=True)
        if s.get("retry_execution"):
            s["retry_execution"]["nodes"] += ("report",)
        modes="; ".join(name+"="+getattr(adapter,"mode","injected offline model double") for name,adapter in
            (("Document",document_llm),("Financial",financial_llm),("Bull",bull_llm),("Bear",bear_llm),("Critic",critic_llm)))
        s["analysis_map"] = agent.build_analysis_map(s["issues"],execution_mode="Full MAFIS; "+modes,health_gate=s["health_gate"])
        s["report"] = agent.generate_report(s["analysis_map"])
        return s
    builder = StateGraph(ExtendedState)
    for name, fn in (("evidence",evidence),("adversarial",reasoning),("planner_retry",allocate),("targeted_retry",targeted),("final_report",final)):
        def timed(s, fn=fn,name=name):
            start=perf_counter(); update=fn(dict(s)); update["stage_timings_ms"]={**update.get("stage_timings_ms",{}),name:(perf_counter()-start)*1000}; return update
        builder.add_node(name,timed)
    builder.add_edge(START,"evidence")
    builder.add_conditional_edges("evidence",lambda s:"adversarial" if s["health_gate"].decision == "passed" else "planner_retry",["adversarial","planner_retry"])
    builder.add_edge("adversarial","planner_retry")
    builder.add_conditional_edges("planner_retry",lambda s:"targeted_retry" if s.get("retry_decision") and s["retry_decision"].outcome == "executed" else "final_report",["targeted_retry","final_report"])
    builder.add_edge("targeted_retry","final_report"); builder.add_edge("final_report",END)
    return builder.compile()


def run_full_pipeline(question,document=None,*,memory=None,**options):
    memory = memory if memory is not None else SharedMemory()
    if memory.get_claims() or memory.get_calculations() or memory.get_retry_decisions():
        raise ValueError("Start a pipeline invocation with an empty run store")
    return build_full_graph(**options).invoke({"question":question,"document":document,"memory":memory,"issues":()},config={"recursion_limit":20})


if __name__ == "__main__":
    main()
