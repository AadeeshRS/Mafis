"""Actual publisher PDFs and manually inspected gold; no model or network calls."""

from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from dataclasses import replace

import pdfplumber
import pytest

from engine.financial_engine import CalculationRequest, FinancialEngine
from memory.shared_memory import SharedMemory
from rag.ingest import extract_financial_facts, extract_alternate_statement, StatementPage, TextLine


@pytest.fixture(scope="module", params=("apple_2024", "coca_cola_2024"))
def extracted(request):
    root = Path("tests/fixtures") / request.param
    gold = json.loads((root / "annotations.json").read_text())
    identity = {k:gold["document"][k] for k in ("source_url","title","entity")}
    result = extract_financial_facts(root / "annual_report.pdf", **identity)
    return result, gold, root


def test_source_identity_and_layouts(extracted):
    result, gold, root = extracted
    assert result.ok, result.failures
    data = (root / "annual_report.pdf").read_bytes()
    assert result.source.sha256 == sha256(data).hexdigest() == gold["document"]["sha256"]
    assert len(data) == gold["document"]["byte_length"]
    assert result.source.currency == "USD" and result.source.currency_evidence
    assert len(result.source.annual_period_ends) == 3 and result.source.annual_period_evidence


@pytest.mark.parametrize("index", range(6))
def test_manually_checked_value_and_locator(extracted, index):
    result, gold, _ = extracted
    expected = gold["values"][index]
    claim = next(c for c in result.claims if c.metric == expected["metric"] and str(c.period.end_date) == expected["period_end"])
    assert claim.value == Decimal(expected["value"])
    assert claim.scale == gold["scale"] and claim.currency == gold["currency"] and claim.unit == gold["unit"]
    evidence = claim.evidence[0]
    assert (evidence.page,evidence.printed_page,evidence.row_label) == (expected["pdf_page"],expected["printed_page"],expected["row"])
    assert evidence.bbox and evidence.column_header and evidence.period_header and evidence.raw_value
    assert claim.accounting_scope == "consolidated" and claim.verification_status == "pending"
    assert claim.period.start_date is None


@pytest.mark.parametrize("operation", ("revenue_growth","operating_margin","net_margin","current_ratio"))
def test_actual_extraction_to_calculation(extracted, operation):
    result, gold, _ = extracted
    store = SharedMemory()
    store.register_source(result.source)
    for claim in result.claims: store.append(claim)
    inputs = {}
    for role,metric in FinancialEngine.operation_inputs(operation):
        matches = sorted((c for c in result.claims if c.metric == metric),key=lambda c:c.period.end_date,reverse=True)
        claim = matches[1] if role == "previous_revenue" else matches[0]
        inputs[role] = store.reference(claim.claim_id)
    outcome = FinancialEngine(store).calculate(CalculationRequest(operation=operation,inputs=inputs))
    assert outcome.status == "success", outcome.findings
    artifact = outcome.artifact
    current,prior,op,net,assets,liabilities = [Fraction(v["value"]) for v in gold["values"]]
    oracle = {"revenue_growth":(current-prior)/prior*100,"operating_margin":op/current*100,
              "net_margin":net/current*100,"current_ratio":assets/liabilities}[operation]
    with localcontext() as ctx:
        ctx.prec=80
        value = Decimal(oracle.numerator)/Decimal(oracle.denominator)
        assert (artifact.output_value-value).copy_abs() < Decimal("1e-45")
    for snapshot in artifact.inputs:
        if snapshot.period.kind == "duration":
            expected_start = gold["prior_start"] if snapshot.role == "previous_revenue" else gold["current_start"]
            assert snapshot.period.start_date == date.fromisoformat(expected_start)
            assert snapshot.source_period.start_date is None
    assert artifact.verification_status == "pending" and store.get_calculation(artifact.calculation_ref) == artifact


@pytest.fixture(scope="module")
def alternate_page(extracted):
    result, gold, root = extracted
    number = gold["values"][0]["pdf_page"]
    with pdfplumber.open(root / "annual_report.pdf") as pdf:
        page = pdf.pages[number - 1]
        lines = tuple(TextLine(x["text"], (x["x0"], x["top"], x["x1"], x["bottom"]))
                      for x in page.extract_text_lines())
        return StatementPage(number, page.height, lines), result.source


@pytest.mark.parametrize("defect", ("currency", "header", "duplicate_row", "missing_row", "heading", "invalid_date"))
def test_alternate_layout_fails_explicitly(alternate_page, defect):
    page, source = alternate_page
    lines = list(page.lines)
    revenue = next(x for x in lines if x.text.startswith(("Total net sales ", "Net Operating Revenues ")))
    if defect == "currency":
        source = source.model_copy(update={"currency": None, "currency_evidence": None})
    elif defect == "header":
        lines = [x for x in lines if "2024" not in x.text]
    elif defect == "invalid_date":
        lines = [replace(x, text=x.text.replace("September 28,", "September 99,").replace("December 31,", "December 99,")) for x in lines]
    elif defect == "duplicate_row":
        lines.append(revenue)
    elif defect == "missing_row":
        lines.remove(revenue)
    elif defect == "heading":
        lines = [x for x in lines if not x.text.casefold().startswith("consolidated statements of")]
    claims, failures, _ = extract_alternate_statement(replace(page, lines=tuple(lines)), "income", source)
    assert failures
    assert not any(c.metric == "revenue" for c in claims)


@pytest.mark.parametrize("raw, expected", (("(9,992)", "-9992"), ("\u22129,992", "-9992"), ("\u2014", None)))
def test_alternate_row_signs_and_missing_values(alternate_page, raw, expected):
    page, source = alternate_page
    row = next(x for x in page.lines if x.text.casefold().startswith("operating income "))
    label, numbers = row.text[:len("Operating income")], row.text[len("Operating income"):].replace("$", "").split()
    numbers[0] = raw
    lines = tuple(replace(x, text=label + " " + " ".join(numbers)) if x == row else x for x in page.lines)
    claims, failures, _ = extract_alternate_statement(replace(page, lines=lines), "income", source)
    matches = [c for c in claims if c.metric == "operating_income"]
    if expected is None:
        assert not matches and any(f.metric == "operating_income" for f in failures)
    else:
        assert not failures and matches[0].value == Decimal(expected)
