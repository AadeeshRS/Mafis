"""Fresh, offline adversarial checks: fixtures represent source cells, not gold answers."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import json
from pathlib import Path

from agents.verification_agent import VerificationAgent
from engine.financial_engine import FinancialEngine
from memory.shared_memory import Claim, Evidence, FiscalPeriod, SharedMemory, SourceDocument
from rag.models import RetrievalHit, SourceChunk, TableCell
from rag.retriever import RetrievalUnavailable


class FreshRetriever:
    def __init__(self, chunks=(), error=None):
        self.chunks, self.error, self.calls = list(chunks), error, []

    def retrieve(self, query, filters=None, top_k=5):
        self.calls.append((query, filters, top_k))
        if self.error:
            raise self.error
        return [RetrievalHit(chunk=c, rank=i+1, distance=0.1) for i, c in enumerate(self.chunks)
                if not filters or c.source.source_id == filters.get("doc_id", c.source.source_id)]

    def validate_evidence(self, evidence):
        return any(VerificationAgent._quote_location(evidence,c) for c in self.chunks)


@pytest.fixture
def source_case():
    memory = SharedMemory("verification-test")
    source = SourceDocument(title="Offline source", entity="Acme", source_url="https://example.test/source", sha256="a"*64)
    memory.register_source(source)
    period = FiscalPeriod(kind="duration", start_date=date(2023,1,1), end_date=date(2023,12,31), label="Year ended 2023")
    chunks, claims = [], []
    for metric, value in (("revenue", "100"), ("net_income", "25")):
        ev = Evidence(source=source.title, source_id=source.source_id, source_url=source.source_url,
            source_type="annual_report", page=1, locator=metric+"/2023", quote=metric+" "+value,
            row_label=metric, column_header="2023", raw_value=value, scale_header="millions")
        cell = TableCell(cell_id=metric, metric=metric, value=Decimal(value), unit="currency", currency="USD", scale=1000000,
            period=period, accounting_scope="consolidated", evidence=ev)
        chunks.append(SourceChunk(chunk_id="chunk:"+metric, source=source, kind="table", text=ev.quote, evidence=ev, cells=(cell,)))
        claims.append(Claim(claim_id=metric, agent="DocumentAgent", claim_type="raw_primitive", entity="Acme",
            accounting_scope="consolidated", metric=metric, value=cell.value, unit="currency", currency="USD", scale=cell.scale,
            period=period, claim="Source number", evidence=(ev,), support_level="single_source"))
    return memory, FreshRetriever(chunks), claims


def test_fresh_check_preserves_exact_history_and_skips_unchanged_verified(source_case):
    memory, retriever, claims = source_case
    original = memory.append(claims[0])
    agent = VerificationAgent(memory, retriever)
    record = agent.verify_claim(original.claim_id)
    assert record.outcome == "verified" and record.checked_ref.version == 1 and record.resulting_ref.version == 2
    assert record.fresh_evidence == original.evidence
    assert len(record.retrieved_chunk_ids) == 2 and len(record.checks) == 8
    latest = memory.get_current(original.claim_id)
    assert latest.agent == original.agent and latest.run_iteration == original.run_iteration
    assert latest.value == original.value and memory.get_claim(original.claim_id, 1) == original
    calls = len(retriever.calls)
    assert agent.verify_claim(original.claim_id) == record
    assert len(retriever.calls) == calls and len(memory.get_history(original.claim_id)) == 2
    assert len(memory.get_verification_records(original.claim_id)) == 1
    record.fresh_evidence[0].__dict__["quote"] = "mutated"
    assert memory.get_verification_records()[0].fresh_evidence == original.evidence


@pytest.mark.parametrize("field,value,code", [
    ("value", Decimal("101"), "source_value"), ("scale", 1000, "source_scale"),
    ("metric", "current_assets", "source_metric"), ("currency", "EUR", "source_currency"),
    ("entity", "Different company", "source_entity"), ("accounting_scope", "standalone", "source_accounting_scope"),
    ("period", FiscalPeriod(kind="duration", start_date=date(2022,1,1), end_date=date(2022,12,31), label="2022"), "source_period"),
])
def test_tampered_numeric_dimensions_are_contradicted(source_case, field, value, code):
    memory, retriever, claims = source_case
    claim = claims[0].model_copy(update={field:value})
    memory.append(claim)
    record = VerificationAgent(memory, retriever).verify_claim(claim.claim_id)
    assert record.outcome == "flagged"
    assert any(c.code == code and c.outcome == "contradicted" for c in record.checks)
    assert not record.fresh_evidence and memory.get_current(claim.claim_id).value == claim.value


@pytest.mark.parametrize("field,value", [("locator", "forged"), ("quote", "Revenue 999"), ("page", 9), ("raw_value", "999")])
def test_tampered_citations_are_not_trusted(source_case, field, value):
    memory, retriever, claims = source_case
    claim = claims[0].model_copy(update={"evidence":(claims[0].evidence[0].model_copy(update={field:value}),)})
    memory.append(claim)
    record = VerificationAgent(memory,retriever).verify_claim(claim.claim_id)
    assert record.outcome == "flagged" and record.checks[0].code == "source_locator"


@pytest.mark.parametrize("failure", [None, RetrievalUnavailable("offline")])
def test_missing_and_failed_retrieval_never_promotes_claim(source_case, failure):
    memory, _, claims = source_case
    memory.append(claims[0])
    retriever = FreshRetriever(error=failure)
    record = VerificationAgent(memory,retriever).verify_claim(claims[0].claim_id)
    assert record.outcome == "unsupported" and not record.fresh_evidence
    assert record.checks[0].outcome == ("error" if failure else "missing")


def derived(memory, artifact):
    return memory.append(Claim(claim_id="margin", agent="FinancialAgent", claim_type="derived_metric", entity=artifact.entity,
        accounting_scope=artifact.accounting_scope, metric=artifact.operation, value=artifact.output_value,
        unit=artifact.output_unit, period=artifact.output_period, claim="Net margin calculation", calculation_ref=artifact.calculation_ref,
        support_level="calculation_backed"))


def calculate(memory):
    return FinancialEngine(memory).calculate({"operation":"net_margin", "inputs":{
        "net_income":memory.reference("net_income"), "revenue":memory.reference("revenue")}}).artifact


def test_verified_current_inputs_replay_and_later_revision_fails_strictly(source_case):
    memory, retriever, claims = source_case
    for claim in claims:
        memory.append(claim)
    verifier = VerificationAgent(memory,retriever)
    verifier.verify_all()
    artifact = calculate(memory)
    claim = derived(memory,artifact)
    assert verifier.verify_claim(claim.claim_id).outcome == "verified"
    upstream = memory.get_current("revenue")
    memory.append(upstream.model_copy(update={"version":upstream.version+1, "verification_status":"pending"}))
    failed = verifier.verify_claim(claim.claim_id)
    assert failed.outcome == "unsupported"
    assert any(c.code == "calculation_freshness" and c.outcome == "missing" for c in failed.checks)
    assert memory.get_calculation(artifact.calculation_ref) == artifact


def test_calculation_success_does_not_verify_pending_inputs(source_case):
    memory, retriever, claims = source_case
    for claim in claims:
        memory.append(claim)
    claim = derived(memory,calculate(memory))
    record = VerificationAgent(memory,retriever).verify_claim(claim.claim_id)
    assert record.outcome == "unsupported"
    assert any(c.code == "calculation_verified_inputs" and c.outcome == "missing" for c in record.checks)


def test_replay_failure_is_explicit(source_case):
    memory, retriever, claims = source_case
    for claim in claims:
        memory.append(claim)
    verifier = VerificationAgent(memory,retriever)
    verifier.verify_all()
    claim = derived(memory,calculate(memory))
    class RejectedReplay:
        def validate_artifact(self, artifact):
            raise ValueError("Artifact replay mismatch")
    record = VerificationAgent(memory,retriever,RejectedReplay()).verify_claim(claim.claim_id)
    assert record.outcome == "flagged" and any(c.code == "calculation_replay" and c.outcome == "contradicted" for c in record.checks)


def test_exact_narrative_quote_and_forged_claim(source_case):
    memory, retriever, claims = source_case
    source = memory.get_source(claims[0].evidence[0].source_id)
    ev = claims[0].evidence[0].model_copy(update={"locator":"overview", "quote":"Acme is headquartered in Example City."})
    chunk = SourceChunk(chunk_id="overview", source=source, kind="narrative", text=ev.quote, evidence=ev)
    retriever.chunks = [chunk]
    quote = ev.model_copy(update={"locator":"overview;quote-offset=0"})
    fact = Claim(claim_id="overview", agent="DocumentAgent", claim_type="qualitative", entity=source.entity,
        claim=quote.quote, evidence=(quote,), support_level="single_source")
    memory.append(fact)
    verifier = VerificationAgent(memory,retriever)
    assert verifier.verify_claim("overview").outcome == "verified"
    memory.append(fact.model_copy(update={"version":3,"claim":"Acme is guaranteed to grow."}))
    assert verifier.verify_claim("overview").outcome == "flagged"


def test_source_identity_dates_tampering_is_not_secondhand_verification(source_case):
    memory,retriever,claims = source_case
    memory.append(claims[0])
    retriever.chunks = [c.model_copy(update={"source":c.source.model_copy(update={"as_of_date":date(2025,1,1)})}) for c in retriever.chunks]
    record = VerificationAgent(memory,retriever).verify_claim("revenue")
    assert record.outcome == "flagged" and record.checks[0].code == "source_identity"


def test_duplicate_source_citations_do_not_inflate_support(source_case):
    memory,retriever,claims = source_case
    memory.append(claims[0].model_copy(update={"evidence":claims[0].evidence*2}))
    record=VerificationAgent(memory,retriever).verify_claim("revenue")
    assert record.support_level == "single_source" and len(record.fresh_evidence) == 1


def test_actual_pdf_primitives_and_context_independently_retrieved(prepared_document,offline_retriever):
    from agents.document_agent import DocumentAgent
    from tests.fakes import GroundedMockLLM
    memory=SharedMemory("actual-pdf-verification")
    memory.register_source(prepared_document.source)
    offline_retriever.index(prepared_document)
    extraction=DocumentAgent(memory,offline_retriever,GroundedMockLLM(include_overview=True),source_id=prepared_document.source.source_id).extract_primitives("Financial statements")
    assert extraction.status=="success"
    records=VerificationAgent(memory,offline_retriever).verify_all()
    assert records and all(r.outcome=="verified" for r in records), [(r.checked_ref.claim_id,r.checks) for r in records]
    assert all(memory.is_current_verified(r.checked_ref.claim_id) for r in records)
    assert any(memory.resolve(r.checked_ref).claim_type=="qualitative" for r in records)
    for record in records:
        if memory.resolve(record.checked_ref).claim_type!="raw_primitive":
            continue
        codes={c.code for c in record.checks}
        assert "currency_context" in codes
        if memory.resolve(record.checked_ref).period.kind=="duration":
            assert "fiscal_calendar" in codes


@pytest.mark.parametrize("tamper", [False,True])
def test_calendar_metadata_must_match_fresh_header_text(source_case,tamper):
    old,retriever,claims=source_case
    source=old.get_source(claims[0].evidence[0].source_id)
    context=claims[0].evidence[0].model_copy(update={"page":2,"locator":"pdf-page=2;section=Fiscal Year",
        "quote":"Fiscal years 2023, 2022 and 2021 were all 52-week years."})
    source=source.model_copy(update={"fiscal_year_weeks":tuple((y,53 if tamper else 52) for y in (2023,2022,2021)),
        "fiscal_calendar_evidence":context})
    memory=SharedMemory()
    memory.register_source(source)
    period=claims[0].period.model_copy(update={"start_date":None})
    retriever.chunks=[c.model_copy(update={"source":source,"cells":tuple(cell.model_copy(update={"period":period}) for cell in c.cells)}) for c in retriever.chunks]
    retriever.chunks.append(SourceChunk(chunk_id="calendar",source=source,kind="narrative",text=context.quote,evidence=context))
    memory.append(claims[0].model_copy(update={"period":period}))
    record=VerificationAgent(memory,retriever).verify_claim("revenue")
    assert record.outcome==("flagged" if tamper else "verified")
    assert any(c.code=="fiscal_calendar" and c.outcome==("contradicted" if tamper else "passed") for c in record.checks)


def test_real_market_and_risk_templates_verify_without_causal_proof():
    from agents.market_agent import MarketAgent
    from agents.risk_agent import RiskAgent
    memory=SharedMemory()
    source=SourceDocument(title="Official economic statement",entity="US economy",source_url="https://example.test/statement",
        source_type="news",sha256="b"*64,as_of_date=date(2024,1,31),
        published_at=datetime(2024,1,31,tzinfo=timezone.utc),retrieved_at=datetime(2024,2,1,tzinfo=timezone.utc))
    text="Inflation remains elevated while economic activity continues to expand."
    ev=Evidence(source=source.title,source_id=source.source_id,source_url=source.source_url,source_type="news",locator="official-statement",quote=text)
    retriever=FreshRetriever([SourceChunk(chunk_id="economic-statement",source=source,kind="narrative",text=text,evidence=ev)])
    market=MarketAgent(memory,retriever).research("inflation economic macro")
    assert market.status=="success"
    verifier=VerificationAgent(memory,retriever)
    assert all(r.outcome=="verified" for r in verifier.verify_all([r.claim_id for r in market.claim_refs]))
    risk=RiskAgent(memory).assess_risk([], [r.claim_id for r in market.claim_refs],categories=("macro",))
    assert risk.status=="success"
    record=verifier.verify_claim(risk.claim_refs[0].claim_id)
    assert record.outcome=="verified" and any(c.code=="risk_traceability" for c in record.checks)
    original=memory.get_current(risk.claim_refs[0].claim_id)
    memory.append(original.model_copy(update={"version":original.version+1,"claim":"Inflation will certainly cause insolvency."}))
    assert verifier.verify_claim(original.claim_id).outcome=="unsupported"


@pytest.mark.parametrize("issuer", ["apple_2024","coca_cola_2024"])
def test_all_annual_anchors_come_from_fresh_header_not_selected_cells(issuer):
    from rag.ingest import extract_financial_facts
    root=Path("tests/fixtures")/issuer
    gold=json.loads((root/"annotations.json").read_text())
    identity={key:gold["document"][key] for key in ("source_url","title","entity")}
    extracted=extract_financial_facts(root/"annual_report.pdf",**identity)
    assert extracted.ok and len(extracted.source.annual_period_ends)==3
    source=extracted.source
    memory=SharedMemory()
    memory.register_source(source)
    chunks=[]
    for claim in extracted.claims:
        ev=claim.evidence[0]
        cell=TableCell(cell_id=claim.claim_id,metric=claim.metric,value=claim.value,unit=claim.unit,currency=claim.currency,
            scale=claim.scale,period=claim.period,accounting_scope=claim.accounting_scope,evidence=ev)
        text="\n".join((ev.scale_header,ev.period_header,ev.quote))
        chunks.append(SourceChunk(chunk_id=claim.claim_id,source=source,kind="table",text=text,evidence=ev,cells=(cell,)))
        memory.append(claim)
    for name in ("currency_evidence","annual_period_evidence","fiscal_calendar_evidence"):
        ev=getattr(source,name)
        if ev is not None:
            chunks.append(SourceChunk(chunk_id=name,source=source,kind="narrative",text=ev.quote,evidence=ev))
    assert len({c.period.end_date for c in extracted.claims if c.claim_type=="raw_primitive" and c.period.kind=="duration"})==2
    retriever=FreshRetriever(chunks)
    verifier=VerificationAgent(memory,retriever)
    records=verifier.verify_all()
    assert all(record.outcome=="verified" for record in records), [(r.checked_ref.claim_id,[(c.code,c.message) for c in r.checks if c.outcome!="passed"],source.annual_period_evidence.quote) for r in records if r.outcome!="verified"]
    assert all(any(c.code=="annual_period_header" and c.outcome=="passed" for c in r.checks)
               for r in records if memory.resolve(r.checked_ref).period.kind=="duration")
    # Forge only the otherwise unextracted THIRD anchor, preserving fresh text.
    third=source.annual_period_ends[-1]
    bad=source.model_copy(update={"annual_period_ends":source.annual_period_ends[:-1]+(third.replace(day=third.day-1),)})
    other=SharedMemory()
    other.register_source(bad)
    original=extracted.claims[0]
    other.append(original)
    altered=[chunk.model_copy(update={"source":bad}) for chunk in chunks]
    record=VerificationAgent(other,FreshRetriever(altered)).verify_claim(original.claim_id)
    assert record.outcome=="flagged"
    assert any(c.code=="annual_period_header" and c.outcome=="contradicted" for c in record.checks)


def test_split_header_parses_all_columns_after_fresh_whitespace_normalization():
    from agents.verification_agent import _annual_header_dates
    assert _annual_header_dates("September 28, September 30, September 24,\n2024 2023 2022") == (
        date(2024,9,28),date(2023,9,30),date(2022,9,24))
    assert _annual_header_dates("Years Ended December 31, 2024 2023 2022") == (
        date(2024,12,31),date(2023,12,31),date(2022,12,31))


def test_market_statement_date_fallback_requires_checked_source_primitives(source_case):
    from agents.market_agent import MarketAgent
    memory,retriever,claims=source_case
    memory.append(claims[0])
    source=retriever.chunks[0].source
    table_chunks=list(retriever.chunks)
    text="The company faces competitive pressures in its historical operating markets."
    ev=claims[0].evidence[0].model_copy(update={"quote":text,"locator":"historical-context"})
    chunk=SourceChunk(chunk_id="historical-context",source=source,kind="narrative",text=text,evidence=ev)
    retriever.chunks=[chunk]
    result=MarketAgent(memory,retriever).research("historical markets")
    assert result.status=="success"
    verifier=VerificationAgent(memory,retriever)
    failed=verifier.verify_claim(result.claim_refs[0].claim_id)
    assert failed.outcome=="unsupported"
    assert any(c.code=="market_date_provenance" and c.outcome=="missing" for c in failed.checks)
    retriever.chunks=table_chunks+[chunk]
    assert verifier.verify_claim("revenue").outcome=="verified"
    assert verifier.verify_claim(result.claim_refs[0].claim_id).outcome=="verified"
