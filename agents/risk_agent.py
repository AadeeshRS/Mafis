"""Constrained historical risk screens over exact Financial and Market versions.

No ratios, probabilities, price forecasts or causal assertions are generated.
Keyword categories are a disclosed evidence screen, not semantic risk discovery.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import json
from typing import Literal, get_args

from agents.contracts import AgentIssue
from agents.market_agent import check_source_cutoff, cutoff_date, validate_market_claim
from memory.shared_memory import Claim, ClaimVersionRef, EvidenceModel, FiscalPeriod, SharedMemory

RiskCategory = Literal["financial", "operational", "market", "regulatory", "macro", "governance", "competitive"]
RISK_CATEGORIES: tuple[RiskCategory, ...] = get_args(RiskCategory)
_KEYWORDS = {
    "operational": ("supply", "manufactur", "production", "disruption", "operations"),
    "market": ("demand", "market conditions", "market volatility", "consumer spending"),
    "regulatory": ("regulat", "export control", "restriction", "legislation"),
    "macro": ("inflation", "interest rate", "federal funds", "monetary", "economic outlook"),
    "governance": ("governance", "internal control", "board oversight", "misconduct"),
    "competitive": ("competit",),
}
UNCERTAINTY = "This is a risk-screening hypothesis; exposure, likelihood and causal effects are unproven."


class RiskResult(EvidenceModel):
    status: Literal["success", "partial", "failed"]
    claim_refs: tuple[ClaimVersionRef, ...] = ()
    calculation_refs: tuple[str, ...] = ()
    issues: tuple[AgentIssue, ...] = ()
    missing_categories: tuple[RiskCategory, ...] = ()
    selection_method: Literal["constrained_dependency_templates"] = "constrained_dependency_templates"


def _resolve_current(memory: SharedMemory, ref: ClaimVersionRef) -> Claim:
    claim = memory.resolve(ref)
    if memory.reference(ref.claim_id) != ref:
        raise ValueError("Risk dependency is a stale claim version")
    if claim.verification_status not in ("pending", "verified") or claim.support_level == "unsupported":
        raise ValueError("Risk dependency has rejected or unresolved support")
    if memory.get_dependency_freshness(claim.claim_id) != "current":
        raise ValueError("Risk dependency has superseded upstream versions")
    return claim


def _financial_dependency(memory: SharedMemory, claim: Claim) -> None:
    if claim.agent != "FinancialAgent" or claim.claim_type != "derived_metric" or not claim.calculation_ref:
        raise ValueError("Risk financial input must be an existing Financial derived metric")
    artifact = memory.get_calculation(claim.calculation_ref)
    if memory.get_calculation_freshness(claim.calculation_ref) != "current":
        raise ValueError("Risk calculation has superseded primitive inputs")
    if (claim.value != artifact.output_value or claim.metric != artifact.operation
            or claim.entity != artifact.entity or claim.accounting_scope != artifact.accounting_scope
            or claim.period != artifact.output_period or claim.unit != artifact.output_unit
            or claim.scale != 1 or claim.currency is not None):
        raise ValueError("Risk Financial input differs from pinned calculation")


def _market_dependency(memory: SharedMemory, claim: Claim) -> None:
    if len(claim.evidence) != 1:
        raise ValueError("Market dependency needs one exact source quotation")
    validate_market_claim(claim, memory.get_source(claim.evidence[0].source_id), memory)


def _category_matches(category: str, claim: Claim) -> bool:
    text = claim.evidence[0].quote.casefold()
    return any(word in text for word in _KEYWORDS.get(category, ()))


def _risk_identity(category: str, refs: tuple[ClaimVersionRef, ...], stable=False, memory=None) -> str:
    if stable and memory is not None:
        first=memory.resolve(refs[0])
        # One logical topic per entity/source context. Adding a newly recovered
        # financial metric revises this topic instead of orphaning the old risk.
        anchor=refs[0].claim_id if category=="financial" else refs[-1].claim_id
        identity=json.dumps([category,first.entity,first.accounting_scope,anchor],sort_keys=True)
    else:
        identity = json.dumps([category, [r.claim_id if stable else r.model_dump(mode="json") for r in refs]], sort_keys=True)
    return ("risk:logical:" if stable else "risk:") + sha256(identity.encode()).hexdigest()


def _canonical(memory: SharedMemory, category: str, refs: tuple[ClaimVersionRef, ...]) -> dict:
    if category not in RISK_CATEGORIES or not refs or len(set(refs)) != len(refs):
        raise ValueError("Risk requires a supported category and distinct pinned dependencies")
    claims = [_resolve_current(memory, ref) for ref in refs]
    financial, market = [], []
    for claim in claims:
        if claim.agent == "FinancialAgent":
            _financial_dependency(memory, claim)
            financial.append(claim)
        elif claim.agent == "MarketAgent":
            _market_dependency(memory, claim)
            market.append(claim)
        else:
            raise ValueError("Risk can consume only typed Financial and Market inputs")
    if len({(c.entity, c.accounting_scope) for c in financial}) > 1:
        raise ValueError("Risk cannot combine financial entities or accounting scopes")
    if category == "financial":
        if len(financial) != 1 or market:
            raise ValueError("Financial screen requires one pinned deterministic metric")
        body = f"Review the historical {financial[0].metric.replace('_', ' ')} calculation for financial exposure."
    else:
        if len(market) != 1 or not _category_matches(category, market[0]):
            raise ValueError("Risk category lacks a matching attributed source topic")
        if financial and category != "macro" and market[0].entity != financial[0].entity:
            raise ValueError("Company-specific risk context belongs to another entity")
        body = f"Review the historical source topic for {category} exposure."
        if financial:
            body += " Consider this context alongside the pinned financial calculations."
    dated = max(c.period.end_date for c in claims if c.period is not None)
    entity = financial[0].entity if financial else market[0].entity
    scope = financial[0].accounting_scope if financial else None
    return dict(entity=entity, accounting_scope=scope, metric=category,
                period=FiscalPeriod(kind="instant", end_date=dated, label=f"Historical risk screen as of {dated.isoformat()}"),
                claim=f"Historical risk screen as of {dated.isoformat()}: {body} {UNCERTAINTY}",
                calculation_ref=financial[0].calculation_ref if financial else None)


def validate_risk_claim(claim: Claim, memory: SharedMemory) -> None:
    """Rebuild the complete template/dependency contract; raise on any alteration.

Independent Verification must additionally verify every pinned dependency. Passing
this check establishes traceability only; the template explicitly disclaims proof.
"""
    expected = _canonical(memory, claim.metric, claim.candidate_claim_refs)
    logical_id=_risk_identity(claim.metric,claim.candidate_claim_refs,stable=True,memory=memory)
    if claim.claim_id==logical_id and claim.metric!="financial":
        # The full-flow screen binds all available checked financial context for
        # its entity. Stable identity must not allow a dropped dependency to pass.
        required={memory.reference(c.claim_id) for c in memory.get_claims() if c.agent=="FinancialAgent"
            and c.entity==claim.entity and c.accounting_scope==claim.accounting_scope and memory.is_current_verified(c.claim_id)}
        actual={r for r in claim.candidate_claim_refs if memory.resolve(r).agent=="FinancialAgent"}
        if required!=actual:
            raise ValueError("Logical risk screen omitted current checked financial context")
    if (claim.agent != "RiskAgent" or claim.claim_type != "risk" or claim.value is not None
            or claim.claim_id not in (_risk_identity(claim.metric, claim.candidate_claim_refs),
                                     _risk_identity(claim.metric, claim.candidate_claim_refs, stable=True),logical_id)
            or claim.evidence or claim.supports_claim_ids or claim.unit is not None or claim.currency is not None
            or claim.scale != 1 or any(getattr(claim, field) != value for field, value in expected.items())):
        raise ValueError("Risk claim differs from its constrained dependency template")


class RiskAgent:
    def __init__(self, memory: SharedMemory, retriever=None, llm=None, *, stable_ids=False, run_iteration=0):
        self.memory, self.retriever, self.llm = memory, retriever, llm
        self.stable_ids, self.run_iteration = stable_ids, run_iteration

    def assess_risk(self, financial_claim_ids: list[str | ClaimVersionRef],
                    market_claim_ids: list[str | ClaimVersionRef], *,
                    categories: tuple[RiskCategory, ...] | None = None,
                    as_of: date | datetime | None = None) -> RiskResult:
        issues, refs, financial, market = [], [], [], []
        requested = RISK_CATEGORIES if categories is None else categories
        try:
            cutoff = cutoff_date(as_of)
            if not requested or len(set(requested)) != len(requested) or any(c not in RISK_CATEGORIES for c in requested):
                raise ValueError("Risk categories must be nonempty, unique and supported")
        except (TypeError, ValueError) as exc:
            return RiskResult(status="failed", issues=(AgentIssue(code="invalid_risk_request", message=str(exc)),))
        seen = set()
        for inputs, expected, accepted in ((financial_claim_ids, "FinancialAgent", financial),
                                            (market_claim_ids, "MarketAgent", market)):
            for identifier in inputs:
                try:
                    reference = self.memory.reference(identifier) if isinstance(identifier, str) else identifier
                    if not isinstance(reference, ClaimVersionRef):
                        raise ValueError("Risk inputs must be claim IDs or exact ClaimVersionRef values")
                    if reference in seen:
                        raise ValueError("Duplicate risk dependency")
                    seen.add(reference)
                    claim = _resolve_current(self.memory, reference)
                    if claim.agent != expected:
                        raise ValueError("Risk input appears in the wrong dependency group")
                    if expected == "FinancialAgent":
                        _financial_dependency(self.memory, claim)
                    else:
                        _market_dependency(self.memory, claim)
                    if cutoff is not None and claim.period.end_date > cutoff:
                        raise ValueError("Risk dependency postdates requested temporal cutoff")
                    if cutoff is not None:
                        evidence_set = list(claim.evidence)
                        if claim.calculation_ref:
                            artifact = self.memory.get_calculation(claim.calculation_ref)
                            for item in artifact.inputs:
                                evidence_set.extend(self.memory.resolve(item.claim_ref).evidence)
                        for evidence in evidence_set:
                            check_source_cutoff(self.memory.get_source(evidence.source_id), as_of, self.memory)
                    accepted.append(reference)
                except (ValueError, KeyError, TypeError) as exc:
                    issues.append(AgentIssue(code="risk_dependency_rejected", message=str(exc)))
        covered = set()
        for category in requested:
            groups = [(ref,) for ref in financial] if category == "financial" else [
                tuple(financial) + (ref,) for ref in market
                if _category_matches(category, self.memory.resolve(ref))]
            for group in groups:
                try:
                    values = _canonical(self.memory, category, group)
                    identifier = _risk_identity(category, group, stable=self.stable_ids,memory=self.memory if self.stable_ids else None)
                    claim = Claim(claim_id=identifier, agent="RiskAgent", claim_type="risk", **values,
                        candidate_claim_refs=group, support_level="calculation_backed" if values["calculation_ref"] else "single_source",
                        verification_status="pending", run_iteration=self.run_iteration)
                    validate_risk_claim(claim, self.memory)
                    try:
                        old = self.memory.get_current(identifier)
                    except KeyError:
                        self.memory.append(claim)
                    else:
                        if self.stable_ids:
                            ignored = {"version","timestamp","verification_status","support_level","run_iteration"}
                            if old.model_dump(exclude=ignored) != claim.model_dump(exclude=ignored):
                                self.memory.append(claim.model_copy(update={"version":old.version+1}))
                        else:
                            validate_risk_claim(old, self.memory)
                    refs.append(self.memory.reference(identifier))
                    covered.add(category)
                except (ValueError, TypeError, KeyError) as exc:
                    issues.append(AgentIssue(code="risk_finding_rejected", message=str(exc)))
        missing = tuple(c for c in requested if c not in covered)
        if missing:
            issues.append(AgentIssue(code="missing_risk_categories",
                message="No supported screen for: " + ", ".join(missing)))
        calculations = tuple(dict.fromkeys(self.memory.resolve(r).calculation_ref for r in financial))
        return RiskResult(status="partial" if refs and issues else "success" if refs else "failed",
            claim_refs=tuple(refs), calculation_refs=calculations, issues=tuple(issues), missing_categories=missing)
