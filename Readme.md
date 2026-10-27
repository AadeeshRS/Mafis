# MAFIS — Multi-Agent Financial Intelligence System

MAFIS produces evidence-backed financial intelligence reports via a team of
specialized agents (Planner, Document, Financial, Market, Risk, Verification,
Bull, Bear, Critic, Report) coordinated through LangGraph, sharing state
through a single append-only Shared Memory object, with deterministic Python
for all arithmetic and a capped (max 1) targeted re-analysis loop.

This checkout implements the **Phase 1 offline MVP**, including the final
three-report acceptance batch: source-grounded extraction, append-only Shared Memory,
deterministic calculations, shared Chroma retrieval, a Gemini-compatible Document
and Financial Agent, a minimal Planner, LangGraph, and a two-stage report process.
The full flow and executable single-LLM comparator use real NVIDIA, Apple, and
Coca-Cola FY2024 PDFs with mocked Gemini responses. Real local semantic retrieval
is measured separately. Live Gemini quality and empirical model comparison remain
unvalidated because project free-tier quota/billing could not be established.
See the [Phase 1 acceptance report](useful_md_files/phase1-acceptance.md) for actual
measurements, failures, and the remaining acceptance conditions. Later-phase agents
remain planned; the four-phase architecture is unchanged.

## Run the focused milestone tests

Use Python 3.12 and the existing virtual environment (or create one first):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-phase1.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Tests run offline against unmodified publisher PDFs under `tests/fixtures/`.
The [case manifest](tests/fixtures/phase1_cases.json) links document identities and
separate test-only gold annotations. Each fixture directory records its URL,
hash, source pages, annotations, and limits. `requirements-phase1.txt` pins the
implemented subset; the full future stack in `requirements.txt` is unnecessary.
The original extraction/memory/engine subset can still run with
`requirements-extraction.txt` by selecting `tests/test_ingest.py`,
`tests/test_shared_memory.py`, and `tests/test_financial_engine.py` explicitly.

`rag.ingest.extract_financial_facts(path, source_url=..., title=..., entity=...)`
reads only the PDF and document identity, never the test annotations. It returns
typed claims and explicit failures. Claims are `raw_primitive`, `single_source`,
and `pending`, not independently verified. Numeric `value` uses the source scale;
`base_value` performs unit normalization. The extractor computes no financial
ratios. Unsupported layouts, ambiguous headers, and missing values fail visibly.
Consolidated statement headings establish `accounting_scope`. An explicit fiscal
calendar policy or consecutive annual statement headers are retained with source evidence;
raw claim period starts remain unknown if not printed in the table.

## Append-only Shared Memory

`SharedMemory(run_id=None)` in `memory/shared_memory.py` owns one run. Supply a
unique run ID or let it generate a UUID. Extracted Claim objects keep their existing
schema and IDs; stored identity is `(run_id, claim_id, version)`. A new instance
does not reopen an existing run, even if a caller reuses its ID.

Register the extraction result's `SourceDocument` with `register_source` before
appending its claims. This retains the source hash and document-level currency
evidence as well as each claim's original page/table/period/unit/scale metadata.
`get_source` retrieves that metadata. Duplicate source identities and mismatched
or unregistered source references are rejected.

`append` requires version 1 first, then consecutive revisions. Duplicate versions
are rejected; status revisions do not change `run_iteration` automatically.
`get_claim(id, version=None)` and `get_current(id)` read current claims;
`get_history(id)` reads all revisions. `reference` / `resolve` use exact
`ClaimVersionRef(run_id, claim_id, version)` pointers and reject another run's
references. Reads and writes use detached validated snapshots, so caller mutation
cannot modify accepted history.

`get_claims` resolves current versions **before** filtering by agent,
`verification_status`, or `support_level`. The legacy `min_version_only` name
means latest; it now defaults to `True`. Explicit `False` returns unfiltered
history; filtered history requests are rejected. This prevents an older verified
revision from leaking into a current-evidence query.

Supporting claim IDs must resolve to current verified records; their versions
are pinned and readable through `get_support_references`. This is reference
validation, not a dependency graph or automatic downstream invalidation.
Calculation references must resolve to accepted artifacts; derived numeric claims
must match the artifact's output, unit, scale, metric, entity, scope, and period.
The store does not verify claims, consume retries, or persist across processes.
The NVIDIA integration test stores the actual six extraction outputs, preserves
all metadata, and leaves them `single_source` / `pending`.

## Deterministic financial engine

`FinancialEngine(memory)` in `engine/financial_engine.py` accepts a
`CalculationRequest` or equivalent mapping. Inputs are exact stored
`ClaimVersionRef(run_id, claim_id, version)` references, never caller-supplied
values or executable formulas.

| Operation | Required input roles | Output |
|---|---|---|
| `revenue_growth` | `current_revenue`, `previous_revenue` | `((current - previous) / previous) * 100`, percent |
| `operating_margin` | `operating_income`, `revenue` | `(income / revenue) * 100`, percent |
| `net_margin` | `net_income`, `revenue` | `(income / revenue) * 100`, percent |
| `current_ratio` | `current_assets`, `current_liabilities` | `assets / liabilities`, ratio |

For example, after registering a source and appending its extracted claims:

```python
from engine.financial_engine import CalculationRequest, FinancialEngine

request = CalculationRequest(
    operation="net_margin",
    inputs={
        "net_income": memory.reference(net_income_claim_id),
        "revenue": memory.reference(revenue_claim_id),
    },
)
result = FinancialEngine(memory).calculate(request)
if result.status == "success":
    artifact = memory.get_calculation(result.artifact.calculation_ref)
else:
    errors = result.findings  # structured code, severity, message, optional input role
```

Validation rejects absent/nonfinite values, wrong metrics, duplicate logical
inputs, missing/cross-run references, unsupported operations, incompatible entity,
scope, currency, unit, or period, and unresolved evidence problems. Monetary scales
must be positive powers of ten; compatible mixed scales normalize exactly to base
currency using a Decimal exponent shift. Zero numerators and negative income are
valid. Zero denominators, negative prior revenue, negative revenue denominators,
and negative liabilities are rejected. Negative numerators receive a warning.

Growth requires adjacent annual periods of 350–371 days with at most a seven-day
length difference. Unequal lengths are warned about without annualizing. Margins
require matching duration boundaries; the current ratio requires matching instant
dates. A missing annual start can be computed from a source-backed 52/53-week
policy or the immediately preceding comparative annual year-end. The artifact retains both raw and normalized
periods. Other missing duration context is rejected. No January 1 assumption is made.

Arithmetic uses a private 50-significant-digit Decimal context, `ROUND_HALF_EVEN`,
and exponent limits of ±999999, independent of the caller's Decimal context.
No display rounding is applied to intermediates. Percent outputs store percentage
points (e.g. `25` means 25%); ratios store the quotient (e.g. `2.5`). Only
`display_value` is rounded to four decimal places with `ROUND_HALF_UP`. Numeric
overflow, underflow, or unrepresentable display values produce explicit rejections.
Growth magnitudes above 200% and margin magnitudes above 100% warn without rejecting;
valid 340% growth is retained. Pending source inputs produce a warning.

`CalculationArtifact` lives alongside Claim in `memory/shared_memory.py`. It records
a unique reference, run, operation/formula versions, exact input versions, original
and normalized values/periods/units, currency, scope, output, precision/rounding,
findings, and UTC timestamp. Artifacts are `calculation_backed` / `pending`;
successful arithmetic is not independent verification. Repeated requests preserve
the same numerical results, with new artifact IDs and timestamps.

`calculate` returns a structured success with its stored artifact or a rejection
with findings and no write. `validate_inputs` returns findings without writing;
`validate_artifact` replays an artifact and raises on mismatches, and
`validate_outputs` returns a boolean. Shared Memory's `append_calculation` replays
against the exact stored claim versions before accepting a detached immutable
snapshot. Duplicate IDs and altered or dangling artifacts are rejected.
`get_calculation`, `get_calculations`, and `get_calculation_freshness` expose
history. Freshness is `current` or `superseded`; later claim revisions never rewrite
old artifacts. Full dependency invalidation remains planned.

The three real-PDF integrations cover all four operations with an independent
rational-number oracle. The engine has no model calls, forecasting, or advanced
valuation. Subsequent batch components use this exact engine contract.

## Runnable Phase 1 batch

`graph.run_pipeline(question, DocumentInput(...), retriever=..., document_llm=...,
financial_llm=...)` runs:

`Planner -> ingestion/shared retrieval -> Document Agent -> Financial Agent/engine
-> Analysis Map -> Report`.

Each invocation owns an isolated Shared Memory store. Graph state carries typed
results/references, issues, and timings; it does not maintain a second claim store.
Unsupported requests, missing documents, extraction failures, and model outages
return a partial report with limitations. No later-phase routing runs.

The shared index uses local `all-MiniLM-L6-v2` ONNX embeddings. The initial model
download is required once. Chroma indexes source text/cells, not run claims. The
original ten labeled NVIDIA retrieval queries now score **10/10 Hit@5 and 1.00
Recall@5**, versus Batch 1's 9/10. A separate 12-query Apple/Coca-Cola validation
set scores **11/12 Hit@5 and 0.9167 Recall@5**. Passage coverage is lower and is
reported separately. Title-aware source sections supplement page windows in the
versioned `mafis_sources_v2` collection. The prior collection is historical.
Detailed original interfaces, per-query
results, limitations, and the file inventory are in the
[batch implementation notes](useful_md_files/batch1-implementation.md).

Run the complete development demonstration with real PDF ingestion, real local
embeddings, and **explicitly mocked Gemini SDK responses**:

```powershell
.\.venv\Scripts\python.exe -m scripts.offline_demo
```

Outputs are `output/batch1/report.md`, `analysis_map.json`, `evidence.json`, and
`run_summary.json`. They record the execution mode; mocked runs are not evidence
of live model quality. Expected numerical answers remain exclusively in tests.

Live execution uses the official Google GenAI SDK. Copy `.env.example` locally
and configure credentials/model IDs. A key alone never enables requests. After
checking the account's quota/billing, explicitly enable calls:

```powershell
.\.venv\Scripts\python.exe graph.py --live --pdf path/to/report.pdf `
  --source-url https://issuer.example/report.pdf --title "Annual report" `
  --entity "Company" --question "Assess annual financial health" --output output/phase1
```

Defaults use `gemini-3.8-flash` for both active agents and the principal comparator.
`MAFIS_PRIMARY_MODEL` controls the comparator's single shared model/settings.
Explicit per-agent overrides support separately labeled experiments; the principal
comparator always uses the primary ID for both agents and the baseline. Flash-Lite
must be evaluated as a separate variant. Model-metadata GETs succeeded, but no
generation requests were made because actual project free quota was unavailable.

Run the final acceptance tools from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.live_readiness
.\.venv\Scripts\python.exe -m scripts.evaluate_retrieval
.\.venv\Scripts\python.exe -m evaluation.run --mode mock
```

The readiness probe makes non-generating metadata requests only. The comparison
exports per-arm reports, evidence, measurements, and manifests under
`output/phase1_acceptance/`. Both arms use the same source context policy; the
manifest checks identical context fingerprints. The baseline makes one model call
and performs no production engine arithmetic. Mock arithmetic is an explicit test
double, not a quality result. Tokens are null when unavailable; mocked API cost is
zero. Live comparison additionally requires independently confirmed project free
tier/quota, `--mode live --free-tier-confirmed`, and a shared bounded request budget.
Do not run concurrent index migrations or benchmark writers against this collection.

The Document Agent accepts only retrieved, matching source cells or exact source
quotations. The Financial Agent delegates final arithmetic to the engine and
validates constrained model interpretations against its artifacts. The report
renderer consumes a validated Analysis Map; it adds no free-form model numbers.
Final validation resolves source content, current claim versions, and exact
calculation inputs. Pending independent verification is always disclosed.

## Layout

- `agents/` — planner, document, financial, market, risk, verification, bull, bear, critic, report
- `engine/` — deterministic financial engine
- `rag/` — ingest + shared retriever
- `memory/` — Shared Memory schema + append-only store
- `graph.py` — LangGraph wiring
- `config.py` — health-gate threshold, re-analysis cap

## Reference docs

The canonical v1.1 specifications below are included in the repository. The
parent workspace's `../MAFIS_PRD.md` (v1.0) and `../MAFIS.svg` are historical,
outside this Git repository, and are not implementation authority. They have not
been moved or modified. The four-phase roadmap is unchanged.

- [architecture.md](useful_md_files/architecture.md) — components, data flow, module layout
- [design.md](useful_md_files/design.md) — principles, key decisions, anti-patterns
- [memory.md](useful_md_files/memory.md) — Shared Memory schema and rules
- [plan.md](useful_md_files/plan.md) — build order and definition of done
- [phases.md](useful_md_files/phases.md) — phased build plan index
- [MAFIS_PRD.md](useful_md_files/MAFIS_PRD.md) — full product requirements
- [phase-1-core-mvp.md](useful_md_files/phase-1-core-mvp.md) — Phase 1 tasks
