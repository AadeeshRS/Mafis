"""Validation-derived parser coverage. Gold stays outside production inference."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import pytest
from rag.ingest import StatementPage,TextLine,comparative_dates,extract_alternate_statement,prepare_document


def test_inline_scale_native_header_signed_consolidated_rows():
    from tests.test_verification_agent import source_case
    memory,_,claims=source_case.__wrapped__()
    source=memory.get_source(claims[0].evidence[0].source_id).model_copy(update={"currency":"USD","currency_evidence":claims[0].evidence[0].model_copy(update={"quote":"Financial statements presented in U.S. dollars"})})
    rows=["Consolidated Statements of Operations",
        "Years Ended (In Millions, Except Per Share Amounts) Dec 28, 2024 Dec 30, 2023 Dec 31, 2022",
        "Net revenue $ 53,101 $ 54,228 $ 63,054",
        "Operating income (loss) (11,678) 93 2,334",
        "Net income (loss) (19,233) 1,675 8,017",
        "Net income (loss) attributable to parent (18,756) 1,689 8,014"]
    page=StatementPage(5,800,tuple(TextLine(t,(10,20+i*20,550,35+i*20)) for i,t in enumerate(rows)))
    claims,failures,anchors=extract_alternate_statement(page,"income",source)
    assert not failures and len(claims)==4
    assert [c.value for c in claims]==list(map(Decimal,["53101","54228","-11678","-19233"]))
    assert all(c.evidence[0].printed_page is None for c in claims)
    assert len(anchors[0])==3
    missing=source.model_copy(update={"currency":None,"currency_evidence":None})
    assert not extract_alternate_statement(page,"income",missing)[0]


@pytest.mark.parametrize("text",["December 28, December 30, December 31,\n2024 2023 2022",
    "December28, December30, December31, 2024 2023 2022",
    "Dec 28, 2024 Dec 30, 2023 Dec 31, 2022"])
def test_comparative_calendar_dates(text):
    assert [str(d) for d in comparative_dates(text)]==["2024-12-28","2023-12-30","2022-12-31"]


def test_tagged_overlay_filter_preserves_native_geometry():
    from rag.ingest import source_text_lines
    class Page:
        chars=[{"tag":"OCRPageInfo"},{"tag":"PlacedPDF"}]
        def filter(self,predicate):
            assert not predicate(self.chars[0]) and predicate(self.chars[1])
            return self
        def extract_text_lines(self):
            return [{"text":"Net revenue 100","x0":1,"top":2,"x1":3,"bottom":4}]
    assert source_text_lines(Page())==(TextLine("Net revenue 100",(1,2,3,4)),)


@pytest.mark.parametrize("case_id",["amd_2024","amazon_2024","meta_2024","pepsico_2024"])
def test_new_source_actual_pdf_fresh_checks_and_full_workflow(tmp_path,case_id):
    from rag.retriever import SharedRetriever
    from rag.market_sources import ingest_market_snapshot
    from tests.conftest import HashTestEmbedder
    from tests.batch2_fakes import Batch2MockLLM
    from graph import run_full_pipeline
    from evaluation.metrics import expectations,numerically_equal
    case=next(c for c in json.loads(Path("tests/fixtures/batch2_cases.json").read_text())["cases"] if c["case_id"]==case_id)
    doc=prepare_document(**case["document"])
    assert not doc.limitations
    index=SharedRetriever(path=tmp_path/"index",embedder=HashTestEmbedder(),embedding_model="test-hash-v1")
    index.index(doc)
    market=ingest_market_snapshot("tests/fixtures/market_snapshots/fomc_2024_01_31.json",retriever=index)
    model=Batch2MockLLM()
    state=run_full_pipeline(case["question"],case["document"],prepared_document=doc,retriever=index,
        document_llm=model,financial_llm=model,bull_llm=model,bear_llm=model,critic_llm=model,
        market_filters={"doc_id":market.source.source_id,"kind":"narrative"},risk_categories=("financial","macro"))
    assert state["report"].status=="success",state["analysis_map"].issues
    memory=state["memory"]
    raw=[c for c in memory.get_claims() if c.claim_type=="raw_primitive"]
    assert len(raw)==6 and all(memory.is_current_verified(c.claim_id) for c in raw)
    _,oracle=expectations(json.loads(Path(case["gold"]).read_text()))
    derived=[c for c in memory.get_claims() if c.claim_type=="derived_metric"]
    assert len(derived)==4
    assert all(numerically_equal(c.value,oracle[c.metric]) and memory.get_calculation_freshness(c.calculation_ref)=="current" for c in derived)


@pytest.mark.parametrize("text",["Year Ended December 31,\n2022 2023 2024","Fiscal years ended December 28, 2024, December 30, 2023 and December 31, 2022"])
def test_ordered_years_preserve_physical_columns(text):
    dates=comparative_dates(text)
    assert len(dates)==3 and len(set(dates))==3


@pytest.mark.parametrize("text",["December 31, 2024 2022 2023","December 31, 2024 2024 2022","December 31, 2024 some unrelated prose 2023"])
def test_ambiguous_comparative_years_rejected(text):
    with pytest.raises(ValueError):comparative_dates(text)
