from decimal import Decimal

import pytest

from agents.document_agent import DocumentAgent
from agents.financial_agent import FinancialAgent
from gemini import ModelUnavailable
from memory.shared_memory import Claim, SharedMemory
from rag.models import IndexedDocument
from tests.fakes import GroundedMockLLM


OPS = ("revenue_growth", "operating_margin", "net_margin", "current_ratio")


@pytest.fixture
def financial_agent(prepared_document, offline_retriever):
    document = IndexedDocument(source=prepared_document.source,
        chunks=tuple(c for c in prepared_document.chunks if c.kind == "table"), page_count=187)
    offline_retriever.index(document)
    store, llm = SharedMemory(), GroundedMockLLM()
    store.register_source(document.source)
    outcome = DocumentAgent(store, offline_retriever, llm, source_id=document.source.source_id).extract_primitives("financial health")
    assert outcome.status == "success"
    return store, llm, FinancialAgent(store, llm)


def test_financial_agent_runs_four_engine_operations(financial_agent):
    store, llm, agent = financial_agent
    raw = [c.model_dump_json() for c in store.get_claims()]
    result = agent.analyze("Analyze annual financial health", operations=OPS)
    assert result.status == "success", result.issues
    assert len(result.claim_refs) == len(result.calculation_refs) == 4
    expected = {"revenue_growth": "125.8545", "operating_margin": "54.1217", "net_margin": "48.8493", "current_ratio": "4.1713"}
    for reference in result.claim_refs:
        claim = store.resolve(reference)
        artifact = store.get_calculation(claim.calculation_ref)
        assert artifact.display_value == Decimal(expected[claim.metric])
        assert claim.value == artifact.output_value and claim.verification_status == "pending"
        assert claim.support_level == "calculation_backed"
        assert all(store.resolve(i.claim_ref).evidence[0].source_id for i in artifact.inputs)
    assert [c.model_dump_json() for c in store.get_claims() if c.claim_type == "raw_primitive"] == raw
    assert len([c for c in llm.calls if c["payload"]["task"] == "financial_interpretation"]) == 4


def test_missing_primitive_is_explicit_partial_result(financial_agent):
    store, _, agent = financial_agent
    ids = [c.claim_id for c in store.get_claims() if c.metric != "net_income"]
    result = agent.analyze("financial health", operations=OPS, primitive_claim_ids=ids)
    assert result.status == "partial" and len(result.claim_refs) == 3
    assert any("net_margin" in i.message for i in result.issues)


def test_requests_pin_current_versions(financial_agent):
    store, _, agent = financial_agent
    income = next(c for c in store.get_claims() if c.metric == "net_income")
    fields = income.model_dump(round_trip=True)
    fields.update(version=2, value=Decimal("-100"))
    store.append(Claim.model_validate(fields))
    result = agent.analyze("net margin", operations=("net_margin",))
    assert result.status == "success"
    artifact = store.get_calculation(result.calculation_refs[0])
    assert artifact.inputs[0].claim_ref.version == 2 and artifact.output_value < 0
    assert store.resolve(result.claim_refs[0]).verification_status == "pending"


@pytest.mark.parametrize("kind", ["wrong_label", "wrong_reference", "new_number"])
def test_model_cannot_change_interpretation_or_numbers(financial_agent, kind):
    store, llm, agent = financial_agent
    def transform(response, payload):
        if payload["task"] == "financial_interpretation":
            if kind == "wrong_label": response["label"] = "loss"
            if kind == "wrong_reference": response["calculation_ref"] = "invented"
            if kind == "new_number": response["value"] = 999
        return response
    llm.transform = transform
    result = agent.analyze("net margin", operations=("net_margin",))
    assert result.status == "failed" and not result.claim_refs
    assert len(result.calculation_refs) == 1  # correct engine history remains
    assert len(store.get_claims()) == 6


def test_unrequested_operations_and_empty_plan_are_explicit(financial_agent):
    _, llm, agent = financial_agent
    llm.transform = lambda response, payload: {"operations": ["current_ratio"]} if payload["task"] == "financial_plan" else response
    assert agent.analyze("net margin", operations=("net_margin",)).status == "failed"
    llm.transform = lambda response, payload: {"operations": []} if payload["task"] == "financial_plan" else response
    outcome = agent.analyze("net margin", operations=("net_margin",))
    assert outcome.status == "failed" and outcome.issues[0].code == "missing_calculations"


def test_zero_denominator_propagates_engine_rejection(financial_agent):
    store, _, agent = financial_agent
    revenue = next(c for c in store.get_claims() if c.metric == "revenue" and c.period.end_date.year == 2024)
    fields = revenue.model_dump(round_trip=True)
    fields.update(version=2, value=Decimal(0))
    store.append(Claim.model_validate(fields))
    result = agent.analyze("net margin", operations=("net_margin",))
    assert result.status == "failed" and not result.calculation_refs
    assert "zero_denominator" in result.issues[0].message


def test_ambiguous_current_primitives_are_not_arbitrarily_selected(financial_agent):
    store, _, agent = financial_agent
    revenue = next(c for c in store.get_claims() if c.metric == "revenue" and c.period.end_date.year == 2024)
    fields = revenue.model_dump(round_trip=True)
    fields["claim_id"] = "conflicting-revenue"
    store.append(Claim.model_validate(fields))
    result = agent.analyze("net margin", operations=("net_margin",))
    assert result.status == "failed" and "ambiguous" in result.issues[0].message


def test_explicit_year_does_not_silently_use_another_year(financial_agent):
    _, _, agent = financial_agent
    result = agent.analyze("financial health 2020", operations=OPS, target_year=2020)
    assert result.status == "failed" and not result.calculation_refs


def test_model_outage_is_explicit(financial_agent):
    store, llm, agent = financial_agent
    def fail(*args, **kwargs):
        raise ModelUnavailable("offline")
    llm.generate = fail
    result = agent.analyze("financial health", operations=OPS)
    assert result.status == "failed" and not store.get_calculations()
