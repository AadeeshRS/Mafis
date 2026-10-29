"""Independent fresh source retrieval and exact deterministic replay."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
import re
from uuid import uuid4

from engine.financial_engine import FinancialEngine
from memory.shared_memory import Evidence, SharedMemory, VerificationCheck, VerificationRecord
from rag.models import RetrievalHit
from rag.retriever import RetrievalUnavailable
from rag.ingest import _DATE, _MONTHS


def _check(checks, code, passed, message, failure="contradicted"):
    checks.append(VerificationCheck(code=code, outcome="passed" if passed else failure, message=message))


def _annual_header_dates(text):
    """Parse all comparative header dates using the existing source profiles.

    Revenue extraction intentionally retains fewer columns than the source's
    complete annual header. Never infer header anchors from selected table cells.
    """
    from rag.ingest import comparative_dates
    return tuple(sorted(comparative_dates(text),reverse=True))


class VerificationAgent:
    def __init__(self, memory: SharedMemory, retriever, engine=None):
        self.memory, self.retriever = memory, retriever
        self.engine = engine if engine is not None else FinancialEngine(memory)

    def _dependencies(self, claim, checks, seen=None):
        seen = set() if seen is None else seen
        if claim.claim_id in seen:
            _check(checks, "dependency_cycle", False, "Dependency cycle")
            return
        seen = seen | {claim.claim_id}
        for ref in self.memory.get_dependency_references(claim.claim_id, claim.version):
            target = self.memory.resolve(ref)
            good = self.memory.reference(ref.claim_id) == ref and self.memory.is_current_verified(ref.claim_id)
            _check(checks, "dependency_current_verified", good,
                f"{ref.claim_id} v{ref.version} must be current and verified", "missing")
            if good:
                self._dependencies(target, checks, seen)
                if target.calculation_ref:
                    self._calculation(target, checks)

    def _calculation(self, claim, checks):
        artifact = self.memory.get_calculation(claim.calculation_ref)
        _check(checks, "calculation_freshness", self.memory.get_calculation_freshness(claim.calculation_ref) == "current",
            "Exact calculation input versions must be current", "missing")
        _check(checks, "calculation_verified_inputs",
            all(self.memory.is_current_verified(i.claim_ref.claim_id) and self.memory.reference(i.claim_ref.claim_id) == i.claim_ref for i in artifact.inputs),
            "Every exact source input must be independently verified", "missing")
        try:
            self.engine.validate_artifact(artifact)
            _check(checks, "calculation_replay", True, "Exact deterministic replay passed")
        except (ValueError, KeyError, ArithmeticError) as exc:
            _check(checks, "calculation_replay", False, str(exc))

    @staticmethod
    def _quote_location(evidence, chunk):
        if evidence.quote not in chunk.text:
            return False
        if evidence == chunk.evidence:
            return True
        expected = chunk.evidence.model_dump(round_trip=True)
        expected.update(quote=evidence.quote,
            locator=chunk.evidence.locator + f";quote-offset={chunk.text.index(evidence.quote)}")
        return evidence == Evidence.model_validate(expected)

    def _source(self, claim, evidence, checks, chunks_seen, fresh_evidence):
        source = self.memory.get_source(evidence.source_id)
        filters = {"doc_id": source.source_id}
        # The cited page scopes a fresh independent source read. All content,
        # source identity and exact locators must still pass their own checks.
        if evidence.page is not None:
            filters["page"] = evidence.page
        if claim.claim_type == "raw_primitive":
            filters["kind"] = "table"
        query = " ".join(str(v) for v in (claim.entity, claim.metric,
            claim.period.end_date if claim.period else None, "source evidence") if v is not None)
        try:
            hits = self.retriever.retrieve(query, filters, top_k=12)
            chunks = [RetrievalHit.model_validate(hit.model_dump(round_trip=True)).chunk for hit in hits]
        except (RetrievalUnavailable, RuntimeError, ValueError, TypeError) as exc:
            checks.append(VerificationCheck(code="fresh_retrieval", outcome="error",
                message=f"Fresh retrieval failed ({type(exc).__name__}); no substitute evidence"))
            return
        chunks_seen.extend(c.chunk_id for c in chunks)
        if not chunks:
            checks.append(VerificationCheck(code="fresh_retrieval", outcome="missing", message="Fresh retrieval found no evidence"))
            return
        matching = [c for c in chunks if c.source == source and c.evidence.source_id == source.source_id]
        if not matching:
            _check(checks, "source_identity", False, "Fresh source identity or source dates differ")
            return
        if claim.claim_type == "raw_primitive":
            cells = [cell for c in matching for cell in c.cells if cell.evidence == evidence and cell.evidence.quote in c.text]
            if not cells:
                _check(checks, "source_locator", False, "Citation differs from freshly retrieved source cell")
                return
            fields = ("value", "metric", "period", "currency", "scale", "unit", "accounting_scope")
            passing = [cell for cell in cells if all(getattr(claim, f) == getattr(cell, f) for f in fields) and claim.entity == source.entity]
            selected = passing[0] if passing else cells[0]
            for name in fields:
                _check(checks, "source_" + name, getattr(claim, name) == getattr(selected, name), f"Fresh source {name} must match")
            _check(checks, "source_entity", claim.entity == source.entity, "Fresh source entity must match")
            if passing:
                fresh_evidence.append(selected.evidence)
                self._contexts(source, claim, checks, chunks_seen, fresh_evidence)
            return
        located = [c for c in matching if self._quote_location(evidence, c)]
        if not located:
            _check(checks, "source_locator", False, "Quotation or exact source locator differs")
            return
        good = claim.claim == evidence.quote and claim.entity == source.entity
        if claim.claim_type == "risk":
            # Interpretation text is checked separately against the risk rubric.
            # Direct risk evidence still has to resolve to exact source content.
            good = claim.entity == source.entity
        if claim.agent == "MarketAgent":
            try:
                from rag.market_sources import validate_market_claim
                validate_market_claim(claim, source, self.memory)
                good = True
                if source.as_of_date is None and source.published_at is None and not source.annual_period_ends:
                    dates = [item.period.end_date for item in self.memory.get_claims()
                             if item.claim_type == "raw_primitive" and item.period is not None
                             and any(ev.source_id == source.source_id for ev in item.evidence)
                             and self.memory.is_current_verified(item.claim_id)]
                    _check(checks, "market_date_provenance", bool(dates) and max(dates) == claim.period.end_date,
                           "Fallback statement date must come from current independently verified source primitives", "missing")
            except (ValueError, ImportError, KeyError):
                good = False
        _check(checks, "source_fact", good, "Exact attributed source quotation, date and entity must match")
        if good:
            fresh_evidence.append(evidence)

    def _contexts(self, source, claim, checks, chunks_seen, fresh_evidence):
        """Independently retrieve document headers used by normalization/replay."""
        contexts = [("currency_context", source.currency_evidence)]
        if claim.period.kind == "duration" and claim.period.start_date is None:
            contexts.extend((("fiscal_calendar", source.fiscal_calendar_evidence),
                             ("annual_period_header", source.annual_period_evidence)))
        for code, evidence in contexts:
            if evidence is None:
                continue
            filters = {"doc_id": source.source_id}
            if evidence.page is not None:
                filters["page"] = evidence.page
            try:
                hits = self.retriever.retrieve(evidence.quote, filters, top_k=12)
                chunks = [RetrievalHit.model_validate(h.model_dump(round_trip=True)).chunk for h in hits]
                chunks_seen.extend(c.chunk_id for c in chunks)
                normalized = " ".join(evidence.quote.split())
                located = [c for c in chunks if c.source == source and c.evidence.page == evidence.page
                           and normalized in " ".join(c.text.split())]
                good = bool(located)
                if code == "currency_context":
                    good = good and source.currency == claim.currency == "USD" and bool(re.search(r"U\.S\. dollar", normalized, re.I))
                elif code == "fiscal_calendar":
                    match = re.search(r"Fiscal years (\d{4}), (\d{4}) and (\d{4}) were all (52|53)-\s*week years\.", normalized)
                    expected = tuple((int(match[n]), int(match[4])) for n in (1,2,3)) if match else ()
                    good = good and source.fiscal_year_weeks == expected and bool(expected)
                elif code == "annual_period_header":
                    # Parse the actual matched fresh text, including third and
                    # older columns which are deliberately absent from cells.
                    parsed = []
                    for chunk in located:
                        text = " ".join(chunk.text.split())
                        offset = text.index(normalized)
                        parsed.append(_annual_header_dates(text[offset:offset+len(normalized)]))
                    good = good and bool(parsed) and all(source.annual_period_ends == dates for dates in parsed)
                _check(checks, code, good, "Document normalization context must match fresh source text and structured dates")
                if good:
                    fresh_evidence.append(evidence)
            except (RetrievalUnavailable, RuntimeError, ValueError, TypeError) as exc:
                checks.append(VerificationCheck(code=code, outcome="error", message=f"Context retrieval failed ({type(exc).__name__})"))

    def verify_claim(self, claim_id: str) -> VerificationRecord:
        claim = self.memory.get_current(claim_id)
        shape_error = claim.verification_shape_error()
        if shape_error is not None:
            ref = self.memory.reference(claim_id)
            return self.memory.append_verification(VerificationRecord(
                verification_id="verification:" + str(uuid4()), checked_ref=ref,
                resulting_ref=ref.model_copy(update={"version": claim.version + 1}),
                outcome="unsupported", support_level="calculation_backed" if claim.calculation_ref else "unsupported",
                checks=(VerificationCheck(code="unsupported_claim_shape", outcome="missing", message=shape_error),)))
        records = self.memory.get_verification_records(claim_id)
        if claim.verification_status == "verified" and records and records[-1].resulting_ref == self.memory.reference(claim_id):
            checks = []
            self._dependencies(claim, checks)
            if claim.calculation_ref:
                self._calculation(claim, checks)
            if all(c.outcome == "passed" for c in checks):
                return records[-1]
        checks, evidence, chunks = [], [], []
        self._dependencies(claim, checks)
        if claim.claim_type == "argument":
            try:
                from agents.argument_contracts import validate_argument
                validate_argument(claim, self.memory)
                _check(checks, "argument_traceability", True,
                    "Exact factual premises and constrained interpretation passed; interpretation truth is not independently proven")
            except (ValueError, KeyError, TypeError) as exc:
                _check(checks, "argument_traceability", False, str(exc), "missing")
        if claim.calculation_ref:
            self._calculation(claim, checks)
        for item in claim.evidence:
            self._source(claim, item, checks, chunks, evidence)
        if claim.claim_type == "risk":
            try:
                from agents.risk_agent import validate_risk_claim
                if validate_risk_claim(claim, self.memory) is False:
                    raise ValueError("Risk traceability template rejected")
                if not self.memory.get_dependency_references(claim_id):
                    raise ValueError("Risk interpretation has no pinned dependencies")
                _check(checks, "risk_traceability", True,
                    "Pinned evidence supports a conditional interpretation; this does not prove a speculative causal outcome")
            except (ImportError, ValueError, KeyError) as exc:
                _check(checks, "risk_traceability", False, str(exc), "missing")
        elif claim.claim_type != "argument" and not claim.evidence and not claim.calculation_ref:
            _check(checks, "factual_evidence", False, "Factual claim lacks independently retrievable evidence or engine artifact", "missing")
        if not checks:
            _check(checks, "missing_evidence", False, "No verifiable evidence", "missing")
        outcome = "flagged" if any(c.outcome == "contradicted" for c in checks) else "unsupported" if any(c.outcome != "passed" for c in checks) else "verified"
        unique = tuple(dict.fromkeys(evidence))
        support = "calculation_backed" if claim.calculation_ref else (
            "multiple_sources" if len({e.source_id for e in unique}) > 1 else "single_source")
        if outcome != "verified" and not claim.calculation_ref:
            support = "unsupported"
        ref = self.memory.reference(claim_id)
        return self.memory.append_verification(VerificationRecord(verification_id="verification:" + str(uuid4()),
            checked_ref=ref, resulting_ref=ref.model_copy(update={"version": claim.version + 1}),
            outcome=outcome, support_level=support, checks=tuple(checks), fresh_evidence=unique,
            retrieved_chunk_ids=tuple(dict.fromkeys(chunks))))

    def verify_all(self, claim_ids: Iterable[str] | None = None) -> list[VerificationRecord]:
        ids = list(dict.fromkeys(claim_ids)) if claim_ids is not None else [c.claim_id for c in self.memory.get_claims()]
        return [self.verify_claim(claim_id) for claim_id in ids]
