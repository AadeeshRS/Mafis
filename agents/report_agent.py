"""Validated Analysis Map followed by a deterministic, source-backed report."""

from __future__ import annotations

from html import escape
from typing import Literal

from agents.contracts import AgentIssue
from agents.verification_gate import GateResult
from engine.financial_engine import FinancialEngine
from memory.shared_memory import (
    ClaimVersionRef, Evidence, EvidenceModel, SharedMemory, SupportLevel, VerificationStatus,
)
from rag.retriever import RetrievalUnavailable


SectionTitle = Literal["Executive Summary", "Company Overview", "Financial Health", "Sources",
                       "Support and Uncertainty", "Limitations", "Market Context", "Risk Assessment"]
_TITLES = ("Executive Summary", "Company Overview", "Financial Health", "Sources", "Support and Uncertainty", "Limitations")
_EXTENDED_TITLES = _TITLES[:3] + ("Market Context", "Risk Assessment") + _TITLES[3:]


class AnalysisEntry(EvidenceModel):
    claim_ref: ClaimVersionRef
    evidence: tuple[Evidence, ...]
    calculation_ref: str | None
    input_refs: tuple[ClaimVersionRef, ...] = ()
    dependency_refs: tuple[ClaimVersionRef, ...] = ()
    support_level: SupportLevel
    verification_status: VerificationStatus
    assumptions: tuple[str, ...] = ()


class AnalysisSection(EvidenceModel):
    title: SectionTitle
    entries: tuple[AnalysisEntry, ...] = ()


class AnalysisMap(EvidenceModel):
    run_id: str
    execution_mode: str = "not recorded"
    sections: tuple[AnalysisSection, ...]
    issues: tuple[AgentIssue, ...] = ()
    extended: bool = False
    health_gate: GateResult | None = None
    excluded_claim_refs: tuple[ClaimVersionRef, ...] = ()
    limitations: tuple[str, ...] = (
        "Independent verification has not been performed; source facts and calculated results remain pending.",
        "Analysis is limited to the supplied document and the supported financial extraction profile.",
        "The model interpretation is constrained; no investment recommendation is provided.",
    )


class FinancialReport(EvidenceModel):
    status: Literal["success", "partial"]
    analysis_map: AnalysisMap
    markdown: str


def _safe(text):
    return escape(str(text), quote=False).replace("[", "\\[").replace("]", "\\]").replace("|", "\\|")


class ReportAgent:
    def __init__(self, memory: SharedMemory, retriever, *, extended: bool = False):
        self.memory, self.retriever = memory, retriever
        self.extended = extended

    def _source_claim(self, claim):
        if not claim.evidence or not all(self.retriever.validate_evidence(e) for e in claim.evidence):
            raise ValueError("Source evidence does not resolve to indexed document content")
        if claim.claim_type == "qualitative":
            if self.extended and claim.agent == "MarketAgent":
                from rag.market_sources import validate_market_claim
                for evidence in claim.evidence:
                    validate_market_claim(claim, self.memory.get_source(evidence.source_id), self.memory)
                return
            if claim.agent != "DocumentAgent" or not any(claim.claim == e.quote for e in claim.evidence):
                raise ValueError("Source statement is not an exact Document Agent quotation")
            return
        matches = [cell for e in claim.evidence for chunk in self.retriever.page_chunks(e.source_id, e.page)
                   for cell in chunk.cells if cell.evidence in claim.evidence]
        if not any((claim.metric, claim.value, claim.unit, claim.currency, claim.scale, claim.period, claim.accounting_scope)
                == (cell.metric, cell.value, cell.unit, cell.currency, cell.scale, cell.period, cell.accounting_scope)
                and claim.entity == self.memory.get_source(cell.evidence.source_id).entity for cell in matches):
            raise ValueError("Raw numeric fields differ from the cited source cell")

    def _entry(self, claim) -> AnalysisEntry:
        if claim.verification_status not in ("pending", "verified") or claim.support_level == "unsupported":
            raise ValueError("Claim has unresolved or insufficient support")
        if self.extended:
            reference = self.memory.reference(claim.claim_id)
            records = self.memory.get_verification_records(claim.claim_id)
            if claim.verification_status != "verified" or not any(
                    r.resulting_ref == reference and r.outcome == "verified" for r in records):
                raise ValueError("Extended reports require an exact independent verification record")
            if self.memory.get_dependency_freshness(claim.claim_id) != "current":
                raise ValueError("Claim dependencies are superseded")
        evidence, input_refs, assumptions, dependency_refs = [], (), [], ()
        if claim.claim_type in ("raw_primitive", "qualitative"):
            self._source_claim(claim)
            evidence.extend(claim.evidence)
        elif claim.claim_type == "derived_metric":
            artifact = self.memory.get_calculation(claim.calculation_ref)
            if self.memory.get_calculation_freshness(artifact.calculation_ref) != "current":
                raise ValueError("Calculation uses superseded inputs")
            if not FinancialEngine(self.memory).validate_outputs(artifact):
                raise ValueError("Calculation failed deterministic replay")
            if (claim.value, claim.unit, claim.period, claim.metric, claim.entity, claim.accounting_scope,
                    claim.scale, claim.currency, claim.support_level) != (
                    artifact.output_value, artifact.output_unit, artifact.output_period, artifact.operation,
                    artifact.entity, artifact.accounting_scope, 1, None, "calculation_backed"):
                raise ValueError("Derived claim does not match the engine artifact")
            input_refs = tuple(i.claim_ref for i in artifact.inputs)
            for reference in input_refs:
                raw = self.memory.resolve(reference)
                if raw.verification_status not in ("pending", "verified"):
                    raise ValueError("Calculation input has unresolved evidence")
                self._source_claim(raw)
                evidence.extend(raw.evidence)
            assumptions.extend(f.message for f in artifact.findings)
            if any(i.source_period.start_date is None and i.period.start_date is not None for i in artifact.inputs):
                assumptions.append("Annual boundaries were normalized using cited fiscal-calendar policy or consecutive annual statement headers.")
                for e in tuple(evidence):
                    doc = self.memory.get_source(e.source_id)
                    calendar = doc.fiscal_calendar_evidence or doc.annual_period_evidence
                    if calendar is not None:
                        evidence.append(calendar)
        elif self.extended and claim.claim_type == "risk" and claim.agent == "RiskAgent":
            from agents.risk_agent import validate_risk_claim
            validate_risk_claim(claim, self.memory)
            dependency_refs = claim.candidate_claim_refs
            for reference in dependency_refs:
                dependency = self.memory.resolve(reference)
                if dependency.verification_status != "verified":
                    raise ValueError("Risk dependency is not verified")
                entry = self._entry(dependency)
                evidence.extend(entry.evidence)
            evidence.extend(claim.evidence)
            assumptions.append("Risk verification establishes evidence traceability; it does not prove a future causal outcome.")
        else:
            raise ValueError("Claim type belongs outside the Phase 1 report")
        for e in tuple(evidence):
            currency = self.memory.get_source(e.source_id).currency_evidence
            if currency is not None:
                evidence.append(currency)
        unique = tuple(dict.fromkeys(evidence))
        if not all(self.retriever.validate_evidence(e) for e in unique):
            raise ValueError("Source metadata context does not resolve")
        return AnalysisEntry(claim_ref=self.memory.reference(claim.claim_id), evidence=unique,
            calculation_ref=claim.calculation_ref, input_refs=input_refs, dependency_refs=dependency_refs, support_level=claim.support_level,
            verification_status=claim.verification_status, assumptions=tuple(dict.fromkeys(assumptions)))

    def build_analysis_map(self, issues: tuple[AgentIssue, ...] = (), *, execution_mode="not recorded", health_gate=None) -> AnalysisMap:
        entries, rejected, excluded = [], list(issues), []
        for claim in self.memory.get_claims():
            try:
                entries.append(self._entry(claim))
            except (ValueError, KeyError, RetrievalUnavailable) as exc:
                rejected.append(AgentIssue(code="report_claim_excluded", message=f"{claim.metric or claim.claim_type}: {exc}"))
                excluded.append(self.memory.reference(claim.claim_id))
        financial = tuple(e for e in entries if self.memory.resolve(e.claim_ref).claim_type in ("raw_primitive", "derived_metric"))
        company = tuple(e for e in entries if self.memory.resolve(e.claim_ref).claim_type == "qualitative"
                        and self.memory.resolve(e.claim_ref).agent == "DocumentAgent")
        summary = tuple(e for e in financial if e.calculation_ref)
        all_entries = tuple(entries)
        section_entries = (summary, company, financial, all_entries, all_entries, ())
        titles, options = _TITLES, {}
        if self.extended:
            market = tuple(e for e in entries if self.memory.resolve(e.claim_ref).agent == "MarketAgent")
            risks = tuple(e for e in entries if self.memory.resolve(e.claim_ref).claim_type == "risk")
            titles = _EXTENDED_TITLES
            section_entries = (summary, company, financial, market, risks, all_entries, all_entries, ())
            options["limitations"] = (
                "Independent verification checks indexed source evidence and deterministic replay; it does not establish external truth or source independence.",
                "Market context uses constrained quotations with historical/as-of dates, not live prices or current news inference.",
                "Risk findings use constrained templates and express possibilities; traceability does not prove causal outcomes or exhaustive risk coverage.",
                "The Health Gate threshold is configurable and remains uncalibrated on held-out validation data.",
                "Batch 1 does not execute Bull/Bear, Critic, or targeted re-analysis; a blocked gate produces a partial report.",
            )
        return AnalysisMap(run_id=self.memory.run_id, execution_mode=execution_mode, issues=tuple(rejected),
            extended=self.extended, health_gate=health_gate,
            excluded_claim_refs=tuple(excluded), sections=tuple(
            AnalysisSection(title=title, entries=items) for title, items in zip(titles, section_entries)), **options)

    def validate_analysis_map(self, analysis_map: AnalysisMap) -> None:
        titles = _EXTENDED_TITLES if self.extended else _TITLES
        if (analysis_map.run_id != self.memory.run_id or analysis_map.extended != self.extended
                or tuple(s.title for s in analysis_map.sections) != titles):
            raise ValueError("Analysis Map run or sections are invalid")
        source_entries = next(s.entries for s in analysis_map.sections if s.title == "Sources")
        source_refs = {e.claim_ref for e in source_entries}
        for section in analysis_map.sections:
            if len({e.claim_ref for e in section.entries}) != len(section.entries):
                raise ValueError("Duplicate section claim references")
            for entry in section.entries:
                if entry.claim_ref not in source_refs:
                    raise ValueError("Section claim has no Sources entry")
                claim = self.memory.resolve(entry.claim_ref)
                if self.memory.reference(claim.claim_id) != entry.claim_ref or self._entry(claim) != entry:
                    raise ValueError("Analysis Map has stale or altered claim provenance")
                if section.title == "Company Overview" and (claim.claim_type != "qualitative" or claim.agent != "DocumentAgent"):
                    raise ValueError("Company overview contains an unexpected claim type")
                if section.title == "Executive Summary" and claim.claim_type != "derived_metric":
                    raise ValueError("Summary contains an uncalculated analytical result")
                if section.title == "Market Context" and claim.agent != "MarketAgent":
                    raise ValueError("Market context contains an unexpected claim")
                if section.title == "Risk Assessment" and claim.claim_type != "risk":
                    raise ValueError("Risk assessment contains an unexpected claim")
                if section.title == "Financial Health" and claim.claim_type not in ("raw_primitive", "derived_metric"):
                    raise ValueError("Financial health contains an unexpected claim type")
        for reference in analysis_map.excluded_claim_refs:
            if self.memory.reference(reference.claim_id) != reference:
                raise ValueError("Excluded claim reference is stale")

    def _render(self, analysis_map: AnalysisMap) -> str:
        by_title = {s.title: s.entries for s in analysis_map.sections}
        sources = tuple(dict.fromkeys(e for entry in by_title["Sources"] for e in entry.evidence))
        source_ids = {e: f"S{index}" for index, e in enumerate(sources, 1)}
        calculations = tuple(dict.fromkeys(e.calculation_ref for e in by_title["Sources"] if e.calculation_ref))
        calc_ids = {ref: f"C{index}" for index, ref in enumerate(calculations, 1)}

        def citations(entry):
            return " ".join(f"[{source_ids[e]}]" for e in entry.evidence)

        lines = ["# Financial Analysis", "", "## Executive Summary", "",
            ("This analysis includes only independently checked claims. Risk checks establish traceability, not proven outcomes."
             if self.extended else "This analysis uses source-linked facts and deterministic calculations. Independent verification is pending."),
            "Execution: " + _safe(analysis_map.execution_mode) + ".", ""]
        for entry in by_title["Executive Summary"]:
            artifact = self.memory.get_calculation(entry.calculation_ref)
            suffix = "%" if artifact.output_unit == "percent" else ""
            lines.append(f"- {_safe(artifact.operation.replace('_', ' ').capitalize())}: {artifact.display_value}{suffix} "
                         f"[{calc_ids[entry.calculation_ref]}]. {citations(entry)}")
        if not by_title["Executive Summary"]:
            lines.append("No supported derived financial results are available.")
        lines.extend(["", "## Company Overview", ""])
        company = by_title["Company Overview"]
        if not company:
            lines.append("No source-grounded company overview was extracted.")
        for entry in company:
            claim = self.memory.resolve(entry.claim_ref)
            lines.extend(["> " + _safe(line) for line in claim.claim.splitlines()])
            lines.append(citations(entry))
        lines.extend(["", "## Financial Health", "", "Reported source values:", "",
                      "| Metric | Period end | Source value | Currency and scale | Evidence |",
                      "|---|---|---:|---|---|"])
        for entry in by_title["Financial Health"]:
            claim = self.memory.resolve(entry.claim_ref)
            if claim.claim_type == "raw_primitive":
                scale = claim.evidence[0].scale_header or f"scale {claim.scale}"
                lines.append(f"| {_safe(claim.metric)} | {claim.period.end_date} | {claim.value} | "
                             f"{claim.currency} {_safe(scale)} | {citations(entry)} |")
        lines.extend(["", "Engine results:", "", "| Metric | Period end | Result | Calculation | Evidence |",
                      "|---|---|---:|---|---|"])
        interpretations = []
        for entry in by_title["Financial Health"]:
            if not entry.calculation_ref:
                continue
            artifact = self.memory.get_calculation(entry.calculation_ref)
            suffix = "%" if artifact.output_unit == "percent" else ""
            lines.append(f"| {_safe(artifact.operation)} | {artifact.output_period.end_date} | {artifact.display_value}{suffix} "
                         f"| [{calc_ids[artifact.calculation_ref]}] | {citations(entry)} |")
            from agents.financial_agent import FinancialAgent
            interpretations.append(FinancialAgent.interpretation_text(artifact) + " " + citations(entry))
        lines.extend([""] + interpretations)
        if self.extended:
            for title in ("Market Context", "Risk Assessment"):
                lines.extend(["", "## " + title, ""])
                if not by_title[title]:
                    lines.append("No independently supported findings are available for this section.")
                for entry in by_title[title]:
                    claim = self.memory.resolve(entry.claim_ref)
                    lines.append("- " + _safe(claim.claim) + " " + citations(entry))
                    if entry.dependency_refs:
                        lines.append("  Dependencies: " + "; ".join(
                            f"{_safe(r.claim_id)} v{r.version}" for r in entry.dependency_refs) + ".")
        lines.extend(["", "## Sources", ""])
        for evidence, label in source_ids.items():
            url = str(evidence.source_url).split("#")[0]
            if evidence.page is None:
                source = self.memory.get_source(evidence.source_id)
                lines.append(f"- [{label}] [{_safe(evidence.source)}]({url}), text snapshot; "
                             f"published {_safe(source.published_at or 'unknown')}; as of {_safe(source.as_of_date or 'unknown')}; "
                             f"{_safe(evidence.locator)}.")
            else:
                url += f"#page={evidence.page}"
                lines.append(f"- [{label}] [{_safe(evidence.source)}]({url}), PDF page {evidence.page}, "
                             f"printed page {_safe(evidence.printed_page or 'unknown')}; {_safe(evidence.locator)}.")
        for reference, label in calc_ids.items():
            artifact = self.memory.get_calculation(reference)
            inputs = "; ".join(f"{i.role}: {_safe(i.claim_ref.claim_id)} v{i.claim_ref.version}" for i in artifact.inputs)
            lines.append(f"- [{label}] `{reference}`; formula version {artifact.formula_version}; {inputs}.")
        lines.extend(["", "## Support and Uncertainty", "",
                      "Source facts are single_source; derived results are calculation_backed. Neither label establishes independent verification.", ""])
        for entry in by_title["Support and Uncertainty"]:
            claim = self.memory.resolve(entry.claim_ref)
            lines.append(f"- {_safe(claim.metric or 'source_statement')}: {entry.support_level}; {entry.verification_status}.")
        if analysis_map.health_gate is not None:
            gate = analysis_map.health_gate
            lines.append(f"- Health Gate: {_safe(gate.decision)}; {gate.verified_count}/{gate.total} current claims verified; "
                         f"unsupported rate {gate.unsupported_rate}; threshold {gate.threshold}.")
        for reference in analysis_map.excluded_claim_refs:
            claim = self.memory.resolve(reference)
            lines.append(f"- Excluded claim {_safe(reference.claim_id)} v{reference.version}: "
                         f"{claim.verification_status}; {claim.support_level}. See limitations for failed checks.")
        assumptions = tuple(dict.fromkeys(a for entry in by_title["Sources"] for a in entry.assumptions))
        lines.extend("- " + _safe(a) for a in assumptions)
        lines.extend(["", "## Limitations", ""])
        lines.extend("- " + _safe(text) for text in analysis_map.limitations)
        lines.extend(f"- {_safe(issue.code)}: {_safe(issue.message)}" for issue in analysis_map.issues)
        return "\n".join(lines) + "\n"

    def generate_report(self, analysis_map: AnalysisMap | None = None) -> FinancialReport:
        analysis_map = analysis_map or self.build_analysis_map()
        self.validate_analysis_map(analysis_map)
        has_financial = any(s.title == "Financial Health" and s.entries for s in analysis_map.sections)
        blocked = analysis_map.health_gate is not None and analysis_map.health_gate.decision != "passed"
        report = FinancialReport(status="partial" if analysis_map.issues or not has_financial or blocked else "success",
            analysis_map=analysis_map, markdown=self._render(analysis_map))
        self.validate_report(report)
        return report

    def validate_report(self, report: FinancialReport) -> None:
        self.validate_analysis_map(report.analysis_map)
        has_financial = any(s.title == "Financial Health" and s.entries for s in report.analysis_map.sections)
        blocked = report.analysis_map.health_gate is not None and report.analysis_map.health_gate.decision != "passed"
        expected_status = "partial" if report.analysis_map.issues or not has_financial or blocked else "success"
        if report.status != expected_status:
            raise ValueError("Report status does not match its limitations")
        if report.markdown != self._render(report.analysis_map):
            raise ValueError("Report text differs from the validated source/engine-backed rendering")
