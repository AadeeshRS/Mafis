"""Mechanical comparison before bounded model explanation; no retry ownership."""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from itertools import combinations
from fractions import Fraction
from typing import Literal

from agents.argument_contracts import premise_for
from agents.contracts import AgentIssue
from gemini import ModelUnavailable, ModelOutputError
from memory.shared_memory import ClaimVersionRef, ContradictionRecord, EvidenceModel, FiscalPeriod


class Assertion(EvidenceModel):
    """Explicit comparison view; hostile variants are evaluation-only injections."""
    reference: ClaimVersionRef
    entity: str | None
    metric: str | None
    accounting_scope: str | None = None
    period: FiscalPeriod | None = None
    value: Decimal | None = None
    currency: str | None = None
    unit: str | None = None
    scale: int = 1
    source_ids: tuple[str, ...] = ()
    predicate: str = "observed"
    proposition_key: str | None = None
    equates_ref: ClaimVersionRef | None = None
    causal_support: bool = False
    qualified: bool = True


class FindingExplanation(EvidenceModel):
    finding_id: str
    significance: Literal["source_consistency", "dimension_consistency", "interpretation_uncertainty"]


class CriticExplanation(EvidenceModel):
    explanations: tuple[FindingExplanation, ...] = ()


class CriticResult(EvidenceModel):
    findings: tuple[ContradictionRecord, ...] = ()
    issues: tuple[AgentIssue, ...] = ()
    check_scope: str = "Exact identities, scale-normalized numbers, dimensions, citations, and explicit predicates only; no unrestricted language contradiction detection"


class CriticAgent:
    def __init__(self, memory, llm=None):
        self.memory, self.llm = memory, llm

    def assertions(self):
        result = []
        for claim in self.memory.get_claims():
            if claim.claim_type == "argument":
                if not self.memory.is_current_verified(claim.claim_id):
                    result.append(Assertion(reference=self.memory.reference(claim.claim_id),entity=claim.entity,
                        metric=claim.metric,period=claim.period))
                    continue
                # Arguments have already constrained factual premises. Opposing
                # perspectives alone do not become contradictory factual values.
                for p in claim.argument.premises if claim.argument else ():
                    result.append(Assertion(reference=p.claim_ref, entity=p.entity, metric=p.metric,
                        accounting_scope=p.accounting_scope, period=p.period,
                        value=p.value if isinstance(p.value, Decimal) else None,
                        currency=p.currency, unit=p.unit, scale=p.scale, source_ids=p.source_ids,
                        predicate=claim.argument.interpretation, qualified=True))
            elif self.memory.is_current_verified(claim.claim_id):
                p = premise_for(self.memory, self.memory.reference(claim.claim_id))
                result.append(Assertion(reference=p.claim_ref, entity=p.entity, metric=p.metric,
                    accounting_scope=p.accounting_scope, period=p.period,
                    value=p.value if isinstance(p.value, Decimal) else None,
                    currency=p.currency, unit=p.unit, scale=p.scale, source_ids=p.source_ids))
        return result

    def mechanical(self, assertions=None):
        """Public direct mechanics permit labelled hostile assertion fixtures.

        Production callers omit assertions: views come from Shared Memory only.
        This method never admits an injected assertion as a production claim.
        """
        views = self.assertions() if assertions is None else [Assertion.model_validate(a.model_dump(round_trip=True)) for a in assertions]
        found = {}
        def emit(category, rule, items, description, missing=()):
            refs = tuple(dict.fromkeys(a.reference for a in items))
            claims = [self.memory.resolve(r) for r in refs]
            components = tuple(dict.fromkeys(c.agent for c in claims))
            identity = category + "|" + rule + "|" + "|".join(sorted(r.claim_id for r in refs))
            finding = ContradictionRecord(finding_id="finding:" + sha256(identity.encode()).hexdigest(),
                category=category, rule=rule, description=description, claim_refs=refs, original_refs=refs,
                components=components, root_cause=rule, missing_evidence=missing, recommended_scope=components)
            found[finding.finding_id] = finding
        for a in views:
            if self.memory.reference(a.reference.claim_id) != a.reference or not self.memory.is_current_verified(a.reference.claim_id):
                emit("missing_evidence", "current_checked_dependency", [a], "Assertion depends on stale or unchecked evidence", ("Current independent verification required",))
            else:
                source = premise_for(self.memory, a.reference)
                if a.source_ids != source.source_ids:
                    emit("source", "exact_source_identity", [a], "Asserted citation identity differs from its supporting source")
            if a.predicate == "causes" and not a.causal_support:
                emit("causal", "unsupported_causal_predicate", [a], "Unqualified causal predicate lacks causal evidence", ("A descriptive association does not establish causation",))
            if a.predicate in ("resilient", "vulnerable") and not a.qualified:
                emit("risk_interpretation", "unqualified_risk_predicate", [a], "Risk interpretation is stated as established exposure without qualifications")
        for a, b in combinations(views, 2):
            same = (a.entity, a.metric, a.accounting_scope) == (b.entity, b.metric, b.accounting_scope)
            if not same:
                continue
            period_key = lambda p: (p.kind,p.start_date,p.end_date) if p else None
            if period_key(a.period) != period_key(b.period):
                if a.equates_ref == b.reference or b.equates_ref == a.reference:
                    emit("temporal", "equated_distinct_periods", [a,b], "Assertion explicitly equates distinct fiscal periods")
                continue
            if a.value is not None and b.value is not None:
                if (a.currency, a.unit) != (b.currency, b.unit):
                    emit("unit", "incompatible_dimensions", [a,b], "Comparable assertions use incompatible currency/unit dimensions")
                elif Fraction(a.value) * a.scale != Fraction(b.value) * b.scale:
                    emit("numerical", "normalized_same_fact", [a,b], "Comparable fact values disagree after scale normalization")
            opposite = {a.predicate, b.predicate} in ({"increase","decrease"}, {"present","absent"})
            if opposite and a.proposition_key and a.proposition_key == b.proposition_key:
                emit("logical", "opposed_same_predicate", [a,b], "Explicit opposite predicates apply to the same proposition and period")
        return tuple(found.values())

    def check_contradictions(self, bull_case=None, bear_case=None, *, run_iteration=0, assertions=None, exhausted=False):
        new = self.mechanical(assertions)
        previous = {f.finding_id: f for f in self.memory.get_contradictions()}
        issues, current = [], []
        explanations = {}
        if new and self.llm is not None:
            try:
                proposed = self.llm.generate(CriticExplanation,
                    system="Explain only supplied mechanical findings by selecting bounded significance labels. Do not add, erase or resolve findings, facts, numbers or references.",
                    payload={"task":"critic_explanation", "findings":[f.model_dump(mode="json") for f in new]})
                proposed = CriticExplanation.model_validate(proposed.model_dump(round_trip=True))
                if len({e.finding_id for e in proposed.explanations}) != len(proposed.explanations) or any(e.finding_id not in {f.finding_id for f in new} for e in proposed.explanations):
                    raise ValueError("Critic explanation invented or duplicated a finding reference")
                explanations = {e.finding_id:e.significance for e in proposed.explanations}
            except (ModelUnavailable, ModelOutputError, ValueError, KeyError, TypeError) as exc:
                issues.append(AgentIssue(code="critic_explanation_failed", message=str(exc)))
        for item in new:
            old = previous.get(item.finding_id)
            revision = item.model_copy(update={"version": old.version+1 if old else 1,
                "original_refs": old.original_refs if old else item.original_refs,
                "status": "unresolved" if exhausted else "open", "run_iteration": run_iteration,
                "explanation": explanations.get(item.finding_id)})
            if old and old.model_dump(exclude={"timestamp","version","run_iteration"}) == revision.model_dump(exclude={"timestamp","version","run_iteration"}):
                current.append(old)
            else:
                current.append(self.memory.append_contradiction(revision))
        # A vanished rule is only resolved after checking the CURRENT implicated
        # factual chain. Missing/unchecked replacements cannot erase a conflict.
        for identifier, old in previous.items():
            if identifier in {f.finding_id for f in new} or old.status == "resolved":
                continue
            replacements = tuple(self.memory.reference(r.claim_id) for r in old.claim_refs)
            sound = (replacements != old.claim_refs and
                     all(self.memory.is_current_verified(r.claim_id) for r in replacements))
            status = "resolved" if sound else "unresolved" if exhausted else "open"
            if old.claim_refs==replacements and old.status==status and old.run_iteration==run_iteration:
                current.append(old)
                continue
            revision = old.model_copy(update={"version":old.version+1,"claim_refs":replacements,
                "status":status,"run_iteration":run_iteration,"timestamp":datetime.now(timezone.utc)})
            current.append(self.memory.append_contradiction(revision))
        return CriticResult(findings=tuple(current), issues=tuple(issues))

    def decide_reanalysis(self, contradictions, retry_used=False):
        raise ValueError("Planner alone allocates the run's single analytical retry")
