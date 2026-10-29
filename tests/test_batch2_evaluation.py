import csv
import pytest
from evaluation.batch2 import detection_metrics,freeze_threshold,human_materials,import_ratings,validate_pair,execution_identity


def test_metrics_zero_denominators_and_compatible_false_positives():
    assert detection_metrics([],[])["precision"] is None
    actual=detection_metrics([True,False,True,False],[True,False,False,False])
    assert actual["precision"]==1 and actual["recall"]==0.5 and actual["compatible_false_positive_rate"]==0
    with pytest.raises(ValueError):
        detection_metrics([True],[])


def test_threshold_is_validation_only_and_reproducible(tmp_path):
    labels=[{"empty":False,"upstream_failure":False,"ineligible_rate":0.2,"should_block":False},
            {"empty":False,"upstream_failure":False,"ineligible_rate":0.6,"should_block":True}]
    with pytest.raises(ValueError):
        freeze_threshold(labels,split="test",output=tmp_path/"bad.json")
    a=freeze_threshold(labels,split="validation",output=tmp_path/"frozen.json")
    b=freeze_threshold(labels,split="validation",output=tmp_path/"repeated.json")
    assert a==b and a["threshold"]==0.25


def test_human_materials_do_not_fabricate_ratings(tmp_path):
    report=tmp_path/"report.md"; report.write_text("# MAFIS\nExecution: full\nUnverified experimental baseline output; single-call model interpretation.\nRevenue 100 USD; page 2.\n")
    target=tmp_path/"human"
    human_materials({"condition":report},target)
    assert import_ratings(target/"ratings_blank.csv")["completed_ratings"]==0
    assert import_ratings(target/"ratings_blank.csv")["means"]["accuracy"] is None
    exported=next(p for p in target.glob("*.md") if p.name!="rubric.md").read_text()
    assert not any(term in exported.lower() for term in ("mafis","baseline","single-call","execution:"))
    assert "Revenue 100 USD; page 2." in exported and "Unverified" in exported


def test_freeze_refuses_later_label_changes(tmp_path):
    path=tmp_path/"frozen.json"
    labels=[{"empty":False,"upstream_failure":False,"ineligible_rate":0.2,"should_block":False}]
    original=freeze_threshold(labels,split="validation",output=path)
    assert freeze_threshold(labels,split="validation",output=path)["configuration_hash"]==original["configuration_hash"]
    with pytest.raises(ValueError,match="cannot be overwritten"):
        freeze_threshold([dict(labels[0],should_block=True)],split="validation",output=path)


@pytest.mark.parametrize("field",["context_sha256","execution_identity","question","as_of","risk_categories"])
def test_pairing_rejects_unequal_evidence_models_and_scope(field):
    from tests.batch2_fakes import Batch2MockLLM
    arm={"context_sha256":"source-hash","execution_identity":execution_identity(Batch2MockLLM()),
         "question":"financial health","as_of":None,"risk_categories":["financial"]}
    assert validate_pair(arm,arm)["valid"]
    assert not validate_pair(arm,dict(arm,**{field:"changed"}))["valid"]


def test_shared_attempt_budget_counts_failures_across_adapters():
    import httpx
    from gemini import GeminiAdapter,GeminiSettings,ModelUnavailable
    from tests.test_gemini import SDKClient,Answer,response
    budget=[2]
    one=SDKClient([httpx.ConnectError("injected failure"),response()])
    two=SDKClient([response()])
    a=GeminiAdapter(GeminiSettings(max_retries=1),client=one,request_budget=budget,sleeper=lambda _:None)
    b=GeminiAdapter(client=two,request_budget=budget)
    assert a.generate(Answer,system="rules",payload={}).text=="grounded"
    with pytest.raises(ModelUnavailable,match="budget exhausted"):
        b.generate(Answer,system="rules",payload={})
    assert len(one.calls)==2 and len(two.calls)==0 and budget==[0]


def test_full_python_entry_point_cannot_create_independent_request_budgets():
    from graph import build_full_graph
    from gemini import GeminiAdapter
    one,two=GeminiAdapter(request_budget=[12]),GeminiAdapter(request_budget=[12])
    with pytest.raises(ValueError,match="one shared"):
        build_full_graph(document_llm=one,financial_llm=two,retriever=object())
    adapters=[GeminiAdapter() for _ in range(5)]
    build_full_graph(retriever=object(),**dict(zip(("document_llm","financial_llm","bull_llm","bear_llm","critic_llm"),adapters)))
    assert all(a.request_budget is adapters[0].request_budget for a in adapters)


@pytest.fixture(scope="module")
def evaluation_bundle(prepared_document,tmp_path_factory):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from rag.retriever import SharedRetriever
    from rag.market_sources import ingest_market_snapshot
    from tests.conftest import HashTestEmbedder
    from evaluation.baseline import context_digest
    case=json.loads(Path("tests/fixtures/phase1_cases.json").read_text())["cases"][0]
    retriever=SharedRetriever(path=tmp_path_factory.mktemp("b2eval_index"),embedder=HashTestEmbedder(),embedding_model="test-hash-v1")
    retriever.index(prepared_document)
    market=ingest_market_snapshot("tests/fixtures/market_snapshots/fomc_2024_01_31.json",retriever=retriever)
    chunks=tuple(prepared_document.chunks)+tuple(market.chunks)
    from agents.planner import PlannerAgent
    plan=PlannerAgent().build_full_plan(case["question"],True)
    payload={"task":"single_llm_baseline","question":case["question"],"requested_metrics":list(plan.metrics),
        "requested_operations":list(plan.operations),"chunks":[c.model_dump(mode="json") for c in chunks]}
    return SimpleNamespace(case=case,retriever=retriever,prepared=prepared_document,chunks=chunks,
        market_id=market.source.source_id,fingerprint=context_digest(chunks),payload=payload)


@pytest.mark.parametrize("condition",["single_llm","full","without_verification","without_bull_bear","without_critic","without_reanalysis","without_engine","unified_analyst"])
def test_conditions_change_execution_and_gold_opens_after_inference(evaluation_bundle,condition,tmp_path,monkeypatch):
    from pathlib import Path
    from evaluation.batch2 import run_condition
    from tests.batch2_fakes import Batch2MockLLM
    from engine.financial_engine import FinancialEngine
    model=Batch2MockLLM()
    if condition in ("single_llm","without_engine"):
        def forbidden(*args,**kwargs):
            raise AssertionError("Engine used during engine-free inference")
        monkeypatch.setattr(FinancialEngine,"calculate",forbidden)
    original=Path.read_text
    gold_read_calls=[]
    def audited(path,*args,**kwargs):
        if path.resolve()==Path(evaluation_bundle.case["gold"]).resolve():
            gold_read_calls.append(len(model.calls))
            assert model.calls,"Gold opened before inference"
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,"read_text",audited)
    result=run_condition(condition,evaluation_bundle,model,tmp_path)
    tasks=[c["payload"]["task"] for c in model.calls]
    assert gold_read_calls==[len(model.calls)]
    assert result["numerical_accuracy"]==1
    if condition=="single_llm":
        assert tasks==["single_llm_baseline"]
        assert {a["section"] for a in result["response"]["analysis"]}>={"Market Analysis","Risk Assessment","Bull Case","Bear Case"}
        assert "Bull Case" in model.calls[0]["payload"]["requested_scope"]
    if condition=="without_engine":
        assert result["calculation_calls"]==0 and len(tasks)>1
    if condition=="without_verification":
        assert result["verification_records"]==0 and "critic_explanation" in tasks
    if condition=="without_bull_bear":
        assert not set(tasks)&{"bull_case","bear_case"}
    if condition=="without_critic":
        assert "critic_explanation" not in tasks
    if condition=="without_reanalysis":
        assert not any(d["outcome"]=="executed" for d in result["retry_decisions"])
    if condition=="unified_analyst":
        assert tasks[0]=="unified_analysis" and "financial_plan" not in tasks and "document_extraction" not in tasks and result["calculation_calls"]==4


def test_unified_condition_keeps_one_targeted_retry(evaluation_bundle,tmp_path):
    from evaluation.batch2 import run_condition
    from tests.batch2_fakes import Batch2MockLLM
    calls=[0]
    def omit_once(response,payload):
        if payload["task"]=="unified_analysis":
            calls[0]+=1
            if calls[0]==1:
                response["primitives"]=[p for p in response["primitives"] if p["metric"]!="net_income"]
        return response
    result=run_condition("unified_analyst",evaluation_bundle,Batch2MockLLM(transform=omit_once),tmp_path)
    assert result["report_status"]=="success"
    assert calls[0]==2 and result["calculation_calls"]==4
    assert len(result["retry_decisions"])==1 and result["retry_decisions"][0]["budget_after"]==0


def test_without_reanalysis_does_not_correct_recoverable_gap(evaluation_bundle,tmp_path):
    from evaluation.batch2 import run_condition
    from tests.batch2_fakes import Batch2MockLLM
    def omit(response,payload):
        if payload["task"]=="document_extraction":
            response["primitives"]=[p for p in response["primitives"] if p["metric"]!="net_income"]
        return response
    model=Batch2MockLLM(transform=omit)
    result=run_condition("without_reanalysis",evaluation_bundle,model,tmp_path)
    assert result["report_status"]=="partial" and result["numerical_correct"]==3
    assert sum(c["payload"]["task"]=="document_extraction" for c in model.calls)==1
    assert result["retry_decisions"][0]["outcome"]=="unresolved" and result["retry_decisions"][0]["budget_after"]==1


def test_unchecked_condition_can_retry_source_gap_without_forging_checks(evaluation_bundle,tmp_path):
    from evaluation.batch2 import run_condition
    from tests.batch2_fakes import Batch2MockLLM
    calls=[0]
    def omit_once(response,payload):
        if payload["task"]=="document_extraction":
            calls[0]+=1
            if calls[0]==1:
                response["primitives"]=[p for p in response["primitives"] if p["metric"]!="net_income"]
        return response
    result=run_condition("without_verification",evaluation_bundle,Batch2MockLLM(transform=omit_once),tmp_path)
    assert calls[0]==2 and result["numerical_accuracy"]==1 and result["verification_records"]==0
    assert result["retry_decisions"][0]["budget_after"]==0
