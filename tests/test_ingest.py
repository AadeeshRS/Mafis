"""Real-PDF success fixtures; adversarial cases modify its extracted source lines."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pdfplumber
import pytest
from pydantic import ValidationError

from memory.shared_memory import Claim, FiscalPeriod, SharedMemory, SourceDocument
from rag.ingest import (
    StatementPage, TextLine, extract_financial_facts, extract_statement, normalize_number,
)


FIXTURE = Path(__file__).parent / "fixtures" / "nvidia_2024"
PDF = FIXTURE / "annual_report.pdf"
IDENTITY = {
    "source_url": "https://s201.q4cdn.com/141608511/files/doc_financials/2024/ar/NVIDIA-2024-Annual-Report.pdf",
    "title": "NVIDIA FY2024 Annual Report (including Form 10-K)",
    "entity": "NVIDIA Corporation",
}
INCOME = "Consolidated Statements of Income"
BALANCE = "Consolidated Balance Sheets"


@pytest.fixture(scope="session")
def gold():
    # This file is read only by tests, never by rag/ or an agent.
    return json.loads((FIXTURE / "annotations.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def result(tmp_path_factory):
    # Extract from an arbitrarily named PDF without any adjacent gold/metadata.
    isolated = tmp_path_factory.mktemp("unlabelled_source") / "source.pdf"
    shutil.copyfile(PDF, isolated)
    return extract_financial_facts(isolated, **IDENTITY)


@pytest.fixture(scope="session")
def pages():
    with pdfplumber.open(PDF) as pdf:
        found = {}
        for n in (150, 152):
            page = pdf.pages[n - 1]
            lines = tuple(TextLine(line["text"], (line["x0"], line["top"], line["x1"], line["bottom"]))
                          for line in page.extract_text_lines())
            found[n] = StatementPage(n, page.height, lines)
        return found


def test_fixture_identity(gold):
    data = PDF.read_bytes()
    assert len(data) == gold["document"]["byte_length"]
    assert sha256(data).hexdigest() == gold["document"]["sha256"]
    with pdfplumber.open(PDF) as pdf:
        assert len(pdf.pages) == gold["document"]["pdf_page_count"]
        assert "NVIDIA" in pdf.pages[0].extract_text()


@pytest.mark.parametrize("index", range(6))
def test_annotated_value_and_provenance(index, gold, result):
    assert result.ok, result.failures
    expected = gold["values"][index]
    matches = [claim for claim in result.claims
               if claim.metric == expected["metric"]
               and claim.period.end_date == date.fromisoformat(expected["period_end"])]
    assert len(matches) == 1
    claim = matches[0]
    assert claim.value == Decimal(expected["value"])
    assert claim.base_value == Decimal(expected["base_value"])
    assert claim.unit == gold["unit"]
    assert claim.currency == gold["currency"]
    assert claim.scale == gold["scale"]
    assert claim.period.kind == expected["period_kind"]
    assert claim.period.start_date == expected["period_start"]
    assert len(claim.evidence) == 1
    ev = claim.evidence[0]
    assert ev.source_id == "sha256:" + gold["document"]["sha256"]
    assert str(ev.source_url) == gold["document"]["source_url"]
    assert ev.page == expected["pdf_page"]
    assert ev.printed_page == expected["printed_page"]
    assert ev.section == expected["table"]
    assert ev.row_label == expected["row"]
    assert ev.column_header == expected["column"]
    assert ev.raw_value == expected["raw_value"]
    assert ev.scale_header == expected["scale_header"]
    assert expected["column"] in ev.period_header
    assert ev.bbox == pytest.approx(expected["row_bbox"], abs=0.02)
    assert ev.locator == (f"pdf-page={ev.page};table={expected['table']};"
                          f"row={expected['row']};column={expected['column']}")
    assert expected["raw_value"] in ev.quote


def test_currency_is_source_backed(gold, result):
    assert result.source.currency == "USD"
    ev = result.source.currency_evidence
    expected = gold["document"]["currency_basis"]
    assert ev.page == expected["pdf_page"]
    assert ev.printed_page == expected["printed_page"]
    assert ev.section == expected["section"]
    assert expected["quote"] in ev.quote


def test_extraction_is_raw_pending_and_replayable(result):
    assert len(result.claims) == 6
    assert len({claim.claim_id for claim in result.claims}) == 6
    for claim in result.claims:
        assert claim.claim_type == "raw_primitive"
        assert claim.agent == "DocumentAgent"
        assert claim.support_level == "single_source"
        assert claim.verification_status == "pending"
        assert claim.calculation_ref is None
        assert claim.run_iteration == 0 and claim.version == 1
        assert claim.timestamp.utcoffset() is not None
        assert Claim.model_validate_json(claim.model_dump_json()) == claim


def test_negative_sign_from_actual_source(pages):
    row = next(line.text for line in pages[150].lines if line.text.startswith("Interest expense "))
    assert normalize_number(row.split()[2]) == Decimal("-257")


@pytest.mark.parametrize(("raw", "expected"), [
    ("$ 1,234.50", "1234.50"), ("(1,234)", "-1234"),
    ("\u2212123", "-123"), ("+123", "123"), ("0", "0"),
])
def test_accounting_number_normalization(raw, expected):
    assert normalize_number(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["", "—", "�", "N/A", "NaN", "inf", "1,23", "123%", "(-123)"])
def test_missing_or_malformed_number_is_not_zero(raw):
    with pytest.raises(ValueError):
        normalize_number(raw)


def modify_page(page, prefix, transform):
    return replace(page, lines=tuple(
        replace(line, text=transform(line.text)) if line.text.startswith(prefix) else line
        for line in page.lines
    ))


@pytest.mark.parametrize(("prefix", "transform", "code"), [
    ("(In millions", lambda _: "Scale not stated", "ambiguous_scale"),
    ("Jan 28, 2024", lambda _: "Year columns missing", "ambiguous_period"),
    ("Jan 28, 2024", lambda s: s.replace("Jan 28, 2024", "Jan 29, 2023"), "ambiguous_period"),
    ("Jan 28, 2024", lambda s: s.replace("Jan 28", "Jan 32"), "invalid_period"),
    ("Year Ended", lambda _: "Period kind missing", "missing_period_kind"),
    ("Revenue ", lambda s: s.replace("60,922", ""), "column_mismatch"),
    ("Revenue ", lambda s: s.replace("60,922", "—"), "invalid_value"),
    ("Revenue ", lambda s: s.replace("60,922", "60,92"), "invalid_value"),
    ("Revenue ", lambda s: s.replace("60,922", "60,922%"), "invalid_value"),
])
def test_damaged_source_has_explicit_failure(pages, result, prefix, transform, code):
    changed = modify_page(pages[150], prefix, transform)
    claims, failures = extract_statement(changed, INCOME, result.source)
    assert code in {failure.code for failure in failures}
    if prefix == "Revenue ":
        assert not any(claim.metric == "revenue" for claim in claims)
        assert {claim.metric for claim in claims} == {"operating_income", "net_income"}
    else:
        assert not claims


def test_duplicate_row_is_not_silently_selected(pages, result):
    page = pages[150]
    revenue = next(line for line in page.lines if line.text.startswith("Revenue "))
    claims, failures = extract_statement(replace(page, lines=page.lines + (revenue,)), INCOME, result.source)
    assert any(f.code == "ambiguous_row" and f.metric == "revenue" for f in failures)
    assert not any(c.metric == "revenue" for c in claims)


def test_missing_balance_value_keeps_only_unaffected_fact(pages, result):
    page = pages[152]
    changed = replace(page, lines=tuple(line for line in page.lines
                                        if not line.text.startswith("Total current liabilities ")))
    claims, failures = extract_statement(changed, BALANCE, result.source)
    assert [c.metric for c in claims] == ["current_assets"]
    assert any(f.code == "missing_row" and f.metric == "current_liabilities" for f in failures)


def test_dollar_symbol_does_not_establish_currency(pages, result):
    source = SourceDocument(**result.source.model_dump(exclude={"currency", "currency_evidence"}))
    claims, failures = extract_statement(pages[150], INCOME, source)
    assert not claims
    assert [f.code for f in failures] == ["missing_currency"]


def test_printed_page_is_not_guessed_from_pdf_offset(pages, result):
    page = pages[150]
    changed = replace(page, lines=tuple(line for line in page.lines if line.text != "50"))
    claims, failures = extract_statement(changed, INCOME, result.source)
    assert len(claims)==4 and not failures
    assert all(c.evidence[0].page==150 and c.evidence[0].printed_page is None for c in claims)


@pytest.mark.parametrize("data", [b"not a PDF", b"%PDF-1.7\ntruncated"])
def test_corrupt_pdf_returns_failure(tmp_path, data):
    path = tmp_path / "bad.pdf"
    path.write_bytes(data)
    extracted = extract_financial_facts(path, **IDENTITY)
    assert not extracted.ok and not extracted.claims
    assert extracted.failures[0].code == "invalid_document"


def test_missing_document_returns_failure(tmp_path):
    extracted = extract_financial_facts(tmp_path / "absent.pdf", **IDENTITY)
    assert not extracted.ok and extracted.source is None
    assert extracted.failures[0].code == "unreadable_document"


@pytest.mark.parametrize("change", [
    {"evidence": ()}, {"confidence": "unverified"}, {"version": 0},
    {"currency": None}, {"scale": 0}, {"value": "not a number"},
    {"claim_type": "derived_metric"},
])
def test_evidence_contract_rejects_invalid_claims(result, change):
    data = result.claims[0].model_dump()
    data.update(change)
    with pytest.raises(ValidationError):
        Claim.model_validate(data)


def test_period_cannot_invent_invalid_interval():
    with pytest.raises(ValidationError):
        FiscalPeriod(kind="instant", start_date=date(2024, 1, 1),
                     end_date=date(2024, 1, 28), label="As of Jan 28, 2024")


def test_six_real_extractions_round_trip_through_shared_memory(result, gold):
    """Milestone integration: extraction output, not gold, is the store input."""
    assert result.ok, result.failures
    store = SharedMemory("nvidia-fy2024-integration")
    store.register_source(result.source)
    for claim in result.claims:
        assert store.append(claim).model_dump_json(round_trip=True) == claim.model_dump_json(round_trip=True)
    assert len(store.get_claims()) == 6
    assert store.get_source(result.source.source_id) == result.source
    assert store.get_source(result.source.source_id).currency_evidence == result.source.currency_evidence
    for expected in gold["values"]:
        original = next(c for c in result.claims if c.metric == expected["metric"]
                        and c.period.end_date.isoformat() == expected["period_end"])
        stored = store.resolve(store.reference(original.claim_id))
        assert stored.model_dump_json(round_trip=True) == original.model_dump_json(round_trip=True)
        assert stored.value == Decimal(expected["value"])
        assert stored.verification_status == "pending" and stored.support_level == "single_source"
        assert stored.evidence == original.evidence and stored.period == original.period
    assert store.get_claims(verification_status="verified") == []


def test_real_pdf_to_calculation_artifacts(result):
    """Independent exact-rational answers stay in tests, never engine inputs."""
    from decimal import localcontext
    from fractions import Fraction
    from engine.financial_engine import CalculationRequest, FinancialEngine

    assert result.ok, result.failures
    assert result.source.fiscal_year_weeks == ((2024, 52), (2023, 52), (2022, 52))
    context = result.source.fiscal_calendar_evidence
    assert context.page == 155 and context.printed_page == "55"
    assert "52- week years" in context.quote
    store = SharedMemory("nvidia-extraction-to-calculation")
    store.register_source(result.source)
    for claim in result.claims:
        store.append(claim)
        assert claim.accounting_scope == "consolidated"
    originals = {c.claim_id: c.model_dump_json(round_trip=True) for c in result.claims}
    claims = {(c.metric, c.period.end_date.year): c for c in store.get_claims()}
    cases = {
        "revenue_growth": ({"current_revenue": ("revenue", 2024), "previous_revenue": ("revenue", 2023)},
                           Fraction(3394800, 26974), "125.8545"),
        "operating_margin": ({"operating_income": ("operating_income", 2024), "revenue": ("revenue", 2024)},
                             Fraction(3297200, 60922), "54.1217"),
        "net_margin": ({"net_income": ("net_income", 2024), "revenue": ("revenue", 2024)},
                       Fraction(2976000, 60922), "48.8493"),
        "current_ratio": ({"current_assets": ("current_assets", 2024), "current_liabilities": ("current_liabilities", 2024)},
                          Fraction(44345, 10631), "4.1713"),
    }
    for operation, (roles, expected, display) in cases.items():
        request = CalculationRequest(operation=operation,
            inputs={role: store.reference(claims[key].claim_id) for role, key in roles.items()})
        outcome = FinancialEngine(store).calculate(request)
        assert outcome.status == "success", outcome.findings
        artifact = store.get_calculation(outcome.artifact.calculation_ref)
        with localcontext() as oracle_context:
            oracle_context.prec = 80
            oracle = Decimal(expected.numerator) / Decimal(expected.denominator)
            assert (artifact.output_value - oracle).copy_abs() < Decimal("1e-45")
        assert artifact.display_value == Decimal(display)
        assert artifact.support_level == "calculation_backed" and artifact.verification_status == "pending"
        assert store.get_calculation_freshness(artifact.calculation_ref) == "current"
        for snapshot in artifact.inputs:
            raw = store.resolve(snapshot.claim_ref)
            assert raw == claims[roles[snapshot.role]]
            assert snapshot.source_value == raw.value and snapshot.source_scale == 1_000_000
            assert snapshot.normalized_value == raw.base_value
            assert snapshot.source_period == raw.period
            assert raw.evidence[0].source_id == result.source.source_id
            assert snapshot.claim_ref.run_id == store.run_id and snapshot.claim_ref.version == 1
            if snapshot.period.kind == "duration":
                expected_start = date(2023, 1, 30) if snapshot.period.end_date.year == 2024 else date(2022, 1, 31)
                assert snapshot.period.start_date == expected_start
                assert snapshot.source_period.start_date is None  # raw claims were not rewritten
    assert len(store.get_calculations()) == 4
    assert {c.claim_id: c.model_dump_json(round_trip=True) for c in store.get_claims()} == originals
    assert store.get_claims(verification_status="verified") == []
