from decimal import Decimal
import json
from pathlib import Path

import pytest

from config import PRIMARY_MODEL
from evaluation.baseline import BaselineMetric, BaselineResponse, BaselineRun, context_digest
from evaluation.metrics import expectations, numerically_equal, score_baseline, usage
from evaluation.run import compare_case
from gemini import GeminiAdapter, GeminiSettings, ModelUnavailable
from rag.models import IndexedDocument
from tests.fakes import ReplaySDKClient


@pytest.fixture(scope="module")
def small_document(prepared_document):
    return IndexedDocument(source=prepared_document.source,page_count=187,
        chunks=tuple(c for c in prepared_document.chunks if c.kind=="table" or c.evidence.page in (155,157)))


@pytest.fixture
def controlled_case(small_document,offline_retriever,monkeypatch,tmp_path):
    def cached_ingest(*args,**kwargs):
        kwargs["retriever"].index(small_document)
        return small_document
    monkeypatch.setattr("graph.ingest_document",cached_ingest)
    monkeypatch.setattr("evaluation.baseline.ingest_document",cached_ingest)
    cases=json.loads(Path("tests/fixtures/phase1_cases.json").read_text())["cases"]
    case=cases[0]
    case["case_id"]="unit_comparison"
    case["gold"]=str(Path(case["gold"]).resolve())
    case["document"]["path"]=str(Path(case["document"]["path"]).resolve())
    monkeypatch.chdir(tmp_path)
    return case,offline_retriever


def test_controlled_offline_harness_and_complete_manifest(controlled_case):
    case,index=controlled_case
    result=compare_case(case,index,mocked=True,request_budget=[7])
    assert result["execution_mode"]=="mock" and "empirical comparison pending" in result["comparison_status"]
    assert result["retrieval"]["identical_source_context"]
    assert result["model_id"]==PRIMARY_MODEL
    assert result["source_hash"] and result["run_ids"]["mafis"]!=result["run_ids"]["single_llm"]
    for arm in ("mafis","single_llm"):
        score=result["measurements"][arm]
        assert score["numerical_correct"]==4 and not score["pipeline_failures"]
        assert score["citation_coverage"]==score["citation_correctness"]==1
        assert score["source_fact_completeness"]==1 and score["unsupported_factual_claims"]==0
        assert score["latency_ms"]>=0 and score["actual_api_cost_usd"]=="0"
        assert score["input_tokens"] is None and score["retrieval_calls"]==8
    assert result["measurements"]["mafis"]["llm_calls"]==6
    assert result["measurements"]["single_llm"]["llm_calls"]==1
    assert result["measurements"]["mafis"]["calculation_calls"]==4


def test_live_comparison_cannot_bypass_free_tier_gate(controlled_case):
    case,index=controlled_case
    with pytest.raises(ValueError,match="free tier"):
        compare_case(case,index,mocked=False)


def test_baseline_wrong_numbers_and_missing_citations_are_measured(small_document):
    gold=json.loads(Path("tests/fixtures/nvidia_2024/annotations.json").read_text())
    cell=next(c.cells[0] for c in small_document.chunks if c.cells)
    response=BaselineResponse(metrics=(BaselineMetric(operation="net_margin",value="999",unit="percent",
        period_end=cell.period.end_date,input_cell_ids=("invented",)),),sections=("Financial Health",))
    run=BaselineRun(run_id="baseline-unit",status="success",response=response,context=small_document.chunks,latency_ms=1)
    measured=score_baseline(run,gold)
    assert measured["numerical_correct"]==0 and measured["citation_correctness"]==0
    assert measured["unsupported_factual_claims"]==1 and len(measured["missing_calculations"])==3
    assert measured["source_fact_completeness"]==0 and measured["section_completeness"]==pytest.approx(1/6)


def test_baseline_abstention_and_failure_are_not_success(small_document):
    gold=json.loads(Path("tests/fixtures/nvidia_2024/annotations.json").read_text())
    response=BaselineResponse(metrics=(BaselineMetric(operation="net_margin",value=None,unit="percent",
        period_end="2024-01-28",input_cell_ids=(),abstained=True),),sections=())
    run=BaselineRun(run_id="abstention",status="success",response=response,context=small_document.chunks,latency_ms=0)
    score=score_baseline(run,gold)
    assert score["abstained_calculations"]==["net_margin"] and len(score["missing_calculations"])==4
    failed=BaselineRun(run_id="failed",status="failed",latency_ms=0,issues=("model_unavailable",))
    assert score_baseline(failed,gold)["pipeline_failures"]==["model_unavailable"]


def test_numerical_tolerance_and_nonfinite_handling():
    assert numerically_equal("1.0000",Decimal("1.00001"))
    assert not numerically_equal("1.001",Decimal(1))
    assert not numerically_equal("NaN",Decimal(1))


def test_context_fingerprint_is_order_independent_and_value_sensitive(small_document):
    assert context_digest(small_document.chunks)==context_digest(reversed(small_document.chunks))
    changed=small_document.chunks[0].model_copy(update={"text":"changed"})
    assert context_digest((changed,)+small_document.chunks[1:])!=context_digest(small_document.chunks)


def test_shared_request_budget_is_enforced_without_model_substitution():
    from agents.financial_agent import FinancialPlan
    adapter=GeminiAdapter(GeminiSettings(),client=ReplaySDKClient(),request_budget=[1])
    payload={"task":"financial_plan","requested_operations":["net_margin"]}
    assert adapter.generate(FinancialPlan,system="test",payload=payload).operations==("net_margin",)
    with pytest.raises(ModelUnavailable,match="budget"):
        adapter.generate(FinancialPlan,system="test",payload=payload)
    assert usage([adapter],mocked=True)["llm_calls"]==1
