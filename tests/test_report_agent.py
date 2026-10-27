from decimal import Decimal

import pytest

from agents.document_agent import DocumentAgent
from agents.financial_agent import FinancialAgent
from agents.report_agent import ReportAgent
from memory.shared_memory import Claim, SharedMemory
from rag.models import IndexedDocument
from tests.fakes import GroundedMockLLM


@pytest.fixture
def report_context(prepared_document, offline_retriever):
    document = IndexedDocument(source=prepared_document.source, chunks=tuple(c for c in prepared_document.chunks
        if c.kind == "table" or c.evidence.page in (155, 157)), page_count=187)
    offline_retriever.index(document)
    store, llm = SharedMemory(), GroundedMockLLM(include_overview=True)
    store.register_source(document.source)
    assert DocumentAgent(store, offline_retriever, llm, source_id=document.source.source_id).extract_primitives("financial health").status == "success"
    assert FinancialAgent(store, llm).analyze("financial health",
        operations=("revenue_growth", "operating_margin", "net_margin", "current_ratio")).status == "success"
    return store, ReportAgent(store, offline_retriever)


def test_map_and_report_have_complete_provenance(report_context):
    store, agent = report_context
    analysis_map = agent.build_analysis_map(execution_mode="offline mocked model")
    assert not analysis_map.issues, analysis_map.issues
    report = agent.generate_report(analysis_map)
    assert report.status == "success"
    assert "125.8545%" in report.markdown and "4.1713" in report.markdown
    assert "Independent verification is pending" in report.markdown
    assert "offline mocked model" in report.markdown
    assert all("## " + section.title in report.markdown for section in analysis_map.sections)
    assert all(e.verification_status == "pending" for s in analysis_map.sections for e in s.entries)
    for entry in next(s.entries for s in analysis_map.sections if s.title == "Financial Health"):
        assert store.reference(entry.claim_ref.claim_id) == entry.claim_ref
        assert entry.evidence and all(agent.retriever.validate_evidence(e) for e in entry.evidence)
        if entry.calculation_ref:
            assert entry.input_refs == tuple(i.claim_ref for i in store.get_calculation(entry.calculation_ref).inputs)
    agent.validate_report(report)


@pytest.mark.parametrize("change", ["number", "new_statement", "verification"])
def test_report_cannot_add_or_alter_financial_assertions(report_context, change):
    _, agent = report_context
    report = agent.generate_report()
    text = report.markdown
    if change == "number": text = text.replace("125.8545", "999.9999")
    if change == "new_statement": text += "Invented financial conclusion: profit doubled.\n"
    if change == "verification": text = text.replace("Independent verification is pending", "Independently verified")
    with pytest.raises(ValueError, match="rendering"):
        agent.validate_report(report.model_copy(update={"markdown": text}))


def test_map_cannot_promote_verification_or_change_source_page(report_context):
    _, agent = report_context
    analysis_map = agent.build_analysis_map()
    first = analysis_map.sections[0].entries[0]
    for changed in (first.model_copy(update={"verification_status": "verified"}),
                    first.model_copy(update={"evidence": (first.evidence[0].model_copy(update={"page": 1}),)})):
        fields = analysis_map.model_dump(round_trip=True)
        fields["sections"][0]["entries"] = (changed.model_dump(round_trip=True),)
        from agents.report_agent import AnalysisMap
        with pytest.raises(ValueError, match="provenance"):
            agent.validate_analysis_map(AnalysisMap.model_validate(fields))


def test_revised_inputs_make_old_report_stale_and_new_report_partial(report_context):
    store, agent = report_context
    report = agent.generate_report()
    revenue = next(c for c in store.get_claims() if c.metric == "revenue" and c.period.end_date.year == 2024)
    fields = revenue.model_dump(round_trip=True)
    fields.update(version=2, value=Decimal("999"))
    store.append(Claim.model_validate(fields))
    with pytest.raises(ValueError):
        agent.validate_report(report)
    partial = agent.generate_report()
    assert partial.status == "partial" and partial.analysis_map.issues
    assert "125.8545%" not in partial.markdown and "| 999 |" not in partial.markdown
    assert len(store.get_calculations()) == 4  # historical artifacts preserved


@pytest.mark.parametrize("kind", ["quote", "page", "status"])
def test_unsupported_claims_only_yield_limitations(report_context, kind):
    store, agent = report_context
    fields = next(c for c in store.get_claims() if c.claim_type == "raw_primitive").model_dump(round_trip=True)
    fields["claim_id"] = "unsupported-extra"
    if kind == "quote": fields["evidence"][0]["quote"] = "Fabricated source text"
    if kind == "page": fields["evidence"][0]["page"] = 1
    if kind == "status": fields["verification_status"] = "unsupported"
    store.append(Claim.model_validate(fields))
    report = agent.generate_report()
    assert report.status == "partial" and "Fabricated source text" not in report.markdown
    assert not any(e.claim_ref.claim_id == "unsupported-extra" for s in report.analysis_map.sections for e in s.entries)
