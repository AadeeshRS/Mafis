"""Planner Agent — builds the task/dependency graph, decides which agents run, computes re-analysis scope.

Single entry point for query routing. Owns the shared re-analysis budget
(max 1 total iteration across Health Gate and Critic triggers).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from agents.contracts import AgentIssue
from engine.financial_engine import FinancialEngine
from memory.shared_memory import CalculationOperation, EvidenceModel


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
        raise NotImplementedError
