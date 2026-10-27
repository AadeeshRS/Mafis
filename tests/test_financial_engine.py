"""Deterministic arithmetic/storage unit fixtures; real-PDF integration is in test_ingest."""

from datetime import date, timedelta
from decimal import Decimal, Inexact, localcontext

import pytest

from engine.financial_engine import CalculationRequest, FinancialEngine
from memory.shared_memory import Claim, ClaimVersionRef, Evidence, FiscalPeriod, SharedMemory, SourceDocument


SPECS = {
    "revenue_growth": (("current_revenue", "revenue"), ("previous_revenue", "revenue")),
    "operating_margin": (("operating_income", "operating_income"), ("revenue", "revenue")),
    "net_margin": (("net_income", "net_income"), ("revenue", "revenue")),
    "current_ratio": (("current_assets", "current_assets"), ("current_liabilities", "current_liabilities")),
}


@pytest.fixture
def sample():
    def build(operation="net_margin", a="25", b="100", a_changes=None, b_changes=None):
        store = SharedMemory("arithmetic-unit-test")
        source = SourceDocument(title="Unit fixture (not an extracted report)", entity="Test Company",
            source_url="https://example.test/report.pdf", sha256="a" * 64)
        store.register_source(source)
        evidence = Evidence(source=source.title, source_id=source.source_id, source_url=source.source_url,
            source_type="annual_report", page=1, printed_page="1", section="Unit fixture",
            locator="unit-test", quote="Deterministic input fixture")
        current = FiscalPeriod(kind="duration", start_date=date(2023, 1, 30),
                              end_date=date(2024, 1, 28), label="Year ended Jan 28, 2024")
        previous = FiscalPeriod(kind="duration", start_date=date(2022, 1, 31),
                               end_date=date(2023, 1, 29), label="Year ended Jan 29, 2023")
        if operation == "current_ratio":
            current = FiscalPeriod(kind="instant", end_date=date(2024, 1, 28), label="As of Jan 28, 2024")
        claims = []
        for index, ((role, metric), value, changes) in enumerate(zip(SPECS[operation], (a, b), (a_changes, b_changes))):
            fields = dict(claim_id=role, agent="DocumentAgent", claim_type="raw_primitive",
                metric=metric, entity=source.entity, accounting_scope="consolidated", claim="Unit input",
                value=None if value is None else Decimal(value), unit="currency", currency="USD", scale=1,
                period=previous if operation == "revenue_growth" and index == 1 else current,
                evidence=(evidence,), support_level="single_source")
            fields.update(changes or {})
            claims.append(store.append(Claim(**fields)))
        request = CalculationRequest(operation=operation,
            inputs={role: store.reference(claim.claim_id) for (role, _), claim in zip(SPECS[operation], claims)})
        return store, FinancialEngine(store), request, claims
    return build


@pytest.mark.parametrize(("operation", "a", "b", "expected", "unit"), [
    ("revenue_growth", "150", "100", "50", "percent"),
    ("operating_margin", "20", "100", "20", "percent"),
    ("net_margin", "25", "100", "25", "percent"),
    ("current_ratio", "250", "100", "2.5", "ratio"),
])
def test_approved_operations(sample, operation, a, b, expected, unit):
    store, engine, request, claims = sample(operation, a, b)
    originals = [c.model_dump_json(round_trip=True) for c in claims]
    result = engine.calculate(request)
    assert result.status == "success", result.findings
    artifact = result.artifact
    assert artifact.output_value == Decimal(expected) and artifact.output_unit == unit
    assert artifact.display_value == Decimal(expected).quantize(Decimal("0.0001"))
    assert artifact.verification_status == "pending" and artifact.support_level == "calculation_backed"
    assert store.get_calculation(artifact.calculation_ref) == artifact
    assert engine.validate_outputs(artifact)
    assert [store.get_current(c.claim_id).model_dump_json(round_trip=True) for c in claims] == originals


def test_precision_display_and_ambient_context_independence(sample):
    store, engine, request, _ = sample(a="1", b="3")
    first = engine.calculate(request).artifact
    with localcontext() as context:
        context.prec = 3
        context.rounding = "ROUND_DOWN"
        context.traps[Inexact] = True
        second = engine.calculate(request).artifact
    assert first.output_value == second.output_value == Decimal("33." + "3" * 48)
    assert first.display_value == second.display_value == Decimal("33.3333")
    assert first.calculation_ref != second.calculation_ref
    assert len(store.get_calculations()) == 2


def test_display_rounds_half_up_without_changing_internal_value(sample):
    _, engine, request, _ = sample(a="1.23445", b="100")
    artifact = engine.calculate(request).artifact
    assert artifact.output_value == Decimal("1.23445")
    assert artifact.display_value == Decimal("1.2345")


@pytest.mark.parametrize(("a", "b"), [("1e999999", "1"), ("1e-999999", "1e100")])
def test_numeric_context_limits_reject_without_storing_a_silent_zero(sample, a, b):
    store, engine, request, _ = sample(a=a, b=b)
    result = engine.calculate(request)
    assert result.status == "rejected" and result.artifact is None
    assert result.findings[0].code == "numeric_error"
    assert store.get_calculations() == []


def test_mixed_scales_normalize_exactly(sample):
    _, engine, request, _ = sample("operating_margin", a="20", b="100000",
        a_changes={"scale": 1_000_000}, b_changes={"scale": 1000})
    artifact = engine.calculate(request).artifact
    assert artifact.output_value == Decimal("20")
    assert artifact.inputs[0].source_value == Decimal("20")
    assert artifact.inputs[0].normalized_value == Decimal("20000000")
    assert artifact.inputs[1].normalized_value == Decimal("100000000")


@pytest.mark.parametrize(("operation", "a", "expected"), [
    ("net_margin", "-25", "-25"), ("operating_margin", "-25", "-25"),
    ("current_ratio", "0", "0"), ("net_margin", "0", "0"),
    ("revenue_growth", "0", "-100"),
])
def test_negative_income_and_legitimate_zero_numerators(sample, operation, a, expected):
    _, engine, request, _ = sample(operation, a=a)
    result = engine.calculate(request)
    assert result.status == "success"
    assert result.artifact.output_value == Decimal(expected)


def test_extreme_growth_is_retained_with_warning(sample):
    _, engine, request, _ = sample("revenue_growth", a="440", b="100")
    result = engine.calculate(request)
    assert result.status == "success" and result.artifact.output_value == Decimal("340")
    assert "extreme_result" in {f.code for f in result.findings}


@pytest.mark.parametrize("operation", SPECS)
def test_zero_denominator_is_structured_rejection_without_storage(sample, operation):
    store, engine, request, _ = sample(operation, b="0")
    result = engine.calculate(request)
    assert result.status == "rejected" and result.artifact is None
    assert result.findings[0].code == "zero_denominator"
    assert store.get_calculations() == []


@pytest.mark.parametrize(("operation", "code"), [
    ("revenue_growth", "negative_prior_revenue"), ("current_ratio", "negative_denominator"),
    ("net_margin", "negative_denominator"),
])
def test_negative_denominator_policy(sample, operation, code):
    _, engine, request, _ = sample(operation, b="-1")
    assert engine.calculate(request).findings[0].code == code


@pytest.mark.parametrize(("changes", "code"), [
    ({"value": None}, "missing_value"),
    ({"currency": "EUR"}, "currency_mismatch"),
    ({"unit": "shares"}, "unit_mismatch"),
    ({"scale": 3}, "unsupported_scale"),
    ({"entity": "Other Company"}, "entity_mismatch"),
    ({"accounting_scope": "standalone"}, "scope_mismatch"),
    ({"accounting_scope": None}, "missing_entity_scope"),
    ({"metric": "current_assets"}, "wrong_input_metric"),
    ({"verification_status": "flagged"}, "unusable_input"),
    ({"period": FiscalPeriod(kind="instant", end_date=date(2024, 1, 28), label="As of")}, "period_kind_mismatch"),
    ({"period": FiscalPeriod(kind="duration", start_date=date(2023, 1, 1), end_date=date(2024, 1, 28), label="Different interval")}, "incompatible_periods"),
    ({"period": FiscalPeriod(kind="duration", end_date=date(2024, 1, 28), label="Unknown duration")}, "missing_duration_context"),
])
def test_input_rejections(sample, changes, code):
    store, engine, request, _ = sample(a_changes=changes)
    result = engine.calculate(request)
    assert result.status == "rejected" and result.findings[0].code == code
    assert store.get_calculations() == []


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_resolver_input_is_rejected(sample, monkeypatch, value):
    store, engine, request, claims = sample()
    resolve = store.resolve
    forged = claims[0].model_copy(update={"value": Decimal(value)})
    monkeypatch.setattr(store, "resolve", lambda ref: forged if ref.claim_id == claims[0].claim_id else resolve(ref))
    assert engine.calculate(request).findings[0].code == "invalid_number"
    assert store.get_calculations() == []


def test_balance_sheet_dates_must_match(sample):
    _, engine, request, _ = sample("current_ratio", a_changes={
        "period": FiscalPeriod(kind="instant", end_date=date(2024, 1, 27), label="Other day")})
    assert engine.calculate(request).findings[0].code == "incompatible_periods"


def test_growth_periods_must_be_adjacent_and_annual(sample):
    _, engine, request, _ = sample("revenue_growth", a_changes={
        "period": FiscalPeriod(kind="duration", start_date=date(2023, 2, 1), end_date=date(2024, 1, 28), label="Gap")})
    assert engine.calculate(request).findings[0].code == "incompatible_periods"


def test_53_week_growth_warns_without_annualizing(sample):
    _, engine, request, _ = sample("revenue_growth", a="150", a_changes={
        "period": FiscalPeriod(kind="duration", start_date=date(2023, 1, 30), end_date=date(2024, 2, 4), label="53-week year")})
    result = engine.calculate(request)
    assert result.status == "success" and result.artifact.output_value == Decimal("50")
    assert "unequal_year_lengths" in {f.code for f in result.findings}


@pytest.mark.parametrize(("kind", "code"), [
    ("missing_role", "missing_input"), ("extra_role", "unexpected_input"),
    ("duplicate", "duplicate_input"), ("cross_run", "cross_run_reference"),
    ("missing_claim", "missing_claim"), ("missing_version", "missing_claim"),
    ("unsupported", "unsupported_operation"), ("raw_value", "invalid_request"),
])
def test_invalid_requests_and_references(sample, kind, code):
    store, engine, request, _ = sample()
    fields = request.model_dump(round_trip=True)
    if kind == "missing_role": del fields["inputs"]["revenue"]
    if kind == "extra_role": fields["inputs"]["another"] = fields["inputs"]["revenue"]
    if kind == "duplicate": fields["inputs"]["net_income"] = fields["inputs"]["revenue"]
    if kind == "cross_run": fields["inputs"]["net_income"]["run_id"] = "other-run"
    if kind == "missing_claim": fields["inputs"]["net_income"]["claim_id"] = "missing"
    if kind == "missing_version": fields["inputs"]["net_income"]["version"] = 99
    if kind == "unsupported": fields["operation"] = "__import__('os').system('not executed')"
    if kind == "raw_value": fields["value"] = 999
    result = engine.calculate(fields)
    assert result.status == "rejected" and result.findings[0].code == code
    assert store.get_calculations() == []


def test_artifact_history_is_immutable_and_pins_superseded_inputs(sample):
    store, engine, request, claims = sample()
    artifact = engine.calculate(request).artifact
    original = artifact.model_dump_json(round_trip=True)
    assert store.get_calculation_freshness(artifact.calculation_ref) == "current"
    fields = claims[0].model_dump(round_trip=True)
    fields.update(version=2, value=Decimal("30"))
    store.append(Claim.model_validate(fields))
    assert store.get_calculation_freshness(artifact.calculation_ref) == "superseded"
    assert engine.validate_outputs(artifact)  # historical replay remains valid
    assert store.get_calculation(artifact.calculation_ref).model_dump_json(round_trip=True) == original
    assert artifact.inputs[0].claim_ref.version == 1
    assert store.resolve(artifact.inputs[0].claim_ref).value == Decimal("25")
    artifact.inputs[0].__dict__["source_value"] = Decimal("999")
    artifact.__dict__["output_value"] = Decimal("999")
    assert store.get_calculation(artifact.calculation_ref).model_dump_json(round_trip=True) == original
    fetched = store.get_calculation(artifact.calculation_ref)
    fetched.inputs[0].claim_ref.__dict__["version"] = 999
    assert store.get_calculation(artifact.calculation_ref).inputs[0].claim_ref.version == 1


@pytest.mark.parametrize("kind", ["duplicate", "output", "input_value", "missing_reference", "cross_run", "formula"])
def test_bad_artifact_appends_cannot_overwrite_history(sample, kind):
    store, engine, request, _ = sample()
    original = engine.calculate(request).artifact
    fields = original.model_dump(round_trip=True)
    if kind != "duplicate": fields["calculation_ref"] = "new-calculation"
    if kind == "output": fields["output_value"] = Decimal("999")
    if kind == "formula": fields["formula"] = "arbitrary expression"
    if kind == "input_value": fields["inputs"][0]["normalized_value"] = Decimal("999")
    if kind == "missing_reference": fields["inputs"][0]["claim_ref"]["version"] = 99
    if kind == "cross_run": fields["run_id"] = "other-run"
    with pytest.raises(ValueError):
        store.append_calculation(type(original).model_validate(fields))
    assert store.get_calculations() == [original]


def derived(artifact, **changes):
    fields = dict(claim_id="derived:" + artifact.calculation_ref, agent="FinancialAgent",
        claim_type="derived_metric", entity=artifact.entity, accounting_scope=artifact.accounting_scope,
        metric=artifact.operation, value=artifact.output_value, unit=artifact.output_unit,
        period=artifact.output_period, claim="Calculation result (no agent executed)",
        calculation_ref=artifact.calculation_ref, support_level="calculation_backed")
    fields.update(changes)
    return Claim(**fields)


def test_derived_claim_references_valid_artifact_without_promotion(sample):
    store, engine, request, _ = sample()
    artifact = engine.calculate(request).artifact
    claim = store.append(derived(artifact))
    assert claim.value == artifact.output_value and claim.verification_status == "pending"
    assert claim.support_level == "calculation_backed"
    assert store.get_current(claim.claim_id) == claim


@pytest.mark.parametrize("changes", [
    {"calculation_ref": "missing"}, {"value": Decimal("999")}, {"unit": "ratio"},
    {"scale": 1000}, {"metric": "current_ratio"}, {"support_level": "single_source"},
])
def test_invalid_derived_claim_references_are_rejected(sample, changes):
    store, engine, request, _ = sample()
    artifact = engine.calculate(request).artifact
    with pytest.raises(ValueError):
        store.append(derived(artifact, **changes))
    assert len(store.get_claims()) == 2


def test_validation_helpers_do_not_store_or_promote(sample):
    store, engine, request, _ = sample()
    findings = engine.validate_inputs(request)
    assert all(f.severity != "error" for f in findings)
    assert store.get_calculations() == []
    assert store.get_claims(verification_status="verified") == []
