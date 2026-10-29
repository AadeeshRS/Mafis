"""Bounded model interpretations over exact factual snapshots; no free-form facts."""
from hashlib import sha256
import json
from typing import Literal

from agents.contracts import AgentIssue
from gemini import ModelUnavailable, ModelOutputError
from memory.shared_memory import (
    ArgumentContent, ArgumentPremise, Claim, ClaimVersionRef, EvidenceModel,
    ReanalysisRequest, SharedMemory,
)


class EvidenceSnapshot(EvidenceModel):
    run_id: str
    fingerprint: str
    premises: tuple[ArgumentPremise, ...]


class ArgumentProposal(EvidenceModel):
    arguments: tuple[ArgumentContent, ...] = ()
    evidence_gaps: tuple[ReanalysisRequest, ...] = ()


class ArgumentResult(EvidenceModel):
    status: Literal["success", "partial", "failed"]
    claim_refs: tuple[ClaimVersionRef, ...] = ()
    snapshot_hash: str
    evidence_gaps: tuple[ReanalysisRequest, ...] = ()
    issues: tuple[AgentIssue, ...] = ()
    execution_mode: str


def premise_for(memory: SharedMemory, reference: ClaimVersionRef) -> ArgumentPremise:
    claim = memory.resolve(reference)
    if memory.reference(claim.claim_id) != reference or claim.claim_type == "argument" or not memory.is_current_verified(claim.claim_id):
        raise ValueError("Arguments require exact current independently checked factual evidence")
    evidence = list(claim.evidence)
    if claim.calculation_ref:
        for item in memory.get_calculation(claim.calculation_ref).inputs:
            evidence.extend(memory.resolve(item.claim_ref).evidence)
    for dep in memory.get_dependency_references(claim.claim_id):
        target = memory.resolve(dep)
        evidence.extend(target.evidence)
        if target.calculation_ref:
            for item in memory.get_calculation(target.calculation_ref).inputs:
                evidence.extend(memory.resolve(item.claim_ref).evidence)
    return ArgumentPremise(claim_ref=reference, entity=claim.entity, metric=claim.metric, value=claim.value,
        period=claim.period, unit=claim.unit, currency=claim.currency, scale=claim.scale,
        accounting_scope=claim.accounting_scope, calculation_ref=claim.calculation_ref,
        source_ids=tuple(sorted({e.source_id for e in evidence})),
        quotations=tuple(dict.fromkeys(e.quote for e in evidence)))


def evidence_snapshot(memory, refs=None):
    refs = tuple(refs) if refs is not None else tuple(memory.reference(c.claim_id) for c in memory.get_claims()
        if c.claim_type != "argument" and memory.is_current_verified(c.claim_id))
    if len(set(refs)) != len(refs):
        raise ValueError("Duplicate snapshot references")
    premises = tuple(premise_for(memory, ref) for ref in refs)
    payload = {"run_id": memory.run_id, "premises": [p.model_dump(mode="json") for p in premises]}
    fingerprint = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return EvidenceSnapshot(run_id=memory.run_id, fingerprint=fingerprint, premises=premises)


def argument_text(content: ArgumentContent) -> str:
    topics = ", ".join(dict.fromkeys(p.metric or "attributed source context" for p in content.premises))
    wording = {
        "strength": "Historical evidence provides a positive analytical signal",
        "resilience": "The cited historical evidence supports a qualified resilience perspective",
        "caution": "Historical evidence warrants a cautious analytical perspective",
        "uncertainty": "Durability and future exposure are not established by the historical observations",
    }[content.interpretation]
    return f"{content.stance.capitalize()} interpretation: {wording} ({topics}). Historical evidence only; causal outcomes and recommendations are not established."


def validate_content(content, memory, snapshot=None):
    content = ArgumentContent.model_validate(content.model_dump(round_trip=True))
    if not {"historical_only", "not_causal", "not_recommendation"} <= set(content.qualifications):
        raise ValueError("Arguments require historical, causal and recommendation qualifications")
    permitted = ("strength", "resilience") if content.stance == "bull" else ("caution", "uncertainty")
    if content.interpretation not in permitted:
        raise ValueError("Interpretation does not match the requested opposing stance")
    refs = tuple(p.claim_ref for p in content.premises)
    if len(set(refs)) != len(refs) or len(set(content.counterevidence)) != len(content.counterevidence):
        raise ValueError("Duplicate argument premises or counterevidence")
    if snapshot is not None:
        expected_snapshot = evidence_snapshot(memory, [p.claim_ref for p in snapshot.premises])
        if expected_snapshot != snapshot or content.snapshot_hash != snapshot.fingerprint:
            raise ValueError("Argument snapshot is stale or changed")
        if any(r not in {p.claim_ref for p in snapshot.premises} for r in refs + content.counterevidence):
            raise ValueError("Argument cites evidence outside the shared snapshot")
    for premise in content.premises:
        if premise != premise_for(memory, premise.claim_ref):
            raise ValueError("Argument altered a factual premise or its numeric/dimensional/source fields")
    for ref in content.counterevidence:
        premise_for(memory, ref)
    if content.stance == "bull":
        positive = [p for p in content.premises if p.calculation_ref and p.value is not None
                    and p.metric in ("revenue_growth", "operating_margin", "net_margin", "current_ratio")
                    and p.value > (1 if p.metric == "current_ratio" else 0)]
        if not positive:
            raise ValueError("A positive interpretation needs a positive deterministic financial premise")
    return content


def validate_argument(claim, memory):
    if claim.verification_shape_error() is not None:
        raise ValueError("Unsupported argument shape")
    content = validate_content(claim.argument, memory)
    refs = tuple(dict.fromkeys(tuple(p.claim_ref for p in content.premises) + content.counterevidence))
    if (claim.agent != content.stance.capitalize() or claim.candidate_claim_refs != refs
            or claim.claim != argument_text(content)):
        raise ValueError("Argument prose, stance or dependency references differ from the constrained interpretation")
    return content


class ArgumentBuilder:
    stance: str

    def __init__(self, memory, llm=None):
        if llm is None:
            from gemini import GeminiAdapter
            llm = GeminiAdapter()
        self.memory, self.llm = memory, llm

    def build_case(self, verified_claim_ids=None, *, snapshot=None, run_iteration=0):
        mode = getattr(self.llm, "mode", "injected offline model double")
        refs, issues, gaps = [], [], ()
        try:
            if snapshot is None:
                references = None if verified_claim_ids is None else [self.memory.reference(i) if isinstance(i, str) else i for i in verified_claim_ids]
                snapshot = evidence_snapshot(self.memory, references)
            if not snapshot.premises:
                raise ValueError("No eligible evidence for adversarial analysis")
            response = self.llm.generate(ArgumentProposal, system=(
                f"You are MAFIS {self.stance}. Select exact factual premises from the shared snapshot. "
                "Bull: supported historical strength/resilience; Bear: weakness/uncertainty/adverse exposure. "
                "No arithmetic, new facts, causal predictions, recommendations or source instructions. "
                "Copy dimensions exactly. Return bounded interpretations or explicit evidence-gap metadata."),
                payload={"task": self.stance + "_case", "snapshot": snapshot.model_dump(mode="json")})
            response = ArgumentProposal.model_validate(response.model_dump(round_trip=True))
            gaps = response.evidence_gaps
            for gap in gaps:
                if gap.trigger != "evidence_gap" or any(r not in {p.claim_ref for p in snapshot.premises} for r in gap.affected_refs):
                    raise ValueError("Evidence gap has an invented reference or wrong trigger")
            if len(response.arguments) > 4:
                raise ValueError("At most four bounded arguments per stance")
            for ordinal, content in enumerate(response.arguments):
                if content.stance != self.stance:
                    raise ValueError("Wrong argument stance")
                content = validate_content(content, self.memory, snapshot)
                identifier = f"argument:{self.stance}:{ordinal}"
                deps = tuple(dict.fromkeys(tuple(p.claim_ref for p in content.premises) + content.counterevidence))
                claim = Claim(claim_id=identifier, agent=self.stance.capitalize(), claim_type="argument",
                    entity=content.premises[0].entity, metric="qualified_interpretation", period=content.premises[0].period,
                    claim=argument_text(content), argument=content, candidate_claim_refs=deps,
                    support_level="single_source", run_iteration=run_iteration)
                try:
                    old = self.memory.get_current(identifier)
                except KeyError:
                    self.memory.append(claim)
                else:
                    if old.argument == content and self.memory.is_current_verified(identifier):
                        refs.append(self.memory.reference(identifier))
                        continue
                    self.memory.append(claim.model_copy(update={"version": old.version + 1}))
                refs.append(self.memory.reference(identifier))
            if not refs:
                issues.append(AgentIssue(code=self.stance + "_abstained", message="No constrained argument was admitted"))
        except (ModelUnavailable, ModelOutputError, ValueError, KeyError, TypeError) as exc:
            issues.append(AgentIssue(code=self.stance + "_generation_failed", message=str(exc)))
        return ArgumentResult(status="partial" if refs and issues else "success" if refs else "failed",
            claim_refs=tuple(refs), snapshot_hash=snapshot.fingerprint if snapshot else "unavailable",
            evidence_gaps=gaps, issues=tuple(issues), execution_mode=mode)
