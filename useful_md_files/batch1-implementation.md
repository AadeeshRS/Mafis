# Phase 1 combined batch: implemented interfaces and validation

Historical Milestones 4-7 record. For the subsequent three-report acceptance
batch and executable comparator, see [phase1-acceptance.md](phase1-acceptance.md).

This implementation follows v1.1. The four-phase roadmap is unchanged. The
single-report development fixture is not a research evaluation or baseline.

## Shared retrieval

`rag.ingest.prepare_document` builds page-bounded 900-character narrative chunks
with 150-character overlap and financial row chunks with repeated table, scale,
and date headers. Existing deterministic parsing provides six supported financial
source cells; other source content is searchable text. These cells are grounding
templates, not accepted run claims. No test annotations enter ingestion or agents.
Stable IDs hash source bytes, chunk format, location, and text. PDF/printed page,
source URL/hash, quotes, source periods, and row boxes survive indexing. Decorative
off-page content has no invented bbox; its page and text offsets remain recorded.

`SharedRetriever` uses one Chroma collection and the explicitly selected local
`all-MiniLM-L6-v2` ONNX model on CPU. No automatic embedding fallback exists.
Collection metadata prevents silent model changes. Re-indexing identical chunks
is a no-op; conflicting document identity/context is rejected. Chroma stores source
content only; Shared Memory remains the run's authoritative claim/artifact store.
The index directory (`chroma_db/`) is ignored by Git.

`retrieve(query, filters=None, top_k=5)` returns typed ranked hits with cosine
distances and complete chunks. The same interface is available on an injected
`SharedRetriever`. Filters support `doc_id`, `page`, `section`, `kind`, `metric`,
`year`, and `period_end`; period filters apply to established financial cells.
`text_contains` is an optional case-sensitive Chroma document-content filter.
Empty evidence returns `[]`; model failures raise `RetrievalUnavailable`.
Retrieved text is untrusted data and is never executed.

The ten manually labeled retrieval queries use canonical PDF pages as relevance
units. `python -m rag.evaluate --help` exposes the reproducible benchmark command.
Hit@5 is the fraction with at least one relevant page; Recall@5 is the mean
fraction of labeled pages retrieved, deduplicating pages before counting. Repeated
pages can occupy separate chunk ranks. Labels and per-query results stay separate
from inference. Unit tests use explicitly named hash embeddings plus real Chroma;
they are not semantic retrieval validation. The semantic benchmark uses real MiniLM.

Actual development run: 950 indexed chunks, Hit@5 **9/10**, mean Recall@5 **0.90**.
All queries have one labeled page, so their recall is binary in this small fixture.
The fiscal-calendar query missed: year-heavy passages on PDF pages 91, 170, 110,
142, and 143 outranked the fiscal-policy paragraph on page 155. No query, label,
or ranking rule was changed to remove this failure. Task-specific metadata filters
help financial-cell retrieval but this benchmark uses only the document filter.
Full ranked chunk IDs and pages are in `output/batch1/retrieval_results.json`.

| Query ID | Expected PDF page | Top-five PDF pages | Hit |
|---|---:|---|---|
| income-revenue-current | 150 | 150, 150, 150, 147, 147 | yes |
| income-revenue-prior | 150 | 150, 150, 150, 147, 147 | yes |
| income-operating | 150 | 150, 150, 150, 147, 147 | yes |
| income-net | 150 | 150, 150, 150, 141, 141 | yes |
| balance-assets | 152 | 152, 152, 150, 150, 168 | yes |
| balance-liabilities | 152 | 152, 152, 167, 168, 152 | yes |
| calendar | 155 | 91, 170, 110, 142, 143 | no |
| functional-currency | 157 | 157, 157, 144, 171, 144 | yes |
| recognition | 155 | 155, 155, 138, 139, 123 | yes |
| operating-cash | 154 | 154, 142, 143, 142, 147 | yes |

## Gemini adapter and Document Agent

`gemini.py` wraps the official `google-genai` SDK. The Phase 1 dependency subset
pins SDK 2.0.1 to preserve Pydantic 2.11.7; newer SDK releases require a Pydantic
upgrade. SDK arguments and parsing are tested with an injected client. The
previously intended `gemini-3.5-flash-lite` (Document) and `gemini-3.8-flash`
(Financial) defaults were checked against the official model pages. Environment
overrides are explicit; no model fallback is attempted. See `.env.example`.

The adapter sends JSON Schema, independently validates response JSON with
Pydantic, rejects incomplete/blocked/malformed responses, and retries only
transient transport errors (429/500/502/503/504 or connection/timeouts). Default:
two retries, three attempts total, 30-second timeout per attempt; nested SDK
retries are disabled. Logs contain request ID, configured/resolved model,
attempt/status, latency and available token usage, never credentials or prompts.
No token cost is guessed. Live calls require explicit opt-in and an environment
key. No API key was available during this implementation, so no live-model
quality or free-tier quota validation was performed and no paid calls were made.

`DocumentAgent(memory, retriever, llm, source_id=...)` retrieves narrative context
and task-filtered financial rows from the shared collection. Its structured
proposal is accepted only if value, metric, unit, currency, scale, period, cell
ID and chunk ID match the retrieved source. Qualitative facts must be exact
retrieved quotations. The agent supplies canonical source evidence, entity,
scope, support and pending status; the model cannot supply or upgrade them.
Missing, ambiguous, duplicate, conflicting, or fabricated extractions yield typed
issues and a partial/failed result. Repeating an identical extraction reuses
current references. No calculations or final investment judgments occur here.

Current financial grounding supports the five primitive metrics/six source cells
from the earlier deterministic parser. Unsupported numerical layouts remain
searchable but are not accepted as new financial primitives. Broader extraction
coverage is a later, explicitly authorized task. Source quotes retain PDF page
and chunk/quote offsets; their narrative bbox may cover the page rather than an
individual sentence. Neither agent nor adapter loads fixture answer files.

Documentation checked: [Google structured outputs](https://ai.google.dev/gemini-api/docs/structured-output),
[official SDK](https://googleapis.github.io/python-genai/),
[3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash),
[3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite).

## Financial Agent

`FinancialAgent(memory, llm)` reads current primitives from Shared Memory only.
The model selects a subset of the Planner's explicitly approved operations;
duplicate, invalid, or unrequested operations are rejected, and omissions are
reported. `request_calculation` constructs the existing engine's typed request
using its public `operation_inputs` role/metric contract. Missing/ambiguous
primitives or requested years fail visibly; no source re-extraction happens here.
All final arithmetic remains exclusively in the Milestone 3 engine.

For each accepted engine artifact, the model proposes a constrained qualitative
label (growth direction, profit/loss, or current-asset/liability relationship).
The label and calculation reference must agree with the engine output; the model
has no output field for a new number or free-form financial assertion. Canonical
wording and numeric values are taken from the artifact. This is intentionally
limited interpretation, not open-ended investment judgment. Rejected or missing
calculations and model outages return typed issues and partial results.

Derived claims retain the exact stored output, period, entity/scope and calculation
reference with `calculation_backed` / `pending` status. Source claims are unchanged.
Current versions are pinned when constructing requests, and superseded artifacts
cannot be published as current interpretations. This milestone adds no formulas,
valuation models, independent verification, or re-analysis behavior.

## LangGraph and report generation

The minimal Planner maps supported question patterns to raw metrics and the four
approved operations, with explicit dependencies and an optional requested fiscal
year. It rejects unsupported-only requests and missing documents before ingestion;
mixed requests retain supported work and disclose omitted scope. This is bounded,
rule-based question routing, not a general-purpose autonomous planner.
Explicit quarterly/monthly, trailing, and calendar-year requests are rejected
instead of silently answering with the available fiscal annual values. Invalid
document metadata, disabled model calls, and missing calculation inputs have
end-to-end partial-result tests.

`graph.run_pipeline` invokes a compiled LangGraph with sequential nodes:
`planner -> ingest -> document_agent -> financial_agent -> analysis_map -> report`.
Conditional edges skip unavailable/irrelevant work and preserve explicit errors.
The store is the only mutable claim/artifact authority; graph channels contain
task inputs, run/source identity, exact references, typed stage outcomes, errors,
and timings. No checkpoints or additional database are introduced. Each invocation
uses a fresh run; existing populated memory cannot be overwritten by a new run.

`ReportAgent.build_analysis_map` links six sections to current claim versions,
source evidence, exact input versions and calculation artifacts, support/status,
assumptions, and limitations. Evidence resolves against indexed source content
using exact page/cell/quote lookups, not another semantic retrieval. Raw values
must match cited source cells, derived values must replay and use current inputs,
and qualitative statements must be exact source quotations. Unsupported, altered,
or stale claims are excluded with limitations. Source-backed currency and fiscal
calendar context are included in the provenance map.

`generate_report` renders the validated map with deterministic templates, readable
source and result tables, grounded interpretation wording, citations, calculation
references and a pending-verification disclosure. It performs no new financial
arithmetic or unconstrained LLM prose generation. `validate_report` checks current
references and requires the text/status to match the backed rendering, rejecting
new numbers, unsupported assertions, altered citations, and verification upgrades.
Failed stages produce a useful partial report rather than fabricated findings.

Source overview retrieval has a general semantic profile plus a case-sensitive
source-content filter for the generic phrase `Our headquarters`. This improves
the demonstrated company-overview evidence without changing the ten benchmark
queries or ranking rules. Other wording can still require a better retrieval
profile; absent overview quotations are stated explicitly. No page numbers or
company figures are hard-coded in the pipeline or agents.

`save_outputs` writes `report.md`, `analysis_map.json`, `evidence.json` and
`run_summary.json`. The evidence file is a read-only run artifact containing
source/claim/calculation snapshots, not a second runtime database or persistence
service. All generated output remains Git-ignored. Timings and available token
usage are recorded; injected mock clients disclose mock mode and report no real
token usage. `scripts.offline_demo` runs the actual source/index/adapter/graph/report
flow with an explicit SDK double from tests. `python graph.py --help` exposes the
generic live CLI; calls require the caller's explicit `--live` opt-in.

No Market/Risk/Verification/Health Gate, Bull/Bear/Critic, adaptive re-analysis,
advanced valuation, baseline experiment, frontend, or additional-report expansion
was implemented. The four-phase architecture is unchanged. Live Gemini behavior,
open-ended interpretation quality, broader extraction layouts, and paraphrase
coverage remain limitations; passing mocks do not establish those capabilities.

## Batch file inventory

Modified existing modules: `config.py`, `rag/ingest.py`, `rag/retriever.py`,
`agents/document_agent.py`, `agents/financial_agent.py`, `agents/planner.py`,
`agents/report_agent.py`, `graph.py`, and `engine/financial_engine.py` (only the
public approved input-role accessor). Milestone 3 Shared Memory and arithmetic
behavior remain intact.

Created: `gemini.py`, `rag/models.py`, `rag/evaluate.py`, `agents/contracts.py`,
`requirements-phase1.txt`, `.env.example`, `scripts/offline_demo.py`,
`tests/conftest.py`, `tests/__init__.py`, `tests/fakes.py`, `tests/test_retrieval.py`,
`tests/test_gemini.py`, `tests/test_document_agent.py`, `tests/test_financial_agent.py`,
`tests/test_planner.py`, `tests/test_report_agent.py`, `tests/test_pipeline.py`,
and `tests/fixtures/nvidia_2024/retrieval_queries.json`.

Updated `requirements.txt` with the official SDK and compatible LangChain Core
pin and `Readme.md` with execution instructions. This implementation note is new.
Existing uncommitted milestone work was preserved. No commits were created.

## Actual completion validation

- Stage A: 11 focused retrieval tests passed; full suite then passed 163 tests.
- Stage B: adapter and Document Agent tests passed, including malformed outputs,
  bounded retries, secret-safe logs, source grounding, and missing evidence.
- Stage C: 74 Financial Agent/engine tests passed; full suite then passed 200 tests.
- Stage D/final: `python -m pytest -q` passed **234 tests, 0 failures in 106.12s**.
  This preserves all original 152 tests and adds 82 batch tests. Initial narrative
  bbox and overview-retrieval failures were corrected before this final run.
- `pip check`: no broken requirements. `git diff --check`: no whitespace errors.
- Real MiniLM benchmark: 950 chunks; Hit@5 9/10, Recall@5 0.90; fiscal-calendar miss
  retained and documented above. This is a provisional development result only.
- `python -m scripts.offline_demo`: succeeded using the actual PDF, actual local
  embeddings/Chroma, official-adapter boundary with an injected SDK double,
  append-only memory, deterministic engine, LangGraph, Analysis Map and report.
  It stored six raw primitives, one exact source quotation, four artifacts and
  four derived claims. All claims/results remain pending independent verification.
- Saved report values: growth 125.8545%, operating margin 54.1217%, net margin
  48.8493%, current ratio 4.1713. Tests compare these with the existing independent
  fixture expectations; no expected answers enter production modules.
- No API key was present; no live-model inference, free-tier quota validation, or
  paid API calls were performed. The example report and run summary explicitly
  identify mocked model execution. There is no critical offline implementation
  blocker; live model behavior remains unvalidated.

The batch stops here. Recommended next batch: explicitly quota-confirmed live
Gemini smoke validation and single-report retrieval/extraction hardening. Baseline
evaluation and additional-report comparison remain unstarted pending approval.
