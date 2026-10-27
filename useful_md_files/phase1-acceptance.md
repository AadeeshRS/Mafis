# Phase 1 final batch acceptance — 2026-10-22

Overall: **PARTIAL acceptance**. The three-company offline MVP and controlled
single-model harness run on actual source PDFs. Live model behavior and the
empirical MAFIS-versus-LLM comparison remain pending. No Phase 2 component was
implemented, no commit was created, and the four-phase v1.1 roadmap is unchanged.

## A. Implementation summary

Changes made in this final batch, relative to the existing 234-test working tree:

| Files | Change |
|---|---|
| `config.py`, `.env.example` | One primary model for the principal comparison; explicit per-role overrides remain available for separate variants. Versioned source chunk collection. |
| `gemini.py`, `scripts/live_readiness.py` | Non-generating readiness probe, optional shared attempt budget, thinking-token telemetry; existing bounded retry, timeout, typed structured-output handling preserved. |
| `rag/ingest.py` | Reusable split/shared date headers, consolidated row aliases, footer labels, explicit USD context, annual anchors, accounting signs, structured failures, contiguous title-aware section chunks. |
| `memory/shared_memory.py`, `engine/financial_engine.py` | Source-backed annual-header context and normalization of missing duration starts. Existing financial formulas, precision and validation rules are unchanged. |
| `agents/document_agent.py` | Shared evidence-context collection policy reused by the comparator. |
| `agents/report_agent.py`, `rag/retriever.py` | Annual-context citations, retrieval-call telemetry, chunk configuration checks, explicit Chroma failure boundary. |
| `rag/evaluate.py`, `scripts/evaluate_retrieval.py` | Separate development/validation retrieval measurement, passage anchors, locator/source checks and missing-document behavior. |
| `evaluation/__init__.py`, `baseline.py`, `metrics.py`, `run.py` | Single-call comparator, evaluation-only gold/oracle scoring, telemetry, per-arm artifacts and reproducible configuration manifests. |
| `tests/fixtures/apple_2024/`, `tests/fixtures/coca_cola_2024/` | Official unmodified PDFs, manual gold annotations and source notes. |
| `tests/fixtures/phase1_cases.json`, `retrieval_validation.json` | Shared three-case manifest and separate 12-query validation labels. |
| `tests/test_multi_report.py`, `test_evaluation.py`, `test_retrieval.py`, `fakes.py` | Actual-PDF integration, controlled-comparison, adversarial extraction and failure tests; explicit test-only model responses. |
| `Readme.md`, `memory.md`, `batch1-implementation.md`, this report | Current usage, bounded schema update, historical-document identification and acceptance evidence. |

The earlier `.gitignore` correction remains in place: canonical reviewed Markdown
specifications are visible; secrets, environments, caches, generated outputs and
the local index remain ignored. Existing uncommitted work was preserved. No new
runtime package, database, parsing framework, agent or architecture layer was added.

Generated review artifacts are under [`output/phase1_acceptance/`](../output/phase1_acceptance/):
`live_readiness.json`, `retrieval_results.json`, `comparison.json`, historical
`comparison_initial.json`, `artifact_audit.json`, `pytest_full.log`, and one directory per report with
MAFIS report/Analysis Map/evidence/run summary, baseline JSON/Markdown and a manifest.
These generated artifacts are deliberately ignored by Git; the tools reproduce them.

## B. Internal stage outcomes

| Stage | Status | Evidence |
|---|---|---|
| 1. Gemini readiness/live validation | PARTIAL | Real model-metadata requests succeeded; zero generation requests. Project free quota/billing is not established. |
| 2. Real-document compatibility | COMPLETE for selected profiles | Three reports, three companies, 18/18 annotated primitives and 12/12 engine calculations. |
| 3. Retrieval hardening/evaluation | COMPLETE with disclosed misses | Original ten queries unchanged; separate twelve-query validation set; all per-query results retained. |
| 4. Baseline/evaluation harness | PARTIAL | Both arms executable with identical source context and model settings; live empirical comparison pending. |
| 5. Integration/acceptance | PARTIAL | Actual three-report offline workflow and 286-test suite pass; live-model acceptance remains incomplete. |

## C. Live Gemini validation

Principal configuration: `gemini-3.8-flash` for Document Agent, Financial Agent and
single-LLM baseline; temperature 0, output cap 4096, timeout 30000 ms, at most two
outer transport retries and no nested SDK retries. No silent model substitution.
Flash-Lite is a separate potential efficiency variant, not the principal result.

A configured key successfully fetched model metadata for `gemini-3.8-flash` and
`gemini-3.5-flash-lite`; both advertised `generateContent`, `countTokens`, cached
content and batch generation, input limit 1,048,576 and output limit 65,536. The
saved repeatable readiness probe records the currently configured primary model.
The key itself was never printed or exported.

Official [primary model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
and [structured-output documentation](https://ai.google.dev/gemini-api/docs/structured-output)
support the selected API/schema path. The adapter uses the official
[Google GenAI SDK](https://googleapis.github.io/python-genai/). It records usage
metadata when exposed, sanitizes transport failures, retries only transient
429/5xx/transport failures, and rejects malformed, blocked or incomplete output.
The default request cap is intentionally below the model maximum.

**Blocker:** model metadata and the API key do not expose this project's billing
tier or active remaining free quota. No authenticated project quota/billing state
was available. Public model eligibility is insufficient to prove these requests
would be free; [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) are
project/tier dependent and [pricing](https://ai.google.dev/gemini-api/docs/pricing)
must be considered against actual project state. Therefore **zero live generation
requests** were made. Real structured-output behavior, locator integrity under real
model proposals, and live end-to-end quality are not validated by metadata GETs or mocks.

The live comparison command requires independently confirmed free access,
`--mode live --free-tier-confirmed`, and a shared 1–30-attempt budget (default 24).
The flag is a caller attestation, not an automatic billing detector. Failed
transport attempts also consume the budget. No such live run was performed.

## D. Multi-report validation

Values below are **USD millions**, consolidated scope. Each annotation is manually
checked test ground truth; production inference receives only PDF bytes and
document identity. The annotations are opened by evaluation only after both arms
finish inference. PDF and printed page numbers are different and retained.

| FY2024 report | Current revenue | Prior revenue | Operating income | Net income | Current assets | Current liabilities | Income PDF/printed; balance PDF/printed |
|---|---:|---:|---:|---:|---:|---:|---|
| NVIDIA | 60,922 | 26,974 | 32,972 | 29,760 | 44,345 | 10,631 | 150/50; 152/52 |
| Apple | 391,035 | 383,285 | 123,216 | 93,736 | 152,987 | 176,392 | 32/29; 34/31 |
| Coca-Cola | 47,061 | 45,754 | 9,992 | 10,649 | 25,997 | 25,249 | 64/62; 66/64 |

| Report | Current end / prior end | Revenue growth | Operating margin | Net margin | Current ratio | Extracted / calculated |
|---|---|---:|---:|---:|---:|---|
| NVIDIA | 2024-01-28 / 2023-01-29 | 125.8545% | 54.1217% | 48.8493% | 4.1713 | 6/6; 4/4 |
| Apple | 2024-09-28 / 2023-09-30 | 2.0220% | 31.5102% | 23.9713% | 0.8673 | 6/6; 4/4 |
| Coca-Cola | 2024-12-31 / 2023-12-31 | 2.8566% | 21.2320% | 22.6281% | 1.0296 | 6/6; 4/4 |

Document identity, official URL, hash, byte length and exact row references:

- [NVIDIA annotations](../tests/fixtures/nvidia_2024/annotations.json), [official report](https://s201.q4cdn.com/141608511/files/doc_financials/2024/ar/NVIDIA-2024-Annual-Report.pdf), SHA-256 `b0de35ded9da9463d5c33dce77cf9b2158b88cf666f144646d0cc64af23c5960`.
- [Apple annotations](../tests/fixtures/apple_2024/annotations.json), [official Form 10-K](https://s2.q4cdn.com/470004039/files/doc_earnings/2024/q4/filing/10-Q4-2024-As-Filed.pdf), SHA-256 `319e1217afe72f194575e63350ea6c813eaf5caf0c24e59ce8b221fc1b3ea0d4`. Despite the CDN filename, the document is the annual Form 10-K.
- [Coca-Cola annotations](../tests/fixtures/coca_cola_2024/annotations.json), [official Form 10-K](https://investors.coca-colacompany.com/_assets/_7083339f2d7f4eaeaf900ef76897f80e/cocacolacompany/db/1007/11020/document/2024_10-K_%28Bookmarked%29.pdf), SHA-256 `96da013cf58c651ae82253c926bfe5bbd1ae63fbcdd4da03efaecf363da11963`.

NVIDIA uses source-backed 52-week context. The other two use consecutive annual
statement headers; raw start dates remain unknown and calculation snapshots
preserve normalized intervals separately. Apple FY2023 is 53 weeks: no
annualization is performed, and unequal lengths are disclosed. Coca-Cola's leap
year also produces the engine's unequal-length warning. Coca-Cola net income is
the consolidated 10,649 including noncontrolling interests; parent-only 10,631
has a different scope and is not substituted. Currency evidence is PDF 157/57,
30/27 and 23/21 respectively. All claims and artifacts remain `pending`.

No primitive extraction failed on the selected three reports. Negative tests
return explicit failures for absent currency, malformed/duplicate headers, absent
or duplicate rows, unsupported headings and missing-value dashes. Accounting
parentheses and Unicode minus signs are normalized deterministically.

An attempted official Microsoft IR PDF download returned HTTP 403 at
`https://microsoft.gcs-web.com/static-files/2e135de7-7104-4bca-b2c4-e584199eabeb`.
It was replaced in source selection by Apple, not silently excluded after a
parsing failure. No synthetic financial fixture was substituted.

## E. Retrieval evaluation

The original fiscal-calendar miss came from ranking of page-window chunks that
buried a short heading/policy among unrelated text. Ingestion now additionally
indexes short source-heading sections. Continuation text remains an actual
contiguous quotation; headings are metadata, not invented quote prefixes. No
company IDs, expected answers, query IDs or labeled pages enter retrieval logic.
Chunk schema 2 uses one shared MiniLM/Chroma collection; the prior index is historical.

| Set | Queries | Hit@5 | Recall@5 | Exact normalized source-anchor coverage |
|---|---:|---:|---:|---:|
| Original Batch 1 NVIDIA development | 10 | 0.90 | 0.90 | Not measured then |
| Same NVIDIA queries, updated chunks | 10 | 1.00 | 1.00 | 0.90 |
| Apple validation | 6 | 1.00 | 1.00 | 0.8333 |
| Coca-Cola validation | 6 | 0.8333 | 0.8333 | 0.8333 |
| Combined new validation | 12 | 0.9167 | 0.9167 | 0.8333 |

Every returned hit passed source-filter and page-locator checks. Relevant printed
labels were checked where labeled; actual financial source-cell page/row/column
locators are also checked by extraction and report validation. Missing document
filters returned no hits. These labels are canonical relevant pages, not an
exhaustive relevance judgment over every possible alternative passage. Recall is
page-label recall, not a claim of complete relevant-document coverage.

Per-query results (`hit / source anchor covered`), including all misses:

| Query ID | Expected PDF page | Top-five PDF pages | Hit / covered |
|---|---:|---|---|
| income-revenue-current | 150 | 150,150,150,147,147 | yes / yes |
| income-revenue-prior | 150 | 150,150,150,33,151 | yes / yes |
| income-operating | 150 | 150,150,150,151,147 | yes / yes |
| income-net | 150 | 150,150,163,150,141 | yes / yes |
| balance-assets | 152 | 152,152,152,173,164 | yes / yes |
| balance-liabilities | 152 | 152,152,152,167,173 | yes / yes |
| calendar | 155 | 155,173,164,162,142 | yes / yes |
| functional-currency | 157 | 157,157,157,144,171 | yes / yes |
| recognition | 155 | 155,155,155,155,138 | yes / yes |
| operating-cash | 154 | 154,154,142,142,143 | yes / **no** |
| apple-sales | 32 | 32,32,25,32,32 | yes / yes |
| apple-operating | 32 | 32,32,32,50,56 | yes / yes |
| apple-net | 32 | 32,50,32,32,31 | yes / yes |
| apple-assets | 34 | 34,34,34,34,32 | yes / yes |
| apple-liabilities | 34 | 34,34,34,34,37 | yes / yes |
| apple-calendar | 37 | 24,4,37,37,24 | yes / **no** |
| coke-revenue | 64 | 64,64,64,118,48 | yes / yes |
| coke-operating | 64 | 64,51,64,64,64 | yes / yes |
| coke-net | 64 | 68,64,118,65,67 | yes / yes |
| coke-assets | 66 | 66,66,66,77,67 | yes / yes |
| coke-liabilities | 66 | 66,66,66,57,90 | yes / yes |
| coke-currency | 23 | 69,124,122,128,122 | **no / no** |

The calendar development miss is fixed without a page-level regression. The cash
and Apple calendar queries find the right page but not the full labeled passage;
Coca-Cola currency remains a semantic-ranking miss. Currency source metadata is
extracted independently from the actual PDF, which explains why financial
provenance can succeed while that natural-language retrieval query misses.

## F. Baseline comparison

The three-case manifest drives both arms with the same question, primary model
ID/settings and shared context policy. Each arm prepares its own actual PDF and
retrieves eight profiles from a warm shared index. Context fingerprints are
checked for equality. Both receive deterministic source-cell metadata as well as
narrative retrieval. This comparison evaluates agent/engine behavior under
equivalent evidence access; it does not measure unaided PDF perception.

The comparator performs one model call and no engine calls. It preserves returned
numbers, locators, abstentions and failures for evaluation without repairing them.
Its mock response computes numbers only in the explicit test double, without
reading gold. Production baseline code does not invoke the financial engine.

For each report, both mocked arms scored 4/4 numerical results, citation coverage
and citation correctness 1.0, six source values present, zero unsupported reported
claims, zero missing/abstained calculations and six section headings present.
These are **offline harness results, not empirical LLM accuracy measurements**.
Section completeness measures presence, not quality: Apple/Coca-Cola company
overview extraction is absent and disclosed. Numerical tolerance is the same
0.00005 absolute threshold in displayed output units for both arms; citation
correctness requires resolvable support consistent with the reported number.

Per report: MAFIS makes six mocked calls, eight retrieval calls and four engine
calls; baseline makes one mocked call, eight retrieval calls and zero engine
calls. Tokens are null because mocks expose none. API generation cost is exactly
zero in mock mode; no live cost or estimated price was invented. The harness can
accept explicit pricing rates when usage is available. Real billed cost requires
external billing records. Run-level wall times and stage timings are in each
manifest and are local offline measurements, not model speed comparisons.

Final fresh three-case batch measurements (seconds, one run per arm):

| Report | Identical context | MAFIS end-to-end | Baseline end-to-end | MAFIS / baseline correct |
|---|---|---:|---:|---|
| NVIDIA | yes | 39.472 | 36.502 | 4/4 / 4/4 |
| Apple | yes | 29.510 | 28.369 | 4/4 / 4/4 |
| Coca-Cola | yes | 44.260 | 41.804 | 4/4 / 4/4 |

The final batch completed without pipeline failures. Totals: 18 mocked MAFIS
calls, 3 mocked baseline calls, 24 retrieval calls per arm, 12 MAFIS engine
calculations, zero baseline engine calls. All six run IDs differ. The full test
suite ran concurrently using isolated test indexes, so these times also include
local CPU contention; no latency superiority claim is justified.

The initial batch had one Chroma `InternalError: Error finding id` on Coca-Cola;
the failed attempt is preserved in `comparison_initial.json`. A fresh-process
Coca-Cola run and final three-case batch completed without changing its source or expected answers. Storage
errors now become explicit `RetrievalUnavailable` failures rather than invented
results. No root cause has been established; this remains operational debt.

Every manifest records run IDs, source hash, dataset identity, mode, model/settings,
prompt/context versions, index configuration, package versions, timing, usage,
failures, limitations and artifact paths. UUIDs and times differ on replay;
deterministic source values and engine results reproduce. Live stochastic outputs
are not promised to be identical. Empirical live comparison remains pending.

## G. Tests executed

Commands run from the repository root with Python 3.12:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_multi_report.py tests/test_ingest.py tests/test_financial_engine.py tests/test_shared_memory.py -q
# 174 passed in 36.93s; 0 failed, 0 skipped
.\.venv\Scripts\python.exe -m pytest tests/test_evaluation.py tests/test_report_agent.py -q
# 16 passed in 78.22s; 0 failed, 0 skipped
.\.venv\Scripts\python.exe -m pytest tests/test_multi_report.py tests/test_retrieval.py -q
# 53 passed in 57.60s before the final three index-failure tests were added
.\.venv\Scripts\python.exe -m pytest -q
# 286 passed in 189.68s; 0 failed, 0 skipped
.\.venv\Scripts\python.exe -m pip check
# No broken requirements found
git diff --check
# Exit 0; Git emitted only LF/CRLF normalization notices
.\.venv\Scripts\python.exe -m scripts.live_readiness
.\.venv\Scripts\python.exe -m scripts.evaluate_retrieval
.\.venv\Scripts\python.exe -m evaluation.run --mode mock
```

All original 234 tests remain; 52 additional tests cover real new reports and
evaluation/failure behavior. The final full suite includes the final Chroma
failure tests and all sign/header/row tests. No test was skipped or weakened.
Most unit retrieval tests use explicitly mocked embeddings to remain offline;
the saved retrieval benchmark and full acceptance runs use the real local MiniLM
model and real Chroma. All Gemini responses in pipeline tests are mocked.
The post-run artifact audit additionally resolved all exact calculation-input
versions across 31 claims and 12 artifacts, checked six distinct run IDs and
identical arm contexts, and confirmed every stored claim/artifact remains pending.

## H. Official v1.1 exit criteria

| Official criterion | Status | Actual evidence |
|---|---|---|
| Pipeline runs end-to-end on 3–5 real reports | PARTIAL | Three actual issuer PDFs complete the offline graph; live model flow has not been validated. |
| Core claims represented in structured Shared Memory | PASS | Three evidence exports; append-only/version/isolation tests. |
| Every numeric report claim traces to evidence and derived numbers to calculation references | PASS within tested runs | ReportAgent revalidates current claims, exact source cells, engine replay and source-calendar context; report/citation tampering tests reject forged inputs. |
| No numeric report result from free-form LLM arithmetic | PASS for MAFIS | Four allowlisted engine artifacts per report; Financial Agent proposal/interpretation validation and deterministic renderer. Single-LLM arithmetic belongs only to the separately labeled comparator. |
| Calculation inputs/outputs pass sanity checks or reject explicitly | PASS | Engine validation/replay/adversarial tests and twelve actual source calculations. |
| Small retrieval set with known relevant passages/pages | PASS | Original ten development plus twelve separate validation labels and measured per-query outputs, including remaining misses. |
| Single-LLM baseline can run on same inputs | PASS for executability | All three input cases use the same settings/context policy, with context fingerprint checks. Empirical live quality remains pending under Stages 1/4. |

The 12 Stage 5 integration properties are covered by pipeline/report/engine
tests and three-case artifacts: exact calculation inputs, provenance, current
versions, absence of unsupported numbers, disclosed missing evidence, pending
verification, safe partial failures, multiple companies, isolated run stores,
backward compatibility and executable baseline. This does not substitute for the
missing real-model smoke test or establish universal PDF compatibility.

## I. Limitations and technical debt

- Live generation and actual quotas are unvalidated; model metadata is only readiness evidence.
- Three supported English born-digital layouts are not general PDF extraction. OCR, scanned pages, multi-page tables, other currencies, restatements, segment/standalone variants and quarterly comparisons remain unsupported.
- Annual-header normalization assumes consecutive annual periods within the existing engine bounds. It does not infer missing restatement or transition-year semantics. Source starts and normalized starts remain separate.
- Narrow explicit currency phrases limit new-document compatibility; dollar symbols alone remain insufficient.
- Residual retrieval passage/currency misses are preserved. A larger frozen held-out set is needed before tuning further; the validation set should not become an undisclosed development set.
- Chroma had an intermittent internal-ID failure. Diagnose index lifecycle/concurrent writer behavior before operational use; do not silently reset evidence or claim the root cause is fixed.
- Eight-profile context collection and repeated PDF preparation are intentionally simple, with measurable overhead. Warm-index, single-order timings are not a fair latency study and imply no speed advantage.
- Evaluation measures typed reported claims and section presence, not broad prose quality, completeness of all corporate risks, or independent truth. No Phase 4 ablation or statistical claim is made.
- All source claims and calculations remain pending independent verification. Single-source support is not a verification result. Shared Memory is still in-process; full dependency invalidation and persistence are deferred.
- Generated outputs are local ignored files; rerun the supplied commands to reproduce them elsewhere. Fixture PDFs and canonical gold/specification files are not ignored.

## J. Recommended Phase 2 starting plan — not implemented

1. Close the Phase 1 external acceptance gap: independently confirm project free tier and remaining quota, run the bounded NVIDIA structured-output smoke, then the same frozen three-case principal comparison. Record real failures, usage and costs without changing the test manifest to favor either arm.
2. After user review authorizes Phase 2, establish verification against fresh source retrieval and deterministic artifact replay. Use existing exact run/claim/version references; append verification revisions and preserve pending/unsupported/unresolved distinctions. Add injected source, period, unit and stale-input errors before changing graph routes.
3. Implement Market's bounded, timestamped public-source research through the existing shared retrieval/tool layer. Store descriptive source-linked findings with source identity and as-of periods; preserve source access failures.
4. Build Risk on existing Financial artifacts plus Market claim references. Retrieve direct risk evidence only for specific gaps; do not re-calculate existing ratios. Extend claim-type-aware verification to financial/market/risk interpretations and their pinned dependencies.
5. Only in the separately authorized Phase 2 work, wire the approved Verification Health Gate, calibrate configurable signals on deliberately degraded validation runs, and surface unsupported findings in reports. Preserve the shared retry cap; full adaptive re-analysis remains Phase 3.

No Phase 2 implementation has begun. Stop boundary: final Phase 1 report for user review.
