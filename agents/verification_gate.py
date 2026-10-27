"""A strict, configurable health decision; never consumes Planner retries.

Denominator: every CURRENT non-argument claim in this run, including pending,
unsupported, flagged, unresolved and stale claims. Failure rate is the fraction
not currently eligible as verified. The boundary is strictly rate > threshold.
An empty evidence set or an explicit upstream issue blocks safely regardless of
the threshold. The default 0.5 is an engineering default, not calibration data.
"""
from __future__ import annotations

from collections import Counter
from typing import Literal

from memory.shared_memory import AgentName, ClaimVersionRef, EvidenceModel, SharedMemory


class GateResult(EvidenceModel):
    decision: Literal["passed", "blocked"]
    total: int
    verified_count: int
    unsupported_count: int
    flagged_count: int
    pending_count: int
    unresolved_count: int
    stale_count: int
    unsupported_rate: float
    threshold: float
    failing_claim_refs: tuple[ClaimVersionRef, ...] = ()
    failure_types: tuple[str, ...] = ()
    reanalysis_scope: tuple[AgentName, ...] = ()
    reason: str


class VerificationHealthGate:
    def __init__(self, memory: SharedMemory, unsupported_threshold: float = 0.5):
        if isinstance(unsupported_threshold, bool) or not isinstance(unsupported_threshold, (int, float)) or not 0 <= unsupported_threshold <= 1:
            raise ValueError("unsupported_threshold must be a finite number in [0, 1]")
        self.memory, self.threshold = memory, float(unsupported_threshold)

    def evaluate(self, *, issues=()) -> GateResult:
        claims = [c for c in self.memory.get_claims() if c.claim_type != "argument"]
        counts = Counter(c.verification_status for c in claims)
        failures, types, scope, stale_count = [], [], [], 0
        for claim in claims:
            stale = self.memory.get_dependency_freshness(claim.claim_id) != "current"
            if claim.calculation_ref:
                stale = stale or self.memory.get_calculation_freshness(claim.calculation_ref) != "current"
            # Eligibility follows all upstream pointers, not just direct versions.
            def dependencies_current(item, seen):
                if item.claim_id in seen:
                    return False
                seen = seen | {item.claim_id}
                for ref in self.memory.get_dependency_references(item.claim_id, item.version):
                    dep = self.memory.resolve(ref)
                    if self.memory.reference(dep.claim_id) != ref or dep.verification_status != "verified":
                        return False
                    if dep.calculation_ref and self.memory.get_calculation_freshness(dep.calculation_ref) != "current":
                        return False
                    if not dependencies_current(dep, seen):
                        return False
                return True
            stale = stale or not dependencies_current(claim, set())
            stale_count += int(stale)
            checked = self.memory.is_current_verified(claim.claim_id)
            if not checked or stale:
                failures.append(self.memory.reference(claim.claim_id))
                types.append("stale_dependency" if stale else "unverified_provenance" if claim.verification_status == "verified" else claim.verification_status)
                scope.append(claim.agent)
        for issue in issues:
            # Any explicit upstream incompleteness must remain visible. Root may
            # choose which task-level issues are relevant before invoking us.
            code = getattr(issue, "code", None) or (issue.get("code") if isinstance(issue, dict) else None)
            if code:
                types.append(str(code))
                agent = getattr(issue, "agent", None)
                if agent in ("DocumentAgent", "FinancialAgent", "MarketAgent", "RiskAgent"):
                    scope.append(agent)
                elif str(code).startswith(("financial_", "calculation_", "missing_calculations")):
                    scope.append("FinancialAgent")
                elif str(code).startswith(("risk_", "missing_risk_categories")):
                    scope.append("RiskAgent")
                elif str(code).startswith("market_"):
                    scope.append("MarketAgent")
                elif str(code).startswith(("ingest", "extraction", "missing_metric", "missing_primitive", "invalid_source", "claim_conflict", "wrong_document")):
                    scope.append("DocumentAgent")
                else:
                    scope.extend(("DocumentAgent", "MarketAgent"))
        total = len(claims)
        rate = len(failures) / total if total else 0.0
        blocked = not total or rate > self.threshold or bool(issues)
        if not total:
            types.append("empty_evidence")
            scope.extend(("DocumentAgent", "MarketAgent"))
        reason = ("No current factual claims; evidence collection required" if not total else
            "Upstream evidence collection or analysis reported incomplete results" if issues else
            "Current ineligible claim rate exceeds threshold" if blocked else
            "Current ineligible claim rate is at or below threshold")
        return GateResult(decision="blocked" if blocked else "passed", total=total,
            verified_count=total-len(failures), unsupported_count=counts["unsupported"],
            flagged_count=counts["flagged"], pending_count=counts["pending"], unresolved_count=counts["unresolved"],
            stale_count=stale_count, unsupported_rate=rate, threshold=self.threshold,
            failing_claim_refs=tuple(failures), failure_types=tuple(dict.fromkeys(types)),
            reanalysis_scope=tuple(dict.fromkeys(scope)) if blocked else (), reason=reason)
