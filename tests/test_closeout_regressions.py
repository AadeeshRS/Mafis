"""Review reproductions; all model/SDK responses in this module are offline."""
from decimal import Decimal
import pytest

from agents.argument_contracts import evidence_snapshot
from agents.bull_agent import BullAgent
from agents.bear_agent import BearAgent
from agents.contracts import AgentIssue
from agents.report_agent import ReportAgent
from agents.verification_agent import VerificationAgent
from agents.verification_gate import VerificationHealthGate
from evaluation.batch2 import execution_identity
from tests.batch2_fakes import Batch2MockLLM
from tests.test_verification_agent import source_case
from tests.test_batch1_review_fixes import checked_store


@pytest.fixture
def argument_map(source_case):
    memory,tool=checked_store(source_case)
    snap=evidence_snapshot(memory)
    for cls in (BullAgent,BearAgent):
        result=cls(memory,Batch2MockLLM()).build_case(snapshot=snap)
        VerificationAgent(memory,tool).verify_all([r.claim_id for r in result.claim_refs])
    agent=ReportAgent(memory,tool,full=True)
    return agent,agent.build_analysis_map(health_gate=VerificationHealthGate(memory).evaluate())


def changed_sections(analysis,updates):
    return analysis.model_copy(update={"sections":tuple(s.model_copy(update={"entries":updates.get(s.title,s.entries)}) for s in analysis.sections)})


@pytest.mark.parametrize("change",["swap","wrong_type","omit_bull","omit_both","coordinated","financial_coordinated"])
def test_section_membership_tampering_rejected(argument_map,change):
    agent,analysis=argument_map
    sections={s.title:s.entries for s in analysis.sections}
    if change=="swap":
        updates={"Bull Case":sections["Bear Case"],"Bear Case":sections["Bull Case"]}
    elif change=="wrong_type":
        updates={"Bull Case":sections["Financial Health"][:1]}
    else:
        removed={e.claim_ref for s in ("Bull Case",) if change=="omit_bull" for e in sections[s]}
        if change!="omit_bull":
            removed={e.claim_ref for s in ("Bull Case","Bear Case") for e in sections[s]}
        if change=="financial_coordinated":
            removed={sections["Financial Health"][0].claim_ref}
        updates={title:tuple(e for e in entries if e.claim_ref not in removed) for title,entries in sections.items()
            if change in ("coordinated","financial_coordinated") or title in ("Bull Case","Bear Case")}
    with pytest.raises(ValueError):
        agent.generate_report(changed_sections(analysis,updates))


def test_direct_report_validation_catches_coordinated_omission(argument_map):
    agent,analysis=argument_map
    report=agent.generate_report(analysis)
    refs={e.claim_ref for s in analysis.sections if s.title in ("Bull Case","Bear Case") for e in s.entries}
    altered=changed_sections(analysis,{s.title:tuple(e for e in s.entries if e.claim_ref not in refs) for s in analysis.sections})
    with pytest.raises(ValueError):
        agent.validate_report(report.model_copy(update={"analysis_map":altered,"markdown":agent._render(altered)}))


def test_untampered_and_legitimate_partial_maps(argument_map):
    agent,analysis=argument_map
    assert agent.generate_report(analysis).status=="success"
    partial=analysis.model_copy(update={"issues":analysis.issues+(AgentIssue(code="caller_limitation",message="Historical context only"),)})
    report=agent.generate_report(partial)
    assert report.status=="partial"
    agent.validate_report(report)


def test_empty_argument_sections_are_legal_without_eligible_arguments(source_case):
    memory,tool=checked_store(source_case)
    agent=ReportAgent(memory,tool,full=True)
    analysis=agent.build_analysis_map(health_gate=VerificationHealthGate(memory).evaluate())
    assert all(not s.entries for s in analysis.sections if s.title in ("Bull Case","Bear Case"))
    agent.validate_report(agent.generate_report(analysis))


@pytest.mark.parametrize("value",["not-a-number","NaN","sNaN","Infinity","-Infinity",float('nan'),float('inf'),True,[],{}])
def test_malformed_argument_numbers_fail_normally(source_case,value):
    memory,_=checked_store(source_case)
    def corrupt(response,payload):
        response["arguments"][0]["premises"][0]["value"]=value
        return response
    result=BullAgent(memory,Batch2MockLLM(transform=corrupt)).build_case()
    assert result.status=="failed" and result.issues
    assert not memory.get_claims(agent="Bull")


@pytest.mark.parametrize("value",["-12.0000000000000000001",Decimal("0"),12,12.25])
def test_finite_numeric_snapshots_keep_exact_values(source_case,value):
    from memory.shared_memory import ArgumentPremise
    memory,_=checked_store(source_case)
    data=evidence_snapshot(memory).premises[0].model_dump(round_trip=True)
    data.update(unit="percent",value=value)
    assert ArgumentPremise.model_validate(data).value==Decimal(str(value))


def test_offline_identity_is_explicit():
    assert execution_identity(Batch2MockLLM()).get("kind")=="offline_mock"


def test_injected_sdk_malformed_number_is_model_output_rejection(source_case):
    import json
    from gemini import GeminiAdapter
    from agents.argument_contracts import ArgumentProposal
    from tests.test_gemini import SDKClient,response
    memory,_=checked_store(source_case);snapshot=evidence_snapshot(memory)
    valid=Batch2MockLLM().generate(ArgumentProposal,system="offline",payload={"task":"bull_case","snapshot":snapshot.model_dump(mode="json")}).model_dump(mode="json")
    valid["arguments"][0]["premises"][0]["value"]="not-a-number"
    client=SDKClient([response(json.dumps(valid))]);adapter=GeminiAdapter(client=client)
    result=BullAgent(memory,adapter).build_case(snapshot=snapshot)
    assert result.status=="failed" and not result.claim_refs and len(client.calls)==1
    assert adapter.telemetry[0].status=="malformed_output"


def test_sdk_usage_slices_and_injection_never_claim_live():
    from evaluation.metrics import condition_usage
    from gemini import GeminiAdapter,CallTelemetry
    from tests.test_gemini import SDKClient
    a=GeminiAdapter(client=SDKClient([]),allow_live=True)
    previous=CallTelemetry(request_id="previous",model_id="test",attempt=1,status="success",latency_ms=1,prompt_tokens=99,output_tokens=9,total_tokens=108)
    current=CallTelemetry(request_id="current",model_id="test",attempt=1,status="success",latency_ms=2,prompt_tokens=12,output_tokens=3,total_tokens=15)
    a.telemetry.extend((previous,current))
    measured=condition_usage(a,a.telemetry[1:])
    assert measured["execution_class"]=="injected_sdk_test" and not measured["live_empirical_evaluation"]
    assert measured["tokens"]["total"]==15 and measured["llm_requests"]==1
    assert measured["generation_transport_attempts"]==0 and measured["mock_transport_attempts"]==1
    assert measured["actual_api_cost_usd"] is None and measured["cost_estimate"] is None


def test_live_success_failure_and_unknown_identity_without_requests():
    """Simulated telemetry only: this test never constructs a real SDK client."""
    from types import SimpleNamespace
    from evaluation.metrics import condition_usage
    from gemini import GeminiAdapter,CallTelemetry
    a=GeminiAdapter(allow_live=True)
    failed=CallTelemetry(request_id="one",model_id="test",attempt=1,status="transport_error:504",latency_ms=1)
    good=CallTelemetry(request_id="one",model_id="test",attempt=2,status="success",latency_ms=1,prompt_tokens=12,output_tokens=3,total_tokens=15)
    unsuccessful=condition_usage(a,[failed])
    assert unsuccessful["execution_class"]=="failed_live_attempt" and unsuccessful["live_attempted"]
    assert not unsuccessful["live_empirical_evaluation"] and unsuccessful["tokens"]["total"] is None
    success=condition_usage(a,[good])
    assert success["live_empirical_evaluation"] and success["tokens"]["total"]==15
    mixed=condition_usage(a,[failed,good])
    assert mixed["llm_requests"]==1 and mixed["transport_attempts"]==2
    assert mixed["tokens"]["total"] is None and mixed["known_token_totals"]["total"]==15
    unknown=SimpleNamespace(mode="live enabled")
    assert execution_identity(unknown)["kind"]=="unknown"
    assert condition_usage(unknown,[])["live_attempted"] is None
    assert condition_usage(unknown,[])["llm_requests"] is None
    assert condition_usage(unknown,[])["transport_attempts"] is None


def test_pricing_requires_date_and_exact_model():
    from evaluation.metrics import condition_usage
    from gemini import GeminiAdapter
    with pytest.raises(KeyError):
        condition_usage(GeminiAdapter(),[],pricing={"input_per_million":1})
    with pytest.raises(ValueError):
        condition_usage(GeminiAdapter(),[],pricing={"as_of":"2026-10-28","model_id":"different"})


from tests.test_batch2_evaluation import evaluation_bundle


def test_run_condition_reused_injected_sdk_usage_only_current_slice(evaluation_bundle,tmp_path):
    from gemini import GeminiAdapter,CallTelemetry
    from evaluation.batch2 import run_condition
    from evaluation.full_baseline import FullBaselineResponse
    from tests.test_gemini import SDKClient,response
    fake=Batch2MockLLM()
    data=fake.generate(FullBaselineResponse,system="offline",payload=evaluation_bundle.payload)
    adapter=GeminiAdapter(client=SDKClient([response(data.model_dump_json()),response(data.model_dump_json())]))
    adapter.telemetry.append(CallTelemetry(request_id="previous",model_id="old",attempt=1,status="success",latency_ms=1,total_tokens=9999))
    for name in ("one","two"):
        manifest=run_condition("single_llm",evaluation_bundle,adapter,tmp_path/name)
        assert "failure" not in manifest,manifest
        assert manifest["tokens"]["total"]==15 and manifest["llm_requests"]==1
        assert manifest["execution_class"]=="injected_sdk_test" and not manifest["live_empirical_evaluation"]
        assert manifest["generation_transport_attempts"]==0 and manifest["mock_transport_attempts"]==1


def test_persisted_shared_budget_and_failure_halt(tmp_path):
    import httpx
    from gemini import GeminiAdapter,PersistentGenerationBudget,ModelUnavailable
    from tests.test_gemini import SDKClient,Answer,response
    path=tmp_path/"budget.json"
    budget=PersistentGenerationBudget(path)
    first=GeminiAdapter(client=SDKClient([httpx.ConnectError("injected")]),request_budget=budget)
    with pytest.raises(ModelUnavailable):first.generate(Answer,system="test",payload={})
    restored=PersistentGenerationBudget(path)
    assert restored[0]==11 and restored.state["stopped"]
    second=SDKClient([response()])
    with pytest.raises(ModelUnavailable,match="halted"):
        GeminiAdapter(client=second,request_budget=restored).generate(Answer,system="test",payload={})
    assert not second.calls


def test_persisted_budget_does_not_allow_thirteenth_transport(tmp_path):
    from gemini import GeminiAdapter,PersistentGenerationBudget,ModelUnavailable
    from tests.test_gemini import SDKClient,Answer,response
    budget=PersistentGenerationBudget(tmp_path/"budget.json")
    client=SDKClient([response() for _ in range(13)])
    adapter=GeminiAdapter(client=client,request_budget=budget)
    for _ in range(12):adapter.generate(Answer,system="test",payload={})
    with pytest.raises(ModelUnavailable,match="exhausted"):
        adapter.generate(Answer,system="test",payload={})
    assert len(client.calls)==12
