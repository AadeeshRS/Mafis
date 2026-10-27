"""Approved deterministic operations over exact SharedMemory claim versions.

No LLM, arbitrary expressions, forecasts, or agent behavior. Arithmetic uses a
private 50-digit Decimal context; display rounding happens only at the end.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Context, Decimal, DecimalException, DivisionByZero, InvalidOperation, Overflow, Underflow, localcontext
from typing import Any, Literal, get_args
from uuid import uuid4

from pydantic import ValidationError

from memory.shared_memory import (
    CalculationArtifact, CalculationFinding, CalculationInput, CalculationOperation,
    Claim, ClaimVersionRef, EvidenceModel, FiscalPeriod, SharedMemory,
)


_OPERATIONS = {
    "revenue_growth": (("current_revenue", "revenue"), ("previous_revenue", "revenue")),
    "operating_margin": (("operating_income", "operating_income"), ("revenue", "revenue")),
    "net_margin": (("net_income", "net_income"), ("revenue", "revenue")),
    "current_ratio": (("current_assets", "current_assets"), ("current_liabilities", "current_liabilities")),
}
_FORMULAS = {
    "revenue_growth": "((current_revenue - previous_revenue) / previous_revenue) * 100",
    "operating_margin": "(operating_income / revenue) * 100",
    "net_margin": "(net_income / revenue) * 100",
    "current_ratio": "current_assets / current_liabilities",
}


def _context() -> Context:
    return Context(prec=50, rounding="ROUND_HALF_EVEN", Emin=-999999, Emax=999999,
                   traps=[InvalidOperation, DivisionByZero, Overflow, Underflow])


class CalculationRequest(EvidenceModel):
    operation: CalculationOperation
    inputs: dict[str, ClaimVersionRef]


class CalculationResult(EvidenceModel):
    status: Literal["success", "rejected"]
    artifact: CalculationArtifact | None = None
    findings: tuple[CalculationFinding, ...] = ()


class _Rejected(ValueError):
    def __init__(self, code: str, message: str, role: str | None = None):
        self.finding = CalculationFinding(code=code, message=message, input_role=role, severity="error")
        super().__init__(message)


class FinancialEngine:
    def __init__(self, memory: SharedMemory) -> None:
        self.memory = memory

    @staticmethod
    def operation_inputs(operation: CalculationOperation) -> tuple[tuple[str, str], ...]:
        """Expose approved role/metric requirements without duplicating formulas."""
        if operation not in _OPERATIONS:
            raise ValueError("Unsupported calculation operation")
        return _OPERATIONS[operation]

    @staticmethod
    def _request(request: CalculationRequest | dict[str, Any]) -> CalculationRequest:
        if isinstance(request, CalculationRequest):
            request = request.model_dump(round_trip=True)
        if not isinstance(request, dict):
            raise _Rejected("invalid_request", "Expected a CalculationRequest or mapping")
        if request.get("operation") not in get_args(CalculationOperation):
            raise _Rejected("unsupported_operation", "Operation is outside the approved MVP allowlist")
        try:
            return CalculationRequest.model_validate(request)
        except ValidationError as exc:
            raise _Rejected("invalid_request", str(exc)) from exc

    def _period(self, claim: Claim, role: str) -> FiscalPeriod:
        period = claim.period
        if period is None:
            raise _Rejected("missing_period", "Input has no reporting period", role)
        if period.kind == "instant" or period.start_date is not None:
            return period
        # Only an explicit annual source policy can supply a missing year start.
        lengths = set()
        if period.label.casefold().startswith("year ended "):
            for evidence in claim.evidence:
                source = self.memory.get_source(evidence.source_id)
                if period.end_date in source.annual_period_ends:
                    prior = [d for d in source.annual_period_ends if d < period.end_date]
                    if prior:
                        days = (period.end_date - max(prior)).days
                        if 350 <= days <= 371:
                            lengths.add(days)
                weeks = dict(source.fiscal_year_weeks).get(period.end_date.year)
                if weeks is not None:
                    lengths.add(weeks * 7)
        if len(lengths) != 1:
            raise _Rejected("missing_duration_context", "A duration needs a stated start or unambiguous fiscal-year policy", role)
        start = period.end_date - timedelta(days=lengths.pop() - 1)
        return FiscalPeriod(kind="duration", start_date=start, end_date=period.end_date, label=period.label)

    def _input(self, role: str, metric: str, reference: ClaimVersionRef) -> tuple[CalculationInput, Claim]:
        if reference.run_id != self.memory.run_id:
            raise _Rejected("cross_run_reference", "Input belongs to another run", role)
        try:
            claim = self.memory.resolve(reference)
        except KeyError as exc:
            raise _Rejected("missing_claim", "Claim or exact claim version is unavailable", role) from exc
        if claim.claim_type != "raw_primitive" or claim.metric != metric:
            raise _Rejected("wrong_input_metric", f"Expected source primitive {metric}", role)
        if claim.value is None:
            raise _Rejected("missing_value", "Missing input is distinct from zero", role)
        if not isinstance(claim.value, Decimal) or not claim.value.is_finite():
            raise _Rejected("invalid_number", "Input must be a finite Decimal", role)
        if claim.verification_status in ("unsupported", "flagged", "unresolved"):
            raise _Rejected("unusable_input", "Input has an unresolved evidence problem", role)
        if claim.unit != "currency":
            raise _Rejected("unit_mismatch", "These operations require monetary primitives", role)
        if claim.currency is None:
            raise _Rejected("missing_currency", "Currency is not established", role)
        if claim.entity is None or claim.accounting_scope is None:
            raise _Rejected("missing_entity_scope", "Entity and consolidation scope must be explicit", role)
        for evidence in claim.evidence:
            source = self.memory.get_source(evidence.source_id)
            if source.entity != claim.entity:
                raise _Rejected("entity_mismatch", "Claim entity differs from its source", role)
            if source.currency is not None and source.currency != claim.currency:
                raise _Rejected("currency_mismatch", "Claim currency differs from its source", role)
        scale = claim.scale
        power = len(str(scale)) - 1
        if scale != 10 ** power:
            raise _Rejected("unsupported_scale", "Source scale must be a positive power of ten", role)
        sign, digits, exponent = claim.value.as_tuple()
        normalized = Decimal((sign, digits, exponent + power))  # exact, no context rounding
        return CalculationInput(
            role=role, claim_ref=reference, source_value=claim.value, source_scale=scale,
            source_unit=claim.unit, normalized_value=normalized, currency=claim.currency,
            entity=claim.entity, accounting_scope=claim.accounting_scope,
            source_period=claim.period, period=self._period(claim, role),
        ), claim

    def _prepare(self, request: CalculationRequest) -> tuple[tuple[CalculationInput, ...], tuple[CalculationFinding, ...]]:
        spec = _OPERATIONS[request.operation]
        roles = {role for role, _ in spec}
        if roles - request.inputs.keys():
            raise _Rejected("missing_input", "Missing roles: " + ", ".join(sorted(roles - request.inputs.keys())))
        if request.inputs.keys() - roles:
            raise _Rejected("unexpected_input", "Unexpected or conflicting input roles")
        if len({(ref.run_id, ref.claim_id) for ref in request.inputs.values()}) != 2:
            raise _Rejected("duplicate_input", "Input roles require distinct logical source claims")
        resolved = [self._input(role, metric, request.inputs[role]) for role, metric in spec]
        inputs = tuple(item for item, _ in resolved)
        a, b = inputs
        if a.entity != b.entity:
            raise _Rejected("entity_mismatch", "Inputs belong to different accounting entities")
        if a.accounting_scope != b.accounting_scope:
            raise _Rejected("scope_mismatch", "Consolidated and standalone inputs cannot be mixed")
        if a.currency != b.currency:
            raise _Rejected("currency_mismatch", "Currency conversion is not implemented")
        expected_kind = "instant" if request.operation == "current_ratio" else "duration"
        if any(i.period.kind != expected_kind for i in inputs):
            raise _Rejected("period_kind_mismatch", f"Expected {expected_kind} facts")
        findings = []
        if request.operation == "revenue_growth":
            current, previous = a.period, b.period
            days = [(i.period.end_date - i.period.start_date).days + 1 for i in inputs]
            if (current.start_date != previous.end_date + timedelta(days=1)
                    or not all(350 <= length <= 371 for length in days) or abs(days[0] - days[1]) > 7):
                raise _Rejected("incompatible_periods", "Growth requires adjacent comparable annual fiscal periods")
            if days[0] != days[1]:
                findings.append(CalculationFinding(code="unequal_year_lengths", severity="warning",
                    message="Reported growth uses unequal fiscal-year lengths without annualization"))
        elif ((a.period.start_date, a.period.end_date) != (b.period.start_date, b.period.end_date)):
            raise _Rejected("incompatible_periods", "Inputs must represent the same reporting interval/date")
        if b.normalized_value == 0:
            raise _Rejected("zero_denominator", "The denominator is zero", b.role)
        if b.normalized_value < 0:
            code = "negative_prior_revenue" if request.operation == "revenue_growth" else "negative_denominator"
            raise _Rejected(code, "Negative prior revenue, revenue denominators, or liabilities are not interpreted by this MVP", b.role)
        if a.normalized_value < 0:
            findings.append(CalculationFinding(code="negative_numerator", severity="warning",
                message="Negative source outcome retained; inspect its financial context", input_role=a.role))
        if any(claim.verification_status != "verified" for _, claim in resolved):
            findings.append(CalculationFinding(code="unverified_inputs", severity="warning",
                message="Arithmetic does not independently verify the underlying source data"))
        return inputs, tuple(findings)

    def _evaluate(self, request: CalculationRequest) -> CalculationArtifact:
        inputs, findings = self._prepare(request)
        a, b = (i.normalized_value for i in inputs)
        with localcontext(_context()):
            if request.operation == "revenue_growth":
                value = ((a - b) / b) * 100
            elif request.operation in ("operating_margin", "net_margin"):
                value = (a / b) * 100
            else:
                value = a / b
            if not value.is_finite():
                raise _Rejected("nonfinite_output", "The output is not finite")
            display = value.quantize(Decimal("0.0001"), rounding="ROUND_HALF_UP")
        limit = Decimal(200) if request.operation == "revenue_growth" else Decimal(100)
        if request.operation != "current_ratio" and value.copy_abs() > limit:
            findings += (CalculationFinding(code="extreme_result", severity="warning",
                message="Unusual magnitude retained as a valid result; investigate source context"),)
        return CalculationArtifact(
            calculation_ref="calc:" + str(uuid4()), run_id=self.memory.run_id,
            operation=request.operation, formula=_FORMULAS[request.operation], inputs=inputs,
            output_value=value, output_unit="ratio" if request.operation == "current_ratio" else "percent",
            output_period=inputs[0].period, entity=inputs[0].entity,
            accounting_scope=inputs[0].accounting_scope, display_value=display, findings=findings,
        )

    def calculate(self, request: CalculationRequest | dict[str, Any]) -> CalculationResult:
        """Return a stored success artifact or a structured, non-mutating rejection."""
        try:
            artifact = self._evaluate(self._request(request))
            stored = self.memory.append_calculation(artifact)
            return CalculationResult(status="success", artifact=stored, findings=stored.findings)
        except _Rejected as exc:
            return CalculationResult(status="rejected", findings=(exc.finding,))
        except DecimalException as exc:
            finding = CalculationFinding(code="numeric_error", message=str(exc), severity="error")
        except (ValidationError, ValueError, KeyError, OverflowError) as exc:
            finding = CalculationFinding(code="invalid_input_or_artifact", message=str(exc), severity="error")
        return CalculationResult(status="rejected", findings=(finding,))

    def validate_inputs(self, request: CalculationRequest | dict[str, Any]) -> tuple[CalculationFinding, ...]:
        """Diagnostics only: warnings are valid; error findings mean rejection."""
        try:
            return self._prepare(self._request(request))[1]
        except _Rejected as exc:
            return (exc.finding,)
        except (ValidationError, ValueError, KeyError, OverflowError) as exc:
            return (CalculationFinding(code="invalid_input", severity="error", message=str(exc)),)

    def validate_artifact(self, artifact: CalculationArtifact) -> None:
        """Replay without writes; reject altered inputs, formulas, results, or policy."""
        try:
            accepted = CalculationArtifact.model_validate(artifact.model_dump(round_trip=True))
            if accepted.run_id != self.memory.run_id:
                raise ValueError("Calculation belongs to another run")
            request = CalculationRequest(operation=accepted.operation,
                inputs={item.role: item.claim_ref for item in accepted.inputs})
            expected = self._evaluate(request)
            omit = {"calculation_ref", "timestamp"}
            if accepted.model_dump(exclude=omit) != expected.model_dump(exclude=omit):
                raise ValueError("Calculation artifact differs from deterministic replay")
        except (_Rejected, DecimalException) as exc:
            raise ValueError(f"Calculation cannot be replayed: {exc}") from exc

    def validate_outputs(self, artifact: CalculationArtifact) -> bool:
        try:
            self.validate_artifact(artifact)
            return True
        except (ValidationError, ValueError, KeyError, OverflowError):
            return False
