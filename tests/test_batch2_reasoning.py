from decimal import Decimal
import pytest
from agents.argument_contracts import evidence_snapshot
from agents.bull_agent import BullAgent
from agents.bear_agent import BearAgent
from agents.critic_agent import CriticAgent, Assertion
from agents.planner import PlannerAgent
from agents.verification_agent import VerificationAgent
from agents.verification_gate import VerificationHealthGate
from memory.shared_memory import ReanalysisRequest
from tests.test_verification_agent import source_case
from tests.test_batch1_review_fixes import checked_store
from tests.batch2_fakes import Batch2MockLLM


def test_opposition_uses_same_checked_snapshot_and_preserves_gate_denominator(source_case):
    memory,tool=checked_store(source_case)
    snap=evidence_snapshot(memory); model=Batch2MockLLM()
    bull=BullAgent(memory,model).build_case(snapshot=snap)
    bear=BearAgent(memory,model).build_case(snapshot=snap)
    assert bull.status==bear.status=="success"
    assert bull.snapshot_hash==bear.snapshot_hash==snap.fingerprint
    VerificationAgent(memory,tool).verify_all([r.claim_id for r in bull.claim_refs+bear.claim_refs])
    assert all(memory.is_current_verified(r.claim_id) for r in bull.claim_refs+bear.claim_refs)
    assert VerificationHealthGate(memory).evaluate().total==3
    assert CriticAgent(memory).mechanical()==()


@pytest.mark.parametrize("field,value",[("value","999"),("value","-20"),("scale",1000),("unit","currency"),("currency","EUR"),("metric","fabricated_topic"),("source_ids",["fabricated"]),("quotations",["unsupported quotation"])])
def test_argument_numeric_fabrication_rejected(source_case,field,value):
    memory,_=checked_store(source_case)
    def corrupt(response,payload):
        response["arguments"][0]["premises"][0][field]=value
        return response
    result=BullAgent(memory,Batch2MockLLM(transform=corrupt)).build_case(snapshot=evidence_snapshot(memory))
    assert result.status=="failed" and not result.claim_refs


def test_unknown_and_stale_snapshot_rejected(source_case):
    memory,_=checked_store(source_case); snapshot=evidence_snapshot(memory)
    old=memory.get_current("revenue")
    memory.append(old.model_copy(update={"version":old.version+1}))
    assert BullAgent(memory,Batch2MockLLM()).build_case(snapshot=snapshot).status=="failed"
    assert BullAgent(memory,Batch2MockLLM()).build_case(["unknown"]).status=="failed"


def test_mechanical_scale_and_conflicts(source_case):
    memory,_=checked_store(source_case)
    p=memory.get_current("revenue")
    base=Assertion(reference=memory.reference("revenue"),entity=p.entity,metric=p.metric,period=p.period,
        value=Decimal("100"),unit="currency",currency="USD",scale=1000000,source_ids=(p.evidence[0].source_id,))
    equivalent=base.model_copy(update={"value":Decimal("100000000"),"scale":1})
    assert CriticAgent(memory).mechanical([base,equivalent])==()
    for change,category in (({"value":Decimal("101")},"numerical"),({"currency":"EUR"},"unit"),
                            ({"source_ids":("forged",)},"source"),({"predicate":"causes"},"causal"),
                            ({"predicate":"resilient","qualified":False},"risk_interpretation")):
        findings=CriticAgent(memory).mechanical([base,base.model_copy(update=change)])
        assert category in {f.category for f in findings}


def test_planner_one_global_budget_and_coalescing(source_case):
    memory,_=checked_store(source_case)
    req=ReanalysisRequest(trigger="critic",affected_refs=(memory.reference("margin"),),components=("FinancialAgent",),
        failure_types=("numerical",),correction=("Recheck artifact",))
    impossible=PlannerAgent().allocate_retry(memory,[req.model_copy(update={"components":()})])
    assert impossible.outcome=="unresolved" and memory.retry_budget_remaining==1
    first=PlannerAgent().allocate_retry(memory,[req,req])
    assert first.outcome=="executed" and first.budget_after==0
    second=PlannerAgent().allocate_retry(memory,[req.model_copy(update={"trigger":"evidence_gap"})])
    assert second.outcome=="unresolved" and memory.retry_budget_remaining==0


def test_temporal_and_logical_rules_have_negative_controls(source_case):
    memory,_=checked_store(source_case); c=memory.get_current("revenue")
    a=Assertion(reference=memory.reference("revenue"),entity=c.entity,metric=c.metric,period=c.period,
        value=c.value,unit=c.unit,currency=c.currency,scale=c.scale,source_ids=(c.evidence[0].source_id,))
    other=a.model_copy(update={"period":c.period.model_copy(update={"end_date":c.period.end_date.replace(year=2022),"start_date":None})})
    assert CriticAgent(memory).mechanical([a,other])==()
    assert "temporal" in {f.category for f in CriticAgent(memory).mechanical([a,other.model_copy(update={"equates_ref":a.reference})])}
    positive=a.model_copy(update={"predicate":"increase","proposition_key":"revenue_direction"})
    negative=a.model_copy(update={"predicate":"decrease","proposition_key":"revenue_direction"})
    assert "logical" in {f.category for f in CriticAgent(memory).mechanical([positive,negative])}


def test_explanation_failure_retains_mechanical_findings(source_case):
    from gemini import ModelUnavailable
    memory,_=checked_store(source_case); c=memory.get_current("revenue")
    a=Assertion(reference=memory.reference("revenue"),entity=c.entity,metric=c.metric,period=c.period,
        source_ids=(c.evidence[0].source_id,),predicate="causes")
    class FailedExplanation:
        def generate(self,*args,**kwargs):
            raise ModelUnavailable("Offline injected explanation failure")
    result=CriticAgent(memory,FailedExplanation()).check_contradictions(assertions=[a])
    assert result.findings and result.issues[0].code=="critic_explanation_failed"
    assert memory.get_contradictions()[0].status=="open"


def test_stale_argument_targets_author_not_sound_upstream_branch(source_case):
    memory,tool=checked_store(source_case)
    result=BullAgent(memory,Batch2MockLLM()).build_case(snapshot=evidence_snapshot(memory))
    VerificationAgent(memory,tool).verify_all([r.claim_id for r in result.claim_refs])
    margin=memory.get_current("margin")
    memory.append(margin.model_copy(update={"version":margin.version+1,"verification_status":"pending"}))
    VerificationAgent(memory,tool).verify_claim("margin")
    findings=CriticAgent(memory).mechanical()
    assert any(f.category=="missing_evidence" and f.components==("Bull",) for f in findings)


def test_cross_run_and_preset_verified_evidence_rejected(source_case):
    from memory.shared_memory import ClaimVersionRef
    memory,tool=checked_store(source_case)
    bad=ClaimVersionRef(run_id="another-run",claim_id="revenue",version=memory.reference("revenue").version)
    with pytest.raises(ValueError):
        evidence_snapshot(memory,[bad])
    old=memory.get_current("revenue")
    memory.append(old.model_copy(update={"version":old.version+1,"verification_status":"verified"}))
    with pytest.raises(ValueError):
        evidence_snapshot(memory,[memory.reference("revenue")])


def test_evidence_gap_is_routing_metadata_and_generation_failure_explicit(source_case):
    from gemini import ModelUnavailable
    memory,_=checked_store(source_case)
    def gap(response,payload):
        response["evidence_gaps"]=[{"trigger":"evidence_gap","components":["MarketAgent"],
            "failure_types":["dated_context_missing"],"correction":["Need official dated source"],"retryable":False}]
        return response
    result=BearAgent(memory,Batch2MockLLM(transform=gap)).build_case()
    assert result.evidence_gaps and all(c.metric!="dated_context_missing" for c in memory.get_claims())
    class Failed:
        mode="explicit offline failure"
        def generate(self,*args,**kwargs):
            raise ModelUnavailable("injected offline failure")
    failure=BullAgent(memory,Failed()).build_case()
    assert failure.status=="failed" and failure.execution_mode=="explicit offline failure" and failure.issues


def test_critic_rejects_invented_explanation_finding(source_case):
    from agents.critic_agent import CriticExplanation
    memory,_=checked_store(source_case); c=memory.get_current("revenue")
    a=Assertion(reference=memory.reference("revenue"),entity=c.entity,metric=c.metric,predicate="causes")
    class Invented:
        def generate(self,schema,**kwargs):
            return CriticExplanation.model_validate({"explanations":[{"finding_id":"invented","significance":"source_consistency"}]})
    result=CriticAgent(memory,Invented()).check_contradictions(assertions=[a])
    assert result.findings and result.issues[0].code=="critic_explanation_failed"
    assert all(f.finding_id!="invented" for f in memory.get_contradictions())


def test_argument_revision_stales_authoritative_gate_and_full_map(source_case):
    from agents.report_agent import ReportAgent
    memory,tool=checked_store(source_case)
    bull=BullAgent(memory,Batch2MockLLM()).build_case()
    VerificationAgent(memory,tool).verify_all([r.claim_id for r in bull.claim_refs])
    gate=VerificationHealthGate(memory).evaluate()
    reporter=ReportAgent(memory,tool,full=True)
    analysis=reporter.build_analysis_map(health_gate=gate)
    bear=BearAgent(memory,Batch2MockLLM()).build_case()
    VerificationAgent(memory,tool).verify_all([r.claim_id for r in bear.claim_refs])
    with pytest.raises(ValueError):
        reporter.generate_report(analysis)
    fresh=VerificationHealthGate(memory).evaluate()
    assert fresh.total==gate.total==3 and fresh.claim_refs!=gate.claim_refs


def test_known_source_revision_uses_actual_artifact_edges_not_metric_wide_guesses(source_case):
    memory,_=checked_store(source_case)
    request=ReanalysisRequest(trigger="critic",affected_refs=(memory.reference("revenue"),),components=("DocumentAgent",),
        failure_types=("source",),correction=("Recheck the implicated exact row",))
    decision=PlannerAgent().allocate_retry(memory,[request])
    # This store contains only one net-margin artifact, not growth/operating.
    assert decision.operations==("net_margin",)


def test_irrecoverable_gap_is_authoritative_partial_report_even_with_passed_gate(source_case):
    from agents.report_agent import ReportAgent
    memory,tool=checked_store(source_case)
    gap=ReanalysisRequest(trigger="evidence_gap",affected_refs=(memory.reference("revenue"),),components=("MarketAgent",),
        failure_types=("dated_context_missing",),correction=("Need an official dated macro statement",),retryable=False)
    decision=PlannerAgent().allocate_retry(memory,[gap])
    assert decision.outcome=="unresolved" and memory.retry_budget_remaining==1
    gate=VerificationHealthGate(memory).evaluate()
    reporter=ReportAgent(memory,tool,full=True)
    analysis=reporter.build_analysis_map(health_gate=gate)
    assert gate.decision=="passed"
    assert reporter.generate_report(analysis).status=="partial"
    required=next(i for i in analysis.issues if i.code=="unresolved_reanalysis")
    with pytest.raises(ValueError):
        reporter.generate_report(analysis.model_copy(update={"issues":tuple(i for i in analysis.issues if i!=required)}))
    with pytest.raises(ValueError):
        reporter.generate_report(analysis.model_copy(update={"issues":analysis.issues+(required,)}))
