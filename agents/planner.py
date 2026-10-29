"""Planner Agent — builds the task/dependency graph, decides which agents run, computes re-analysis scope.

Single entry point for query routing. Owns the shared re-analysis budget
(max 1 total iteration across Health Gate and Critic triggers).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from agents.contracts import AgentIssue
from engine.financial_engine import FinancialEngine
from memory.shared_memory import CalculationOperation, EvidenceModel, ReanalysisRequest, RetryDecision
from uuid import uuid4


class PlanTask(EvidenceModel):
    name: str
    depends_on: tuple[str, ...] = ()


class Phase1Plan(EvidenceModel):
    status: Literal["ready", "unsupported", "missing_document"]
    query: str
    operations: tuple[CalculationOperation, ...] = ()
    metrics: tuple[str, ...] = ()
    target_year: int | None = None
    tasks: tuple[PlanTask, ...] = ()
    issues: tuple[AgentIssue, ...] = ()


class PlannerAgent:
    """Plans task graph and scoped re-analysis within the retry budget."""

    def build_full_plan(self, query, has_documents):
        if not isinstance(query, str):
            return self.build_extended_plan(query, has_documents)
        # Full mode explicitly supports these tasks; do not preserve a false
        # unsupported-scope warning from the legacy query router.
        analysis_query = re.sub(r"\b(bull|bear|critic|adversarial|opposing)\b", "", query, flags=re.I)
        if not re.search(r"financial|revenue|margin|liquidity|overview|market analysis|risk assessment", analysis_query, re.I):
            analysis_query += " financial health"
        base = self.build_extended_plan(analysis_query, has_documents)
        tasks = base.tasks[:-2] + (
            PlanTask(name="bull", depends_on=("health_gate",)),
            PlanTask(name="bear", depends_on=("health_gate",)),
            PlanTask(name="critic", depends_on=("bull", "bear")),
            PlanTask(name="targeted_retry", depends_on=("critic",)),
            PlanTask(name="analysis_map", depends_on=("targeted_retry",)),
            PlanTask(name="report", depends_on=("analysis_map",)),)
        return base.model_copy(update={"query":query,"tasks":tasks})

    def allocate_retry(self, memory, requests, *, enabled=True):
        requests = tuple(ReanalysisRequest.model_validate(r.model_dump(round_trip=True)) for r in requests)
        refs = tuple(dict.fromkeys(r for request in requests for r in request.affected_refs))
        for ref in refs:
            memory.resolve(ref)
        components = set(c for request in requests for c in request.components)
        supported = {"DocumentAgent","FinancialAgent","MarketAgent","RiskAgent","Bull","Bear"}
        before = memory.retry_budget_remaining
        if not requests or not enabled or not before or not components or not components <= supported or not any(r.retryable for r in requests):
            reason=("No correction requests" if not requests else "Analytical correction disabled for this condition" if not enabled
                else "Global analytical retry is exhausted" if not before else "No supported recoverable component scope" if not components or not components<=supported
                else "Requests are marked irrecoverable; no correction executed")
            return memory._record_retry_decision(RetryDecision(decision_id="retry:"+str(uuid4()),
                requests=requests, affected_refs=refs, rerun_nodes=(), budget_before=before,budget_after=before,
                outcome="unresolved" if requests else "skipped",
                reason=reason))
        metrics = set(m for r in requests for m in r.metrics)
        operations = set(op for r in requests for op in r.operations)
        affected = {r.claim_id for r in refs}
        for ref in refs:
            c = memory.resolve(ref)
            if c.claim_type == "raw_primitive" and c.metric:
                metrics.add(c.metric)
            if c.claim_type == "derived_metric" and c.metric:
                operations.add(c.metric)
        # Follow actual pinned calculation inputs, then risk/argument edges.
        if "DocumentAgent" in components:
            known_metrics={memory.resolve(r).metric for r in refs if memory.resolve(r).claim_type=="raw_primitive"}
            missing_metrics=metrics-known_metrics
            for op in ("revenue_growth","operating_margin","net_margin","current_ratio"):
                if missing_metrics & {metric for _,metric in FinancialEngine.operation_inputs(op)}:
                    operations.add(op)
            for artifact in memory.get_calculations():
                if any(i.claim_ref.claim_id in affected for i in artifact.inputs):
                    operations.add(artifact.operation)
        if operations:
            components.add("FinancialAgent")
        for c in memory.get_claims():
            if c.agent == "FinancialAgent" and c.metric in operations:
                affected.add(c.claim_id)
        changed = True
        while changed:
            changed = False
            for c in memory.get_claims():
                if c.claim_id not in affected and any(r.claim_id in affected for r in memory.get_dependency_references(c.claim_id)):
                    affected.add(c.claim_id); components.add(c.agent); changed = True
        # New missing Market/Financial evidence can introduce risk findings even
        # when no prior risk dependency exists. Existing ones are filtered by
        # affected dependencies in the executor.
        if components & {"DocumentAgent","FinancialAgent","MarketAgent"}:
            components.add("RiskAgent")
        if components & {"DocumentAgent","FinancialAgent","MarketAgent","RiskAgent"} and not any(c.claim_type=="argument" for c in memory.get_claims()):
            components.update(("Bull","Bear"))
        order = ("DocumentAgent","FinancialAgent","MarketAgent","RiskAgent","Bull","Bear")
        nodes = []
        for c in order:
            if c in components:
                nodes.append(c)
                if c not in ("Bull","Bear"):
                    nodes.append("verify:"+c)
        nodes.extend(("health_gate","critic","report"))
        return memory._record_retry_decision(RetryDecision(decision_id="retry:"+str(uuid4()),requests=requests,
            affected_refs=tuple(memory.reference(c) for c in sorted(affected)),rerun_nodes=tuple(nodes),
            operations=tuple(sorted(operations)),metrics=tuple(sorted(metrics)),budget_before=before,budget_after=before-1,
            outcome="executed",reason="Coalesced correction allocated once to affected dependency closure"))

    def build_extended_plan(self, query: str, has_documents: bool) -> Phase1Plan:
        """Plan Batch 1 dependencies without allocating or consuming a retry.

        The extended entry point explicitly opts into dated Market and Risk work.
        Risk-only requests need the supported financial profile as an input.
        Phase 1 routing and its scope exclusions remain unchanged.
        """
        scoped = query
        if isinstance(query, str):
            scoped = re.sub(r"market analysis", "company overview", query, flags=re.I)
            scoped = re.sub(r"risk assessment", "financial health", scoped, flags=re.I)
        base = self.build_graph(scoped, has_documents)
        if base.status != "ready":
            return base.model_copy(update={"query": str(query)})
        tasks = (
            PlanTask(name="ingest"),
            PlanTask(name="document", depends_on=("ingest",)),
            PlanTask(name="verify_primitives", depends_on=("document",)),
            PlanTask(name="financial", depends_on=("verify_primitives",)),
            PlanTask(name="market", depends_on=("ingest",)),
            PlanTask(name="verify_findings", depends_on=("financial", "market")),
            PlanTask(name="risk", depends_on=("verify_findings",)),
            PlanTask(name="verify_risk", depends_on=("risk",)),
            PlanTask(name="health_gate", depends_on=("verify_risk",)),
            PlanTask(name="analysis_map", depends_on=("health_gate",)),
            PlanTask(name="report", depends_on=("analysis_map",)),
        )
        return base.model_copy(update={"query": query, "tasks": tasks})

    def build_graph(self, query: str, has_documents: bool) -> Phase1Plan:
        """Build the task/dependency graph for a query.

        Args:
            query: User query string.
            has_documents: Whether source documents were provided.

        Returns:
            Task graph with agent assignments and explicit dependencies
            (Financial waits on Document; Risk waits on Financial + Market).
        """
        if not isinstance(query, str) or not query.strip():
            return Phase1Plan(status="unsupported", query=str(query),
                issues=(AgentIssue(code="empty_question", message="A financial-analysis question is required"),))
        if not has_documents:
            return Phase1Plan(status="missing_document", query=query,
                issues=(AgentIssue(code="missing_document", message="Provide a born-digital annual report and its identity"),))
        text = query.casefold()
        if re.search(r"\bquarter\w*\b|\bq[1-4]\b|\bttm\b|trailing|calendar.year|monthly", text):
            return Phase1Plan(status="unsupported", query=query,
                issues=(AgentIssue(code="unsupported_period", message="This extraction profile supports reported fiscal annual periods, not quarterly, monthly, calendar-year, or trailing periods"),))
        operations = []
        for operation, pattern in (
            ("revenue_growth", r"growth|compar\w*.*revenue|revenue.*compar"),
            ("operating_margin", r"operating.*margin|profitability|profit margins?"),
            ("net_margin", r"net.*margin|profitability|profit margins?"),
            ("current_ratio", r"current ratio|liquidity|short.term"),
        ):
            if re.search(pattern, text):
                operations.append(operation)
        unsupported = bool(re.search(r"\bdcf\b|forecast|valuation|buy|sell|hold recommendation|bull|bear|critic|market analysis|risk assessment", text))
        general = bool(re.search(r"financial (?:health|analysis|performance)|annual results", text))
        if general or (not operations and not unsupported and re.search(r"analy[sz]|assess|review", text)):
            operations = ["revenue_growth", "operating_margin", "net_margin", "current_ratio"]
        metrics = list(dict.fromkeys(name for op in operations for _, name in FinancialEngine.operation_inputs(op)))
        if not operations:
            for name, pattern in (("revenue", r"revenue"), ("operating_income", r"operating income"),
                                  ("net_income", r"net income"), ("current_assets", r"current assets"),
                                  ("current_liabilities", r"current liabilities")):
                if re.search(pattern, text):
                    metrics.append(name)
        overview = bool(re.search(r"company overview|business overview|headquarter|incorporat", text))
        if not operations and not metrics and not overview:
            return Phase1Plan(status="unsupported", query=query,
                issues=(AgentIssue(code="unsupported_question", message="Supported scope is source facts, annual revenue growth, margins, and current ratio"),))
        years = [int(value) for value in re.findall(r"\b(?:fy\s*)?(20\d{2})\b", text)]
        tasks = (PlanTask(name="ingest"), PlanTask(name="document", depends_on=("ingest",)),
                 PlanTask(name="financial", depends_on=("document",)),
                 PlanTask(name="analysis_map", depends_on=("document", "financial")),
                 PlanTask(name="report", depends_on=("analysis_map",)))
        return Phase1Plan(status="ready", query=query, operations=tuple(operations), metrics=tuple(metrics),
            target_year=max(years) if years else None, tasks=tasks,
            issues=(AgentIssue(code="unsupported_scope_omitted", message="Out-of-scope analysis or recommendations were omitted"),) if unsupported else ())

    def compute_reanalysis_scope(
        self, contradiction_scope: dict[str, Any], retry_used: bool
    ) -> dict[str, Any]:
        """Compute the minimal subgraph to re-run for targeted re-analysis.

        Args:
            contradiction_scope: Implicated agent(s) flagged by Critic/Health Gate.
            retry_used: Whether the single shared retry budget is spent.

        Returns:
            Scoped re-run plan, or an unresolved marker if budget is spent.
        """
        requested = tuple(contradiction_scope.get("reanalysis_scope", ()))
        return {"reanalysis_scope": requested if not retry_used else (),
                "outcome": "unresolved" if retry_used else "scoped", "retry_budget_remaining": 0 if retry_used else 1}
