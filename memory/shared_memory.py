"""v1.1 evidence contracts and a per-run, append-only in-memory store.

Numeric ``value`` is in the source's displayed units. ``scale`` is the
multiplier to base units (e.g. 1_000_000 for an amount printed in millions).
Unit normalization is distinct from a derived financial calculation.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Literal, get_args
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

AgentName = Literal[
    "DocumentAgent",
    "FinancialAgent",
    "MarketAgent",
    "RiskAgent",
    "Verification",
    "Critic",
    "Bull",
    "Bear",
]

SupportLevel = Literal[
    "multiple_sources", "single_source", "calculation_backed", "unsupported",
]

VerificationStatus = Literal["verified", "unsupported", "flagged", "pending", "unresolved"]


class EvidenceModel(BaseModel):
    """Reject unknown fields (including the obsolete confidence field)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FiscalPeriod(EvidenceModel):
    """An instant or a duration ending on a source-stated date.

    A missing start date stays unknown; a year-end heading does not imply
    January 1, especially for 52/53-week fiscal calendars.
    """

    kind: Literal["instant", "duration"]
    end_date: date
    start_date: date | None = None
    label: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_interval(self) -> FiscalPeriod:
        if self.kind == "instant" and self.start_date is not None:
            raise ValueError("An instant cannot have a start date")
        if self.start_date is not None and self.start_date > self.end_date:
            raise ValueError("Period starts after it ends")
        return self


class Evidence(EvidenceModel):
    """Source location; page is a ONE-BASED PDF index, not a printed label.

    bbox uses PDF points from the top-left: (x0, top, x1, bottom).
    For table values it bounds the row; column_header fixes the selected cell.
    """

    source: str = Field(min_length=1)
    source_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_url: HttpUrl
    source_type: Literal["annual_report", "filing", "news", "market_data", "other"]
    page: int | None = Field(default=None, ge=1)
    printed_page: str | None = None
    section: str | None = Field(default=None, description="Section name if known")
    year: int | None = Field(default=None, description="Fiscal year if applicable")
    locator: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    bbox: tuple[float, float, float, float] | None = None
    row_label: str | None = None
    column_header: str | None = None
    raw_value: str | None = None
    scale_header: str | None = None
    period_header: str | None = None

    @model_validator(mode="after")
    def valid_bbox(self) -> Evidence:
        if self.bbox is not None:
            x0, top, x1, bottom = self.bbox
            if not all(Decimal(str(v)).is_finite() for v in self.bbox):
                raise ValueError("Non-finite source coordinates")
            if not (0 <= x0 < x1 and 0 <= top < bottom):
                raise ValueError("Invalid source bounding box")
        return self


class SourceDocument(EvidenceModel):
    """Identity and document-level currency evidence, never answer annotations."""

    title: str = Field(min_length=1)
    entity: str = Field(min_length=1)
    source_url: HttpUrl
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: Literal["annual_report", "filing", "news", "market_data", "other"] = "annual_report"
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    as_of_date: date | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    currency_evidence: Evidence | None = None
    fiscal_year_weeks: tuple[tuple[int, Literal[52, 53]], ...] = ()
    fiscal_calendar_evidence: Evidence | None = None
    annual_period_ends: tuple[date, ...] = ()
    annual_period_evidence: Evidence | None = None

    @property
    def source_id(self) -> str:
        return f"sha256:{self.sha256}"

    @model_validator(mode="after")
    def currency_has_context(self) -> SourceDocument:
        for stamp in (self.published_at, self.retrieved_at):
            if stamp is not None and stamp.utcoffset() is None:
                raise ValueError("Source timestamps must be timezone aware")
        if self.published_at is not None and self.retrieved_at is not None and self.published_at > self.retrieved_at:
            raise ValueError("Source publication cannot follow retrieval")
        if (self.currency is None) != (self.currency_evidence is None):
            raise ValueError("Currency and its source context must be supplied together")
        if self.currency_evidence is not None and self.currency_evidence.source_id != self.source_id:
            raise ValueError("Currency context belongs to another document")
        if bool(self.fiscal_year_weeks) != (self.fiscal_calendar_evidence is not None):
            raise ValueError("Fiscal year lengths require their source context")
        if len({year for year, _ in self.fiscal_year_weeks}) != len(self.fiscal_year_weeks):
            raise ValueError("Duplicate fiscal year lengths")
        if self.fiscal_calendar_evidence is not None and self.fiscal_calendar_evidence.source_id != self.source_id:
            raise ValueError("Fiscal calendar context belongs to another document")
        if bool(self.annual_period_ends) != (self.annual_period_evidence is not None):
            raise ValueError("Annual period anchors require their source header")
        if len(set(self.annual_period_ends)) != len(self.annual_period_ends):
            raise ValueError("Duplicate annual period anchors")
        if self.annual_period_evidence is not None and self.annual_period_evidence.source_id != self.source_id:
            raise ValueError("Annual period anchors belong to another document")
        return self


class Claim(EvidenceModel):
    """Structured claim contract; extraction emits pending raw primitives only."""

    claim_id: str = Field(description="Unique claim identifier")
    agent: AgentName = Field(description="Authoring agent")
    claim_type: Literal["raw_primitive", "derived_metric", "qualitative", "risk", "argument"]
    entity: str | None = None
    accounting_scope: Literal["consolidated", "standalone"] | None = None
    metric: str | None = None
    value: Decimal | str | None = None
    unit: str | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    scale: int = Field(default=1, gt=0)
    period: FiscalPeriod | None = None
    claim: str = Field(description="Claim text")
    evidence: tuple[Evidence, ...] = ()
    calculation_ref: str | None = Field(
        default=None, description="Engine call ID, if applicable"
    )
    supports_claim_ids: tuple[str, ...] = ()
    candidate_claim_refs: tuple[ClaimVersionRef, ...] = ()
    argument: ArgumentContent | None = None
    support_level: SupportLevel
    verification_status: VerificationStatus = "pending"
    version: int = Field(default=1, ge=1, description="Increments on every revision")
    run_iteration: int = Field(
        default=0, ge=0, le=1, description="0 initially; verification alone does not increment it"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="before")
    @classmethod
    def monetary_values_are_numeric(cls, data: Any) -> Any:
        # Decimal serializes as a JSON string; restore its numeric meaning on replay.
        if isinstance(data, dict) and data.get("unit") == "currency" and data.get("value") is not None:
            data = dict(data)
            try:
                data["value"] = Decimal(str(data["value"]))
            except InvalidOperation as exc:
                raise ValueError("Monetary value is not numeric") from exc
        return data

    @model_validator(mode="after")
    def supported_claim(self) -> Claim:
        if not (self.evidence or self.calculation_ref or self.supports_claim_ids or self.candidate_claim_refs):
            raise ValueError("A claim needs evidence, a calculation, or supporting claims")
        if self.claim_type == "raw_primitive":
            if not self.evidence or self.calculation_ref is not None:
                raise ValueError("Raw primitives require source evidence, not a calculation")
        if self.claim_type == "derived_metric" and not self.calculation_ref:
            raise ValueError("Derived metrics require a calculation reference")
        if self.support_level == "calculation_backed" and not self.calculation_ref:
            raise ValueError("calculation_backed requires a calculation reference")
        if isinstance(self.value, Decimal):
            if not self.value.is_finite() or self.unit is None or self.period is None:
                raise ValueError("Numeric claims need finite values, units, and periods")
            if self.unit == "currency" and self.currency is None:
                raise ValueError("Monetary claims need an explicit currency")
        if self.timestamp.utcoffset() is None:
            raise ValueError("Timestamps must be timezone aware")
        return self

    @property
    def base_value(self) -> Decimal:
        """Exact scale normalization, not a financial metric or an engine result."""
        if not isinstance(self.value, Decimal):
            raise ValueError("This claim is not numeric")
        return self.value * self.scale

    def verification_shape_error(self) -> str | None:
        """Implemented check shapes, stricter than legacy storage acceptance.

        Numbers inside a quotation are text. A structured value (including a
        numeric string) or numerical dimensions must never ride that quote's
        verification. Unsupported historical shapes remain stored unchanged.
        """
        if self.claim_type in ("raw_primitive", "derived_metric"):
            if not isinstance(self.value, Decimal) or not self.metric or self.period is None:
                return "Numeric claims require a structured Decimal value, metric and period"
            if self.claim_type == "raw_primitive":
                if (self.agent != "DocumentAgent" or self.unit != "currency" or not self.currency
                        or self.accounting_scope is None):
                    return "Implemented raw primitives require Document source-cell monetary dimensions"
            elif self.agent != "FinancialAgent" or not self.calculation_ref:
                return "Implemented derived metrics require Financial deterministic artifacts"
            return None
        if self.claim_type == "argument":
            if (self.agent not in ("Bull", "Bear") or self.argument is None or self.value is not None
                    or self.unit is not None or self.currency is not None or self.scale != 1
                    or self.calculation_ref or self.evidence or self.supports_claim_ids):
                return "Only constrained Bull/Bear interpretations with exact factual premises are supported"
            return None
        if self.argument is not None:
            return "Factual claims cannot carry argument interpretations"
        if self.value is not None or self.unit is not None or self.currency is not None or self.scale != 1:
            return "Narrative claims cannot carry structured values, units, currencies or non-unit scales"
        if self.claim_type == "qualitative":
            if self.calculation_ref or self.accounting_scope is not None:
                return "Qualitative quotations cannot carry calculation or accounting dimensions"
            if self.agent == "DocumentAgent":
                if self.period is not None or self.metric not in (None, "source_statement"):
                    return "Document quotations require the non-numeric source-statement shape"
            elif self.agent != "MarketAgent":
                return "Only Document quotations and canonical Market descriptions are implemented"
        return None


def _require_identifier(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be nonblank with no surrounding whitespace")
    return value


class ClaimVersionRef(EvidenceModel):
    """An exact stored identity; a logical claim ID alone is not run-scoped."""

    run_id: str
    claim_id: str
    version: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def valid_identifiers(self) -> ClaimVersionRef:
        _require_identifier(self.run_id, "run_id")
        _require_identifier(self.claim_id, "claim_id")
        return self


class VerificationCheck(EvidenceModel):
    code: str = Field(min_length=1)
    outcome: Literal["passed", "missing", "contradicted", "error"]
    message: str = Field(min_length=1)


class VerificationRecord(EvidenceModel):
    verification_id: str = Field(min_length=1)
    checked_ref: ClaimVersionRef
    resulting_ref: ClaimVersionRef
    outcome: Literal["verified", "unsupported", "flagged"]
    support_level: SupportLevel
    checks: tuple[VerificationCheck, ...]
    fresh_evidence: tuple[Evidence, ...] = ()
    retrieved_chunk_ids: tuple[str, ...] = ()
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def valid_transition(self) -> VerificationRecord:
        a, b = self.checked_ref, self.resulting_ref
        if a.run_id != b.run_id or a.claim_id != b.claim_id or b.version != a.version + 1:
            raise ValueError("Verification must pin one consecutive same-run claim revision")
        if not self.checks or self.timestamp.utcoffset() is None:
            raise ValueError("Verification needs checks and an aware timestamp")
        if self.outcome == "verified" and any(c.outcome != "passed" for c in self.checks):
            raise ValueError("Verified records require every check to pass")
        if self.outcome == "verified" and self.support_level == "unsupported":
            raise ValueError("Verified records require support")
        expected = ("flagged" if any(c.outcome == "contradicted" for c in self.checks) else
                    "unsupported" if any(c.outcome != "passed" for c in self.checks) else "verified")
        if self.outcome != expected:
            raise ValueError("Verification outcome must exactly reflect its checks")
        if len(set(self.fresh_evidence)) != len(self.fresh_evidence) or len(set(self.retrieved_chunk_ids)) != len(self.retrieved_chunk_ids):
            raise ValueError("Verification evidence and retrieved chunk IDs must be distinct")
        return self


class ArgumentPremise(EvidenceModel):
    claim_ref: ClaimVersionRef
    entity: str | None
    metric: str | None
    value: Decimal | str | None
    period: FiscalPeriod | None
    unit: str | None
    currency: str | None
    scale: int
    accounting_scope: Literal["consolidated", "standalone"] | None
    calculation_ref: str | None
    source_ids: tuple[str, ...] = ()
    quotations: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def numeric_snapshot(cls, data):
        if isinstance(data, dict) and data.get("unit") in ("currency", "percent", "ratio") and data.get("value") is not None:
            data = dict(data)
            value=data["value"]
            if isinstance(value,bool) or not isinstance(value,(str,int,float,Decimal)):
                raise ValueError("Numeric argument premise requires a finite decimal value")
            try:
                number=Decimal(str(value))
            except InvalidOperation as exc:
                raise ValueError("Numeric argument premise is not a number") from exc
            if not number.is_finite():
                raise ValueError("Numeric argument premise must be finite")
            data["value"] = number
        return data


class ArgumentContent(EvidenceModel):
    stance: Literal["bull", "bear"]
    interpretation: Literal["strength", "resilience", "caution", "uncertainty"]
    premises: tuple[ArgumentPremise, ...] = Field(min_length=1)
    counterevidence: tuple[ClaimVersionRef, ...] = ()
    qualifications: tuple[Literal["historical_only", "not_causal", "not_recommendation", "coverage_limited"], ...]
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ContradictionRecord(EvidenceModel):
    finding_id: str = Field(min_length=1)
    category: Literal["numerical", "temporal", "unit", "source", "logical", "causal", "risk_interpretation", "missing_evidence"]
    rule: str
    description: str
    claim_refs: tuple[ClaimVersionRef, ...]
    original_refs: tuple[ClaimVersionRef, ...]
    components: tuple[AgentName, ...]
    root_cause: str
    missing_evidence: tuple[str, ...] = ()
    recommended_scope: tuple[AgentName, ...] = ()
    status: Literal["open", "resolved", "unresolved"] = "open"
    explanation: str | None = None
    version: int = Field(default=1, ge=1)
    run_iteration: int = Field(default=0, ge=0, le=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReanalysisRequest(EvidenceModel):
    trigger: Literal["health_gate", "evidence_gap", "critic"]
    affected_refs: tuple[ClaimVersionRef, ...] = ()
    components: tuple[AgentName, ...]
    failure_types: tuple[str, ...]
    correction: tuple[str, ...]
    metrics: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    retryable: bool = True


class RetryDecision(EvidenceModel):
    decision_id: str
    requests: tuple[ReanalysisRequest, ...]
    affected_refs: tuple[ClaimVersionRef, ...]
    rerun_nodes: tuple[str, ...]
    operations: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    budget_before: int = Field(ge=0, le=1)
    budget_after: int = Field(ge=0, le=1)
    outcome: Literal["executed", "skipped", "unresolved"]
    reason: str


Claim.model_rebuild()


CalculationOperation = Literal["revenue_growth", "operating_margin", "net_margin", "current_ratio"]


class CalculationFinding(EvidenceModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"]
    input_role: str | None = None


class CalculationInput(EvidenceModel):
    """A snapshot of source and normalized inputs, pinned to an existing Claim."""

    role: str
    claim_ref: ClaimVersionRef
    source_value: Decimal = Field(allow_inf_nan=False)
    source_scale: int = Field(gt=0)
    source_unit: str
    normalized_value: Decimal = Field(allow_inf_nan=False)
    normalized_unit: Literal["currency"] = "currency"
    currency: str
    entity: str
    accounting_scope: Literal["consolidated", "standalone"]
    source_period: FiscalPeriod
    period: FiscalPeriod


class CalculationArtifact(EvidenceModel):
    """Successful arithmetic is calculation-backed, never independent verification."""

    calculation_ref: str = Field(min_length=1)
    run_id: str
    operation: CalculationOperation
    formula: str
    formula_version: Literal["1.0"] = "1.0"
    engine_version: Literal["1.0"] = "1.0"
    inputs: tuple[CalculationInput, ...]
    output_value: Decimal = Field(allow_inf_nan=False)
    output_unit: Literal["percent", "ratio"]
    output_period: FiscalPeriod
    entity: str
    accounting_scope: Literal["consolidated", "standalone"]
    precision: Literal[50] = 50
    rounding: Literal["ROUND_HALF_EVEN"] = "ROUND_HALF_EVEN"
    display_value: Decimal = Field(allow_inf_nan=False)
    display_places: Literal[4] = 4
    display_rounding: Literal["ROUND_HALF_UP"] = "ROUND_HALF_UP"
    validation_status: Literal["passed"] = "passed"
    findings: tuple[CalculationFinding, ...] = ()
    support_level: Literal["calculation_backed"] = "calculation_backed"
    verification_status: Literal["pending"] = "pending"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def valid_identity(self) -> CalculationArtifact:
        _require_identifier(self.calculation_ref, "calculation_ref")
        _require_identifier(self.run_id, "run_id")
        if len(self.inputs) != 2 or len({i.claim_ref for i in self.inputs}) != 2:
            raise ValueError("A calculation requires two distinct exact input references")
        if any(i.claim_ref.run_id != self.run_id for i in self.inputs):
            raise ValueError("Calculation input belongs to another run")
        if any(f.severity == "error" for f in self.findings):
            raise ValueError("A successful artifact cannot contain validation errors")
        if self.timestamp.utcoffset() is None:
            raise ValueError("Calculation timestamps must be timezone aware")
        return self


class SharedMemory:
    """One run's append-only records; no global registry or external storage.

    The run ID belongs to this container rather than changing extraction DTOs.
    JSON strings are private immutable snapshots. Every public read returns a
    newly validated object, including nested evidence. This also protects history
    from callers bypassing Pydantic's ordinary frozen-model checks.
    """

    def __init__(self, run_id: str | None = None) -> None:
        self._run_id = _require_identifier(str(uuid4()) if run_id is None else run_id, "run_id")
        self._sources: dict[str, str] = {}
        self._claims: dict[str, tuple[str, ...]] = {}
        self._support_refs: dict[tuple[str, int], tuple[ClaimVersionRef, ...]] = {}
        self._calculations: dict[str, str] = {}
        self._verifications: tuple[str, ...] = ()
        self._health_gate_contexts: tuple[str, ...] = ()
        self._contradictions: dict[str, tuple[str, ...]] = {}
        self._retry_decisions: tuple[str, ...] = ()
        self._retry_remaining = 1

    @property
    def run_id(self) -> str:
        return self._run_id

    @staticmethod
    def _read_claim(snapshot: str) -> Claim:
        payload = json.loads(snapshot)
        record = payload["record"]
        # Decimal and a literal string both serialize as JSON text in Claim's
        # value union. Preserve that distinction without changing the public DTO.
        if payload["numeric_value"]:
            record["value"] = Decimal(record["value"])
        return Claim.model_validate(record)

    @staticmethod
    def _check_evidence(evidence: Evidence, source: SourceDocument) -> None:
        if (evidence.source_id != source.source_id or evidence.source != source.title
                or evidence.source_url != source.source_url or evidence.source_type != source.source_type):
            raise ValueError("Evidence identity does not match its registered source")

    def register_source(self, source: SourceDocument) -> SourceDocument:
        """Retain source identity and currency context once within this run."""
        if not isinstance(source, SourceDocument):
            raise TypeError("register_source expects a SourceDocument")
        accepted = SourceDocument.model_validate(source.model_dump(round_trip=True))
        if accepted.source_id in self._sources:
            raise ValueError(f"Source already registered: {accepted.source_id}")
        if accepted.currency_evidence is not None:
            self._check_evidence(accepted.currency_evidence, accepted)
        if accepted.fiscal_calendar_evidence is not None:
            self._check_evidence(accepted.fiscal_calendar_evidence, accepted)
        if accepted.annual_period_evidence is not None:
            self._check_evidence(accepted.annual_period_evidence, accepted)
        self._sources[accepted.source_id] = accepted.model_dump_json(round_trip=True)
        return self.get_source(accepted.source_id)

    def get_source(self, source_id: str) -> SourceDocument:
        """Return a detached source; an unknown source raises KeyError."""
        return SourceDocument.model_validate_json(self._sources[source_id])

    def append(self, claim: Claim) -> Claim:
        """Validate and append v1 or the next consecutive version, atomically.

        Register cited SourceDocuments first. Supporting logical claim IDs must
        currently be verified; their exact versions are pinned at acceptance.
        Calculation references must resolve to stored artifacts. No status or
        retry counter is changed.
        """
        return self._append(claim)

    def _append(self, claim: Claim, *, verification_revision: bool = False) -> Claim:
        if not isinstance(claim, Claim):
            raise TypeError("append expects a Claim")
        # model_validate(existing_model) can trust an invalid model_copy/model_construct.
        # A recursively dumped mapping forces validation of the entire input tree.
        accepted = Claim.model_validate(claim.model_dump(round_trip=True))
        claim_id = _require_identifier(accepted.claim_id, "claim_id")
        history = self._claims.get(claim_id, ())
        if accepted.version <= len(history):
            raise ValueError(f"Duplicate claim version: {claim_id} v{accepted.version}")
        if accepted.version != len(history) + 1:
            raise ValueError("Claim versions must start at 1 and advance consecutively")
        if history and accepted.run_iteration < self.get_current(claim_id).run_iteration:
            raise ValueError("run_iteration cannot decrease across revisions")
        if verification_revision:
            previous = self.get_current(claim_id)
            excluded = {"version", "verification_status", "support_level", "timestamp"}
            if previous.model_dump(exclude=excluded) != accepted.model_dump(exclude=excluded):
                raise ValueError("Verification may revise only status and support metadata")
        if accepted.calculation_ref is not None:
            try:
                artifact = self.get_calculation(accepted.calculation_ref)
            except KeyError as exc:
                raise ValueError("Dangling calculation_ref") from exc
            if accepted.claim_type == "derived_metric" and (
                not isinstance(accepted.value, Decimal) or accepted.value != artifact.output_value
                or accepted.unit != artifact.output_unit or accepted.scale != 1
                or accepted.currency is not None or accepted.metric != artifact.operation
                or accepted.entity != artifact.entity or accepted.accounting_scope != artifact.accounting_scope
                or accepted.period != artifact.output_period or accepted.support_level != "calculation_backed"
            ):
                raise ValueError("Derived claim does not match its calculation artifact")
        for evidence in accepted.evidence:
            try:
                source = self.get_source(evidence.source_id)
            except KeyError as exc:
                raise ValueError(f"Unregistered evidence source: {evidence.source_id}") from exc
            self._check_evidence(evidence, source)
        if len(set(accepted.supports_claim_ids)) != len(accepted.supports_claim_ids):
            raise ValueError("Duplicate supporting claim IDs")
        support_refs = []
        candidates = accepted.candidate_claim_refs
        if len(set(candidates)) != len(candidates) or len({r.claim_id for r in candidates}) != len(candidates):
            raise ValueError("Duplicate candidate claim references")
        for reference in candidates:
            if reference.claim_id == claim_id:
                raise ValueError("A claim cannot depend on itself")
            try:
                target = self.resolve(reference)
            except KeyError as exc:
                raise ValueError("Missing candidate claim reference") from exc
            if not verification_revision and target.version != self.get_current(target.claim_id).version:
                raise ValueError("Candidate claim reference is stale")
        for support_id in accepted.supports_claim_ids:
            _require_identifier(support_id, "supporting claim ID")
            if support_id == claim_id:
                raise ValueError("A claim cannot support itself")
            try:
                support = self.get_current(support_id)
            except KeyError as exc:
                raise ValueError(f"Unknown supporting claim: {support_id}") from exc
            if support.verification_status != "verified" and not verification_revision:
                raise ValueError(f"Supporting claim is not currently verified: {support_id}")
            support_refs.append(ClaimVersionRef(run_id=self.run_id, claim_id=support_id, version=support.version))
        if verification_revision:
            support_refs = list(self.get_support_references(claim_id))
        snapshot = json.dumps({
            "record": accepted.model_dump(mode="json", round_trip=True),
            "numeric_value": isinstance(accepted.value, Decimal),
        }, allow_nan=False)
        detached = self._read_claim(snapshot)
        # No state changes occur until all validation and serialization succeeds.
        self._claims[claim_id] = history + (snapshot,)
        self._support_refs[(claim_id, accepted.version)] = tuple(support_refs)
        return detached

    def append_verification(self, record: VerificationRecord) -> VerificationRecord:
        """Atomically append an exact check record and a status-only claim revision.

        Failed checks retain their old dependency pointers, including stale ones;
        verification never silently repins evidence to a newer analytical claim.
        """
        if not isinstance(record, VerificationRecord):
            raise TypeError("append_verification expects a VerificationRecord")
        accepted = VerificationRecord.model_validate(record.model_dump(round_trip=True))
        current = self.resolve(accepted.checked_ref)
        for evidence in accepted.fresh_evidence:
            self._check_evidence(evidence, self.get_source(evidence.source_id))
        if self.reference(current.claim_id) != accepted.checked_ref:
            raise ValueError("Cannot verify a superseded claim version")
        if any(r.verification_id == accepted.verification_id for r in self.get_verification_records()):
            raise ValueError("Duplicate verification_id")
        updated = current.model_copy(update={"version": accepted.resulting_ref.version,
            "verification_status": accepted.outcome, "support_level": accepted.support_level,
            "timestamp": accepted.timestamp})
        snapshot = accepted.model_dump_json(round_trip=True)
        self._append(updated, verification_revision=True)
        self._verifications += (snapshot,)
        return VerificationRecord.model_validate_json(snapshot)

    def get_verification_records(self, claim_id: str | None = None) -> list[VerificationRecord]:
        records = [VerificationRecord.model_validate_json(s) for s in self._verifications]
        return [r for r in records if claim_id is None or r.checked_ref.claim_id == claim_id]

    def get_dependency_references(self, claim_id: str, version: int | None = None) -> tuple[ClaimVersionRef, ...]:
        claim = self.get_claim(claim_id, version)
        return tuple(dict.fromkeys(self.get_support_references(claim_id, claim.version) + claim.candidate_claim_refs))

    def get_dependency_freshness(self, claim_id: str, version: int | None = None) -> Literal["current", "superseded"]:
        """Exact version freshness; candidate references do not confer support."""
        refs = self.get_dependency_references(claim_id, version)
        return "current" if all(self.reference(r.claim_id) == r for r in refs) else "superseded"

    def is_current_verified(self, claim_id: str, _seen: frozenset[str] = frozenset()) -> bool:
        """Require an exact check record and recursively current verified support.

        A manually assigned status is preserved for legacy storage compatibility,
        but cannot substitute for an independent check in Phase 2 consumers.
        """
        if claim_id in _seen:
            return False
        claim = self.get_current(claim_id)
        if claim.verification_shape_error() is not None:
            return False
        if claim.claim_type == "argument":
            try:
                from agents.argument_contracts import validate_argument
                validate_argument(claim, self)
            except (ValueError, KeyError, TypeError):
                return False
        records = self.get_verification_records(claim_id)
        if (claim.verification_status != "verified" or not records
                or records[-1].outcome != "verified" or records[-1].resulting_ref != self.reference(claim_id)):
            return False
        seen = _seen | {claim_id}
        for ref in self.get_dependency_references(claim_id):
            if self.reference(ref.claim_id) != ref or not self.is_current_verified(ref.claim_id, seen):
                return False
        if claim.calculation_ref:
            artifact = self.get_calculation(claim.calculation_ref)
            if self.get_calculation_freshness(claim.calculation_ref) != "current":
                return False
            if any(not self.is_current_verified(i.claim_ref.claim_id, seen) for i in artifact.inputs):
                return False
        return True

    def _record_health_gate(self, result, issues) -> None:
        """Retain detached gate policy and upstream issues within this run only."""
        self._health_gate_contexts += (json.dumps({
            "result": result.model_dump(mode="json"),
            "issues": [issue.model_dump(mode="json") for issue in issues],
        }, allow_nan=False),)

    def get_health_gate_context(self) -> dict[str, Any] | None:
        """Detached latest authoritative gate evaluation, never caller map data."""
        return json.loads(self._health_gate_contexts[-1]) if self._health_gate_contexts else None

    def get_health_gate_history(self) -> list[dict[str, Any]]:
        return [json.loads(item) for item in self._health_gate_contexts]

    @property
    def retry_budget_remaining(self) -> int:
        return self._retry_remaining

    def _record_retry_decision(self, decision: RetryDecision) -> RetryDecision:
        accepted = RetryDecision.model_validate(decision.model_dump(round_trip=True))
        if accepted.budget_before != self._retry_remaining:
            raise ValueError("Retry decision does not match the run's global budget")
        expected = self._retry_remaining - (accepted.outcome == "executed")
        if expected < 0 or accepted.budget_after != expected:
            raise ValueError("Exactly one global analytical retry is permitted")
        for ref in accepted.affected_refs:
            self.resolve(ref)
        self._retry_remaining = expected
        self._retry_decisions += (accepted.model_dump_json(),)
        return RetryDecision.model_validate_json(self._retry_decisions[-1])

    def get_retry_decisions(self) -> list[RetryDecision]:
        return [RetryDecision.model_validate_json(item) for item in self._retry_decisions]

    def append_contradiction(self, finding: ContradictionRecord) -> ContradictionRecord:
        accepted = ContradictionRecord.model_validate(finding.model_dump(round_trip=True))
        history = self._contradictions.get(accepted.finding_id, ())
        if accepted.version != len(history) + 1 or accepted.timestamp.utcoffset() is None:
            raise ValueError("Finding versions must be consecutive with aware timestamps")
        for ref in accepted.claim_refs + accepted.original_refs:
            self.resolve(ref)
        if history:
            previous = ContradictionRecord.model_validate_json(history[-1])
            if (accepted.original_refs != previous.original_refs or accepted.rule != previous.rule
                    or accepted.run_iteration < previous.run_iteration):
                raise ValueError("Finding revision cannot erase its origin or rule")
        self._contradictions[accepted.finding_id] = history + (accepted.model_dump_json(),)
        return ContradictionRecord.model_validate_json(self._contradictions[accepted.finding_id][-1])

    def get_contradictions(self, *, history: bool = False) -> list[ContradictionRecord]:
        return [ContradictionRecord.model_validate_json(item)
                for records in self._contradictions.values() for item in (records if history else records[-1:])]

    def get_claim(self, claim_id: str, version: int | None = None) -> Claim:
        """Read an exact version, or the current version when omitted.

        Unknown claims/versions raise KeyError; malformed identities raise
        ValueError/TypeError. Historical reads deliberately retain old statuses.
        """
        _require_identifier(claim_id, "claim_id")
        if version is not None and (type(version) is not int or version < 1):
            raise ValueError("version must be a positive integer")
        history = self._claims[claim_id]
        selected = len(history) if version is None else version
        if selected > len(history):
            raise KeyError((claim_id, selected))
        return self._read_claim(history[selected - 1])

    def get_current(self, claim_id: str) -> Claim:
        """Return the newest accepted version, irrespective of status."""
        return self.get_claim(claim_id)

    def get_history(self, claim_id: str) -> list[Claim]:
        """Return all versions in ascending version order; unknown ID: KeyError."""
        _require_identifier(claim_id, "claim_id")
        return [self._read_claim(snapshot) for snapshot in self._claims[claim_id]]

    def reference(self, claim_id: str, version: int | None = None) -> ClaimVersionRef:
        """Create an exact run/claim/version pointer to an existing record."""
        record = self.get_claim(claim_id, version)
        return ClaimVersionRef(run_id=self.run_id, claim_id=record.claim_id, version=record.version)

    def resolve(self, reference: ClaimVersionRef) -> Claim:
        """Resolve an exact pointer; reject pointers to another run."""
        if not isinstance(reference, ClaimVersionRef):
            raise TypeError("resolve expects a ClaimVersionRef")
        reference = ClaimVersionRef.model_validate(reference.model_dump(round_trip=True))
        if reference.run_id != self.run_id:
            raise ValueError("Claim reference belongs to another run")
        return self.get_claim(reference.claim_id, reference.version)

    def get_support_references(self, claim_id: str, version: int | None = None
                               ) -> tuple[ClaimVersionRef, ...]:
        """Read pinned support versions; no dependency graph or invalidation runs."""
        record = self.get_claim(claim_id, version)
        return tuple(ref.model_copy(deep=True) for ref in self._support_refs[(claim_id, record.version)])

    def append_calculation(self, artifact: CalculationArtifact) -> CalculationArtifact:
        """Append an immutable artifact after replay against exact stored inputs."""
        if not isinstance(artifact, CalculationArtifact):
            raise TypeError("append_calculation expects a CalculationArtifact")
        accepted = CalculationArtifact.model_validate(artifact.model_dump(round_trip=True))
        if accepted.run_id != self.run_id:
            raise ValueError("Calculation belongs to another run")
        if accepted.calculation_ref in self._calculations:
            raise ValueError("Duplicate calculation_ref")
        # Local import keeps the shared contracts importable without a module cycle.
        # Only the approved engine executes/replays financial arithmetic.
        from engine.financial_engine import FinancialEngine
        FinancialEngine(self).validate_artifact(accepted)
        snapshot = accepted.model_dump_json(round_trip=True)
        detached = CalculationArtifact.model_validate_json(snapshot)
        self._calculations[accepted.calculation_ref] = snapshot
        return detached

    def get_calculation(self, calculation_ref: str) -> CalculationArtifact:
        _require_identifier(calculation_ref, "calculation_ref")
        return CalculationArtifact.model_validate_json(self._calculations[calculation_ref])

    def get_calculations(self) -> list[CalculationArtifact]:
        return [self.get_calculation(ref) for ref in self._calculations]

    def get_calculation_freshness(self, calculation_ref: str) -> Literal["current", "superseded"]:
        """Version freshness only; never rewrites artifacts or invalidates claims."""
        artifact = self.get_calculation(calculation_ref)
        return "current" if all(self.get_current(i.claim_ref.claim_id).version == i.claim_ref.version
                                for i in artifact.inputs) else "superseded"

    def get_claims(
        self,
        agent: AgentName | None = None,
        verification_status: VerificationStatus | None = None,
        min_version_only: bool = True,
        *,
        support_level: SupportLevel | None = None,
    ) -> list[Claim]:
        """List this run's CURRENT claims, then apply optional filters.

        The legacy name min_version_only means latest, not minimum. False is an
        explicit unfiltered history view; combining it with filters is rejected
        so a superseded verified version cannot be mistaken for current evidence.
        Ordering is first claim insertion, then ascending version for history.
        """
        for name, value, labels in (
            ("agent", agent, AgentName),
            ("verification_status", verification_status, VerificationStatus),
            ("support_level", support_level, SupportLevel),
        ):
            if value is not None and value not in get_args(labels):
                raise ValueError(f"Unknown {name}: {value!r}")
        if type(min_version_only) is not bool:
            raise TypeError("min_version_only must be a boolean")
        if not min_version_only:
            if any(value is not None for value in (agent, verification_status, support_level)):
                raise ValueError("History views cannot be filtered; filter current claims or use get_history")
            return [record for claim_id in self._claims for record in self.get_history(claim_id)]
        current = [self.get_current(claim_id) for claim_id in self._claims]
        return [record for record in current
                if (agent is None or record.agent == agent)
                and (verification_status is None or record.verification_status == verification_status)
                and (support_level is None or record.support_level == support_level)]

    def get_verification_health(self) -> dict[str, float | int]:
        """Aggregate verification stats for the Health Gate.

        Returns:
            Dict with total, unsupported_count, contradicted_count, unsupported_rate.
        """
        from agents.verification_gate import VerificationHealthGate
        result = VerificationHealthGate(self)._evaluate(issues=(), evaluation_id="summary")
        return {"total": result.total, "verified_count": result.verified_count,
                "unsupported_count": result.unsupported_count, "contradicted_count": result.flagged_count,
                "pending_count": result.pending_count, "unresolved_count": result.unresolved_count,
                "stale_count": result.stale_count, "unsupported_rate": result.unsupported_rate}

    def get_unresolved(self) -> dict[str, list[Any]]:
        """Return claims/contradictions still flagged at final state.

        Returns:
            Dict of unresolved/unsupported items for the report Limitations section.
        """
        return {"claims": [c for c in self.get_claims() if not self.is_current_verified(c.claim_id)],
                "contradictions": [f for f in self.get_contradictions() if f.status != "resolved"]}
