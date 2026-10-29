import pytest
from graph import run_full_pipeline, save_outputs
from tests.test_batch1_integration import extended_inputs
from tests.batch2_fakes import Batch2MockLLM


def execute(inputs,model,**kwargs):
    doc,index,snapshot=inputs
    return run_full_pipeline("Assess FY2024 financial health, bull and bear cases with critic",doc,
        retriever=index,document_llm=model,financial_llm=model,bull_llm=model,bear_llm=model,critic_llm=model,
        market_filters={"doc_id":snapshot.source.source_id,"kind":"narrative"},risk_categories=("financial","macro"),**kwargs)


def test_full_clean(extended_inputs,tmp_path):
    model=Batch2MockLLM()
    state=execute(extended_inputs,model)
    assert state["report"].status=="success",state["analysis_map"].issues
    assert state["memory"].retry_budget_remaining==1
    assert state["bull_result"].snapshot_hash==state["bear_result"].snapshot_hash
    assert state["memory"].get_contradictions()==[]
    assert "## Bull Case" in state["report"].markdown
    save_outputs(state,tmp_path)


def test_full_document_gap_corrected_once(extended_inputs):
    calls=[0]
    def omit_once(response,payload):
        if payload["task"]=="document_extraction":
            calls[0]+=1
            if calls[0]==1:
                response["primitives"]=[p for p in response["primitives"] if p["metric"]!="net_income"]
        return response
    state=execute(extended_inputs,Batch2MockLLM(transform=omit_once))
    assert state["report"].status=="success",state["analysis_map"].issues
    assert state["memory"].retry_budget_remaining==0 and calls[0]==2
    assert len(state["memory"].get_calculations())==4
    assert len([c for c in state["memory"].get_claims() if c.agent=="RiskAgent" and c.metric=="macro"])==1
    assert state["retry_execution"]["nodes"][0]=="DocumentAgent"
    for artifact in state["memory"].get_calculations():
        assert state["memory"].get_calculation_freshness(artifact.calculation_ref)=="current"


def test_full_persistent_failure_terminates(extended_inputs):
    def omit(response,payload):
        if payload["task"]=="document_extraction":
            response["primitives"]=[p for p in response["primitives"] if p["metric"]!="net_income"]
        return response
    state=execute(extended_inputs,Batch2MockLLM(transform=omit))
    assert state["report"].status=="partial"
    assert state["memory"].retry_budget_remaining==0
    assert state["memory"].get_retry_decisions()[-1].outcome=="unresolved"
    assert "bull_result" not in state


def test_argument_only_correction_preserves_all_upstream_versions(extended_inputs):
    seen=[0]
    def corrupt_once(response,payload):
        if payload["task"]=="bull_case":
            seen[0]+=1
            if seen[0]==1:
                response["arguments"][0]["premises"][0]["value"]="9999"
        return response
    model=Batch2MockLLM(transform=corrupt_once)
    state=execute(extended_inputs,model)
    assert state["report"].status=="success",state["analysis_map"].issues
    assert state["memory"].retry_budget_remaining==0 and seen[0]==2
    nodes=state["retry_execution"]["nodes"]
    assert "Bull" in nodes and not any(c in nodes for c in ("DocumentAgent","FinancialAgent","MarketAgent","RiskAgent","Bear"))
    before={r.claim_id:r for r in state["retry_execution"]["before_refs"]}
    for c in state["memory"].get_claims():
        if c.agent!="Bull":
            assert state["memory"].reference(c.claim_id)==before[c.claim_id]


def test_critic_triggered_argument_correction_resolves_with_trail(extended_inputs,monkeypatch):
    from agents.critic_agent import CriticAgent
    original=CriticAgent.check_contradictions
    injected=[False]
    def stale_once(self,*args,**kwargs):
        if not injected[0]:
            injected[0]=True
            claim=next(c for c in self.memory.get_claims() if c.agent=="Bull")
            self.memory.append(claim.model_copy(update={"version":claim.version+1,"verification_status":"flagged"}))
        return original(self,*args,**kwargs)
    monkeypatch.setattr(CriticAgent,"check_contradictions",stale_once)
    state=execute(extended_inputs,Batch2MockLLM())
    memory=state["memory"]
    assert memory.retry_budget_remaining==0
    assert state["report"].status=="success",state["analysis_map"].issues
    assert {r.trigger for r in memory.get_retry_decisions()[0].requests}=={"critic"}
    assert all(f.status=="resolved" for f in memory.get_contradictions())
    assert {f.status for f in memory.get_contradictions(history=True)}=={"open","resolved"}
    assert not any(n in state["retry_execution"]["nodes"] for n in ("DocumentAgent","FinancialAgent","MarketAgent","RiskAgent","Bear"))


def test_source_revision_rebuilds_only_affected_artifacts_and_keeps_history(extended_inputs,monkeypatch,tmp_path):
    from agents.critic_agent import CriticAgent
    original=CriticAgent.check_contradictions
    injected=[False]
    preserved={}
    def revise_once(self,*args,**kwargs):
        if not injected[0]:
            injected[0]=True
            ratio=next(c for c in self.memory.get_claims() if c.claim_type=="derived_metric" and c.metric=="current_ratio")
            preserved["ratio_ref"]=self.memory.reference(ratio.claim_id)
            preserved["artifact"]=ratio.calculation_ref
            revenue=next(c for c in self.memory.get_claims() if c.claim_type=="raw_primitive" and c.metric=="revenue")
            self.memory.append(revenue.model_copy(update={"version":revenue.version+1,"verification_status":"pending"}))
        return original(self,*args,**kwargs)
    monkeypatch.setattr(CriticAgent,"check_contradictions",revise_once)
    state=execute(extended_inputs,Batch2MockLLM())
    memory=state["memory"]
    save_outputs(state,tmp_path)
    assert state["report"].status=="success",state["analysis_map"].issues
    assert memory.retry_budget_remaining==0
    assert len(memory.get_calculations())==7
    assert memory.reference(preserved["ratio_ref"].claim_id)==preserved["ratio_ref"]
    assert memory.get_calculation_freshness(preserved["artifact"])=="current"
    current=[c for c in memory.get_claims() if c.claim_type=="derived_metric"]
    assert len(current)==4
    assert all(memory.get_calculation_freshness(c.calculation_ref)=="current" for c in current)
    assert all(memory.is_current_verified(c.claim_id) for c in current)
    assert {r.trigger for r in memory.get_retry_decisions()[0].requests}=={"critic"}


@pytest.mark.parametrize("persistent",[False,True])
def test_malformed_numeric_uses_only_planner_retry(extended_inputs,persistent):
    seen=[]
    def malformed(response,payload):
        if payload["task"]=="bull_case":
            seen.append(1)
            if persistent or len(seen)==1:
                response["arguments"][0]["premises"][0]["value"]="not-a-number"
        return response
    state=execute(extended_inputs,Batch2MockLLM(transform=malformed))
    assert len(seen)==2
    assert state["memory"].retry_budget_remaining==0
    assert state["report"].status==("partial" if persistent else "success")
    assert set(state["retry_execution"]["nodes"])=={"Bull","health_gate","critic","report"}
    assert all(c.value is None for c in state["memory"].get_claims() if c.agent=="Bull")
    if persistent:
        assert not [c for c in state["memory"].get_claims() if c.agent=="Bull"]
        assert state["memory"].get_retry_decisions()[-1].outcome=="unresolved"
