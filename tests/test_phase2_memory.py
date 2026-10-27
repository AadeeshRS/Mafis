"""Candidate pointers, check history, run isolation and health boundaries."""
from datetime import datetime, timezone

import pytest

from agents.contracts import AgentIssue
from agents.verification_agent import VerificationAgent
from agents.verification_gate import VerificationHealthGate
from memory.shared_memory import Claim, ClaimVersionRef, SharedMemory, SourceDocument, VerificationRecord
from tests.test_verification_agent import source_case


def risk(memory, refs, **changes):
    fields = dict(claim_id="risk", agent="RiskAgent", claim_type="risk", entity="Acme", claim="Conditional risk",
        candidate_claim_refs=tuple(refs), support_level="single_source")
    fields.update(changes)
    return Claim(**fields)


def test_pending_candidate_is_not_a_verified_support(source_case):
    memory,_,claims = source_case
    memory.append(claims[0])
    ref=memory.reference("revenue")
    pending=memory.append(risk(memory,[ref]))
    assert pending.verification_status == "pending"
    assert memory.get_dependency_references("risk") == (ref,)
    assert memory.get_dependency_freshness("risk") == "current"
    with pytest.raises(ValueError,match="not currently verified"):
        memory.append(risk(memory,[],claim_id="legacy",supports_claim_ids=("revenue",)))


@pytest.mark.parametrize("kind", ["missing","self","duplicate","stale","cross_run"])
def test_candidate_rejects_bad_refs_atomically(source_case,kind):
    memory,_,claims=source_case
    memory.append(claims[0])
    ref=memory.reference("revenue")
    if kind=="stale":
        memory.append(claims[0].model_copy(update={"version":2}))
    refs={"missing":[ref.model_copy(update={"claim_id":"unknown"})],
          "self":[ref.model_copy(update={"claim_id":"risk"})],
          "duplicate":[ref,ref], "stale":[ref],
          "cross_run":[ref.model_copy(update={"run_id":"another-run"})]}[kind]
    with pytest.raises(ValueError):
        memory.append(risk(memory,refs))
    assert len(memory.get_claims())==1


def test_stale_candidate_status_revision_preserves_original_pointer(source_case,monkeypatch):
    memory,retriever,claims=source_case
    memory.append(claims[0])
    pointer=memory.reference("revenue")
    memory.append(risk(memory,[pointer]))
    agent=VerificationAgent(memory,retriever)
    agent.verify_claim("revenue")
    assert memory.get_dependency_freshness("risk")=="superseded"
    import agents.risk_agent
    monkeypatch.setattr(agents.risk_agent,"validate_risk_claim",lambda *args:None,raising=False)
    record=agent.verify_claim("risk")
    assert record.outcome=="unsupported"
    assert memory.get_current("risk").candidate_claim_refs==(pointer,)
    assert memory.get_history("risk")[0].verification_status=="pending"
    assert memory.get_history("risk")[1].agent=="RiskAgent"


def test_current_verified_dependency_checks_traceability_not_causality(source_case,monkeypatch):
    memory,retriever,claims=source_case
    memory.append(claims[0])
    agent=VerificationAgent(memory,retriever)
    agent.verify_claim("revenue")
    memory.append(risk(memory,[memory.reference("revenue")]))
    import agents.risk_agent
    monkeypatch.setattr(agents.risk_agent,"validate_risk_claim",lambda *args:None,raising=False)
    record=agent.verify_claim("risk")
    assert record.outcome=="verified"
    assert any(c.code=="risk_traceability" and "does not prove" in c.message for c in record.checks)


def test_exact_record_cannot_be_reused_or_cross_run(source_case):
    memory,retriever,claims=source_case
    memory.append(claims[0])
    record=VerificationAgent(memory,retriever).verify_claim("revenue")
    with pytest.raises(ValueError):
        memory.append_verification(record)
    other=SharedMemory("other")
    with pytest.raises(ValueError,match="another run"):
        other.append_verification(record)
    assert memory.get_verification_records()==[record] and other.get_verification_records()==[]
    assert len(memory.get_history("revenue"))==2


@pytest.mark.parametrize("threshold,decision",[(0.49,"blocked"),(0.5,"passed"),(0.51,"passed")])
def test_gate_strict_boundary_and_pending_denominator(source_case,threshold,decision):
    memory,retriever,claims=source_case
    for claim in claims:
        memory.append(claim)
    VerificationAgent(memory,retriever).verify_claim("revenue")
    result=VerificationHealthGate(memory,threshold).evaluate()
    assert result.decision==decision and result.total==2 and result.verified_count==1
    assert result.pending_count==1 and result.unsupported_rate==0.5
    assert result.failing_claim_refs==(memory.reference("net_income"),)
    assert bool(result.reanalysis_scope)==(decision=="blocked")


def test_gate_empty_and_upstream_degraded_are_safe(source_case):
    empty=VerificationHealthGate(SharedMemory(),1).evaluate()
    assert empty.decision=="blocked" and empty.total==0 and "empty_evidence" in empty.failure_types
    memory,retriever,claims=source_case
    memory.append(claims[0])
    VerificationAgent(memory,retriever).verify_all()
    result=VerificationHealthGate(memory,1).evaluate(issues=(AgentIssue(code="missing_metrics",message="Extraction incomplete"),))
    assert result.decision=="blocked" and result.verified_count==1 and result.unsupported_rate==0
    assert "missing_metrics" in result.failure_types and result.reanalysis_scope


@pytest.mark.parametrize("threshold",[-0.1,1.1,True,float("nan"),float("inf"),"0.5"])
def test_gate_invalid_threshold(threshold):
    with pytest.raises(ValueError):
        VerificationHealthGate(SharedMemory(),threshold)


@pytest.mark.parametrize("code,agent",[("financial_plan_unavailable","FinancialAgent"),
    ("missing_calculations","FinancialAgent"),("risk_dependency_rejected","RiskAgent"),
    ("missing_risk_categories","RiskAgent"),("market_retrieval_unavailable","MarketAgent"),
    ("missing_metrics","DocumentAgent"),("ingestion_failed","DocumentAgent")])
def test_gate_routes_explicit_failure_to_implicated_agent(source_case,code,agent):
    memory,retriever,claims=source_case
    memory.append(claims[0])
    VerificationAgent(memory,retriever).verify_all()
    result=VerificationHealthGate(memory).evaluate(issues=(AgentIssue(code=code,message="Missing required analysis"),))
    assert result.decision=="blocked" and result.reanalysis_scope==(agent,)


def test_gate_stale_verified_claims_are_ineligible(source_case,monkeypatch):
    memory,retriever,claims=source_case
    memory.append(claims[0])
    agent=VerificationAgent(memory,retriever)
    agent.verify_all()
    memory.append(risk(memory,[memory.reference("revenue")]))
    import agents.risk_agent
    monkeypatch.setattr(agents.risk_agent,"validate_risk_claim",lambda *args:None,raising=False)
    agent.verify_claim("risk")
    prior=memory.get_current("revenue")
    memory.append(prior.model_copy(update={"version":prior.version+1}))
    result=VerificationHealthGate(memory,0).evaluate()
    assert result.decision=="blocked" and result.stale_count==1 and result.verified_count==0
    assert memory.get_current("risk").verification_status=="verified"
    assert memory.get_verification_health()["stale_count"]==1


def test_preset_verified_status_is_not_independent_verification(source_case):
    memory,retriever,claims=source_case
    memory.append(claims[0].model_copy(update={"verification_status":"verified"}))
    assert not memory.is_current_verified("revenue")
    result=VerificationHealthGate(memory,0).evaluate()
    assert result.decision=="blocked" and result.verified_count==0
    assert "unverified_provenance" in result.failure_types
    VerificationAgent(memory,retriever).verify_claim("revenue")
    assert memory.is_current_verified("revenue")


def test_source_dates_require_aware_ordered_timestamps():
    fields=dict(title="Snapshot",entity="Acme",source_url="https://example.test/data",sha256="f"*64,source_type="news")
    with pytest.raises(ValueError,match="timezone aware"):
        SourceDocument(**fields,published_at=datetime(2024,1,1))
    with pytest.raises(ValueError,match="publication"):
        SourceDocument(**fields,published_at=datetime(2024,2,1,tzinfo=timezone.utc),retrieved_at=datetime(2024,1,1,tzinfo=timezone.utc))
