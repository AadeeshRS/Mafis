# MAFIS — Shared Memory Reference v1.1

> Authoritative schema and behavior specification for `memory/shared_memory.py`. Agents communicate through this structured store rather than passing raw natural-language outputs directly.

## Rules

1. **Append-only.** Never overwrite a claim in place. Re-analysis creates a new version and preserves the old record.
2. **Every claim needs support.** A claim must have direct evidence, a deterministic calculation reference, or `supports_claim_ids` that point to verified claims.
3. **Support level is a rubric label, not a probability.** Do not display an LLM's self-reported confidence as a calibrated probability.
4. **Agents read structured data, not each other's raw prose.**
5. **Raw primitives and derived claims are different.** A raw numeric primitive may come directly from a cited document; any derived/final numeric metric must reference the deterministic engine.
6. **Verification creates a new version.** Verification status is not an in-place mutation of the original analytical claim.

## Schema

```json
{
  "claim_id": "string, unique logical identifier",
  "agent": "DocumentAgent | FinancialAgent | MarketAgent | RiskAgent | Verification | Critic | Bull | Bear",
  "claim_type": "raw_primitive | derived_metric | qualitative | risk | argument",
  "entity": "string | null",
  "accounting_scope": "consolidated | standalone | null",
  "metric": "string | null",
  "value": "number | string | null",
  "unit": "string | null",
  "period": {"kind": "instant | duration", "end_date": "ISO date", "start_date": "ISO date | null", "label": "source period label"},
  "currency": "ISO currency code | null",
  "scale": "positive integer multiplier from displayed to base units",
  "claim": "string",
  "evidence": [
    {
      "source": "string",
      "source_type": "annual_report | filing | news | market_data | other",
      "page": "int | null",
      "section": "string | null",
      "year": "int | null",
      "locator": "string | null"
    }
  ],
  "calculation_ref": "string | null",
  "supports_claim_ids": ["string"],
  "support_level": "multiple_sources | single_source | calculation_backed | unsupported",
  "verification_status": "verified | unsupported | flagged | pending | unresolved",
  "version": "int, starts at 1",
  "run_iteration": "int, 0 for initial pass and incremented for re-analysis",
  "timestamp": "ISO-8601"
}
```

## Initial extraction milestone contract

The extraction subset is source identity, fiscal periods, evidence, and claims.
Milestones 2 and 3 implement the append-only store and calculation artifacts below; later-phase
verification and contradiction behaviors remain planned. A claim's
numeric `value` is in displayed source units; `scale` converts it to base units.
Raw source values remain distinct from `derived_metric` claims, which require a
calculation reference. Extracted claims are `single_source` / `pending`.

Evidence also records `source_id` (SHA-256 identity), `source_url`, `printed_page`,
`quote`, a row `bbox` in PDF points from the top-left, `row_label`, `column_header`,
`raw_value`, `scale_header`, and `period_header`. `page` is the one-based PDF page
index. The source document stores its hash and source-backed currency context.
Raw period starts stay null when not directly established. `accounting_scope`
is optional for compatibility; the extraction slice establishes `consolidated`
from the statement heading, and the engine requires explicit scope. SourceDocument
can retain `fiscal_year_weeks` as year/52-or-53-week pairs accompanied by
`fiscal_calendar_evidence`. For supported comparative annual statements it can
also retain `annual_period_ends` with `annual_period_evidence` pointing to the
actual annual header. Both anchors and their evidence must be supplied together;
duplicate anchors and evidence from another document are rejected. The engine
uses the consecutive preceding year-end only within its existing 350-371-day
annual-period rule; raw claim starts remain null. Calculation snapshots retain
the normalized start separately, and reports cite the source header. This is
period normalization, not independent verification or a new calendar framework.
Unknown schema fields, including obsolete `confidence`,
are rejected. Verification remains unimplemented.

## Milestone 2: per-run append-only storage

- `SharedMemory(run_id=None)` owns one isolated run. An omitted ID generates a
  UUID; caller-supplied IDs must be unique per run. A new instance is empty and
  does not reopen another instance. No global registry or external service exists.
- Extraction Claim payloads remain unchanged. Run membership is the owning store;
  exact record identity is `(run_id, claim_id, version)`. `ClaimVersionRef` makes
  that identity explicit for calculation artifacts and future dependencies.
- Register the existing `SourceDocument` before its claims. Source records retain
  hashes and document-level currency evidence. All claim evidence must point to
  a registered source with the same title, URL, source type, and hash identity.
  Duplicate source registration cannot overwrite prior metadata.
- Claim versions start at 1 and advance consecutively. Duplicate versions and
  gaps are rejected. Revisions may keep `run_iteration` unchanged; it cannot move
  backwards. This store does not allocate or consume analytical retries.
- Inputs are recursively revalidated, including inputs created through Pydantic
  validation-bypassing helpers. Private immutable JSON snapshots retain accepted
  records, including the distinction between numeric Decimal values and text.
  Reads return fresh objects, so neither input nor output mutation can
  change history. Source-linked extraction claims are not promoted to verified.
- Queries resolve newest versions before applying agent, verification-status,
  or support-level filters. `get_claims` defaults to current records. The legacy
  `min_version_only` parameter means latest; explicit `False` is an unfiltered
  history view. Combining that view with filters is an error; use `get_history`
  for deliberate historical inspection.
- Under Rule 2, supporting logical claim IDs must currently exist and be verified.
  The store pins their exact versions at acceptance without altering the Claim
  schema. Unknown, duplicate, or self-support references are rejected. Old pinned
  versions remain inspectable, but cannot substitute for current eligibility when
  appending a new claim. Dependency invalidation is not implemented here.
- Milestone 2 rejected all calculation references. Milestone 3 now resolves them
  against stored, replay-validated calculation artifacts as described below.
- Invalid records/references raise validation errors or `ValueError`; wrong input
  types raise `TypeError`. Unknown read identities raise `KeyError`. Failed appends
  leave the store unchanged. The interface is single-process and synchronous.

## Milestone 3: deterministic calculation artifacts

The engine supports only `revenue_growth`, `operating_margin`, `net_margin`, and
`current_ratio`. It resolves exact input versions from this store; raw primitives
remain separate and unchanged. The accepted request roles, validation rules,
precision policy, and usage are documented in [Readme.md](../Readme.md#deterministic-financial-engine).

The artifact contracts are defined here in `memory/shared_memory.py`:

- `CalculationFinding`: structured code, severity, message, and optional input role.
- `CalculationInput`: role, exact `ClaimVersionRef`, original value/scale/unit/period,
  normalized Decimal value/unit/period, currency, entity, and accounting scope.
  Missing annual start dates may be normalized using registered source-calendar
  evidence; `source_period` preserves what the raw claim actually stated.
- `CalculationArtifact`: unique `calculation_ref`, run ID, allowlisted operation,
  formula, formula and engine version (`1.0`), two input snapshots, output value,
  unit and period, entity/scope, findings, and an aware UTC timestamp. Metadata pins
  precision 50, `ROUND_HALF_EVEN`, and separate four-place `ROUND_HALF_UP` display
  rounding. Percent values are percentage points; ratios are plain quotients.
  Validation status is `passed`, support is `calculation_backed`, and verification
  remains `pending`, including when all source inputs already have verified status.

`append_calculation` revalidates and replays through the deterministic engine
before storing an immutable JSON snapshot. Exact referenced versions must exist
in this run. Duplicate IDs, missing inputs, forged formulas, altered snapshots,
and incorrect outputs are rejected without writing. Reads return detached models.
The engine never evaluates arbitrary expression strings.

`append` now accepts a calculation reference only if it resolves locally. A
`derived_metric` must exactly match the artifact output, unit, scale of 1, metric,
entity, scope, and period, use `calculation_backed`, and have no currency for these
dimensionless operations. The store does not automatically create derived claims
or promote verification status. A future verification revision remains possible.

`get_calculation_freshness` compares pinned versions with current claim versions:
it returns `current` or `superseded`. Old artifacts continue resolving and replaying
against their historical inputs. No deletion, invalidation cascade, or targeted
re-analysis is implemented. This remains an in-memory, per-run store.

## Contradiction Schema

Contradictions are stored separately from claims so that a conflict is not confused with a claim revision.

```json
{
  "contradiction_id": "string, unique",
  "claim_ids": ["string", "string"],
  "type": "numerical | temporal | unit | source | logical | causal | risk_interpretation | missing_evidence",
  "description": "string",
  "status": "open | resolved | unresolved",
  "reanalysis_requested": "boolean",
  "run_iteration": "int",
  "timestamp": "ISO-8601"
}
```

## Evidence-Gap / Re-analysis Metadata

Evidence gaps and routing instructions are structured state used by Planner; they are not treated as factual claims.

```json
{
  "reanalysis_scope": ["DocumentAgent | FinancialAgent | MarketAgent | RiskAgent"],
  "missing_evidence": ["string"],
  "trigger": "health_gate | critic | evidence_gap",
  "retry_budget_remaining": "int"
}
```

## Read/Write Matrix

| Agent | Reads | Writes |
|---|---|---|
| Planner Agent | Query, document availability, verification health, evidence-gap/re-analysis metadata | Task graph and routing state |
| Document Agent | RAG | Raw primitives + citations |
| Financial Agent | Document claims, relevant RAG evidence | Derived metrics + calculation references |
| Market Agent | RAG / external source results | Market findings + citations |
| Risk Agent | Financial claims, Market claims, direct RAG evidence | Risk findings + supporting references |
| Verification Agent | All claims, RAG, calculation results | Verification versions with support/verification status |
| Verification Health Gate | Aggregate verification statistics | Routing decision only |
| Bull / Bear | Verified claims only | Arguments citing existing claim IDs; evidence-gap signal if needed |
| Critic | Bull/Bear arguments, underlying structured claims, contradictions | Contradiction objects + re-analysis scope |
| Report Generation Agent | Final-state Shared Memory | No new factual claims; final report artifact only |

## Support-Level Rubric

| Label | Meaning |
|---|---|
| `multiple_sources` | Claim has support from two or more independent evidence entries |
| `single_source` | Claim has one traceable source but has not received independent confirmation |
| `calculation_backed` | Derived numerical result is produced by the deterministic engine |
| `unsupported` | No sufficient support was found |

## Verification Status

| Label | Meaning |
|---|---|
| `verified` | Evidence/calculation check passed |
| `pending` | Not yet checked |
| `flagged` | Potential issue found and requires attention |
| `unsupported` | Required support could not be established |
| `unresolved` | Problem remained after allowed re-analysis |

## Query Helpers

- `register_source(source)` / `get_source(source_id)`
- `append(claim)`
- `get_claim(claim_id, version=None)` / `get_current(claim_id)`
- `get_history(claim_id)`
- `get_claims(agent=None, verification_status=None, min_version_only=True, *, support_level=None)`
- `reference(claim_id, version=None)` / `resolve(reference)`
- `get_support_references(claim_id, version=None)`
- `append_calculation(artifact)` / `get_calculation(calculation_ref)`
- `get_calculations()` / `get_calculation_freshness(calculation_ref)`

### Planned later-phase helpers (not implemented)

- `get_verification_health()` → returns aggregate counts and rates for the Health Gate
- `get_unresolved()` → returns unresolved claims and contradictions for the final report
- `get_claims_by_metric(metric, period=None, entity=None)` → supports structured contradiction checks
- `get_claims_by_ids(claim_ids)` → returns referenced verified claims for Bull/Bear/Critic
