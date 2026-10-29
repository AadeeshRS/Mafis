# Batch 2 evaluation

Run from the repository root with the existing environment:

```powershell
.\.venv\Scripts\python.exe -m evaluation.batch2 --output output/batch2/evaluation_reproduce
.\.venv\Scripts\python.exe -m evaluation.mechanisms
.\.venv\Scripts\python.exe -m evaluation.dataset
```

The first command executes all eight conditions over three previously exposed
development PDFs and the same official Fed snapshot. It uses explicit offline
doubles and hash embeddings by default (`--real-embeddings` selects MiniLM).
Conditions remove actual calls/stages: Verification, Bull/Bear, Critic, correction,
engine, or specialist extraction/operation selection. Experimental unchecked/model
numeric outputs use isolated renderers and never forge checked records/artifacts.
The no-engine pathway retains source checking, generates model arithmetic, and
cannot claim artifact-backed financial risk. Unified analysis selects cells and
operations in one call and uses the ordinary deterministic tool afterward.
Its current correction coverage and the unchecked pathway's reduced downstream
eligibility must be disclosed when interpreting interventions.

The principal comparator makes one call with no engine, verifier or Critic. A
common source bundle is built before either arm, including dated market context.
Full agents perform additional scoped retrieval, so the pairing is comparable
source access, not identical retrieved contexts. Pair validation checks actual
adapter/settings identity, bundle fingerprint, question and temporal/risk scope.
Failures stay in results and invalid pairs stay out of paired claims. Gold is
opened only after inference; production agents never load annotation files.

Numerical accuracy has four requested operations per development case; abstention
or missing output is incorrect, not success. The independent oracle uses Fraction/
Decimal arithmetic. Citation correctness checks retrieved evidence rather than
mere citation presence. Retrieval Hit/Recall/passages are unavailable for the
combined bundle unless query-specific relevant labels exist. Zero denominators,
unavailable tokens/cost and probability calibration are `null`, never invented.
The injected-study utility reports actual confusion matrices for labelled checks;
its threshold grid/objective is fixed before evaluation and writes an immutable
validation-only record. That injected operating point is not real-world calibration
and does not replace production's uncalibrated engineering default of 0.5.

`dataset` freezes a 12-slot inventory (3 development, 3 validation, 6 test) before
held-out scoring and records each official download attempt/hash. Downloaded
candidates are not automatically gold. Unsupported layouts and blocked downloads
remain in the accounting. No held-out quality claim is justified until all needed
source inspections and scoring are complete. No test-driven extractor tuning is
performed by this harness.

Exports include per-condition manifests, evidence/model fingerprints, dirty code
identity, telemetry, failures, paired-context validity and blind-review materials.
The anonymous reports and blank ratings are separate from the private arm mapping.
`human_materials` and `import_ratings` prepare/import actual ratings; blank templates
are not evidence that human review occurred. Reviewer access must exclude the
private mapping and original outputs. Visible content may still reveal mechanisms;
blindness cannot be guaranteed solely by removing arm labels.

These commands validate offline mechanisms and experiment plumbing. Live quality,
live ablation superiority and human review remain pending unless separately measured.

Unified analysis uses the same Planner-owned correction budget. The unchecked
condition can correct source/operation gaps once without creating check records;
its missing-check Critic findings are intentional and irrecoverable in that condition.
No-engine arithmetic stays experimental and cannot supply artifact-backed financial
risk or independently checked numerical arguments. These differences are recorded,
not presented as clean live causal estimates of an isolated architectural effect.

`tests/fixtures/batch2_cases.json` retains the original 12 assignments and adds AMD
as a reserve validation source after Microsoft's HTTP 403. It accounts for ten
actual official PDFs and three unavailable source slots. Seven new candidates have
AI source-inspected annotation files; Nike lacks a separately reported operating
income row, and explicit currency context remains incomplete for Intel/Walmart.
These are candidate annotations, not human-reviewed gold. Offline source-profile
probes accepted zero primitives from all seven new layouts; no extraction tuning
followed. Primary model-quality inference remains limited to the three exposed
development cases. Scientific held-out evaluation remains incomplete.

Additional commands:

```powershell
.\.venv\Scripts\python.exe -m evaluation.dataset --include-reserve --output output/batch2/dataset_reproduce
.\.venv\Scripts\python.exe -m evaluation.source_coverage
.\.venv\Scripts\python.exe -m evaluation.retrieval_study
```

Retrieval scoring runs after inference against the existing real MiniLM demo index.
Hit@5 and Recall@5 use labelled source pages; representative anchor passage coverage
is measured separately. These previously exposed queries are development measurements,
not untouched test evidence. The default common experiment has no availability cutoff
because annual filings lack publication metadata. It retains historical source dates
and records that limitation; explicitly supplied cutoffs still fail unavailable or
undated source contexts strictly.


## Final closeout commands and interpretation

Historical zero-extraction probes above preceded closeout parsing changes. Current
per-document outcomes, split changes and limitations are in [results](results.md).
AMD validation annotations and Amazon/Meta/PepsiCo development annotations were
source-inspected by AI, not human-reviewed. The latter three were reclassified from
test to development; their original assignments remain recorded. Original PDF bytes
and the original three gold files are preserved.

```powershell
.\.venv\Scripts\python.exe -m evaluation.batch2 --cases tests/fixtures/batch2_cases.json --split all --real-embeddings --output output/final_closeout/offline_reproduce
.\.venv\Scripts\python.exe -m evaluation.batch2 --cases tests/fixtures/batch2_cases.json --split validation --case-ids amd_2024 --conditions full single_llm --real-embeddings --output output/final_closeout/selected_offline
```

All eight conditions execute by default. `--conditions` selects a subset and
`--case-ids` bounds documents. Blocked/unannotated sources remain explicit failed
records, with four requested numerical outputs in the accounting; an all-source
matrix can correctly exit 1. Results checkpoint after each condition.

A bounded live invocation uses the same exact adapter/settings for both arms:

```powershell
.\.venv\Scripts\python.exe -m evaluation.batch2 --cases tests/fixtures/batch2_cases.json --split validation --case-ids amd_2024 --conditions single_llm full --live --model gemini-3.8-flash --real-embeddings --live-budget output/final_closeout/live_budget.json --output output/final_closeout/live_pair
```

Generation is opt-in. Use a model whose current availability and free-tier status
have been inspected; project billing itself is not independently observed. The
first baseline call doubles as structured-readiness testing. A principal pair
requires at least nine remaining attempts before starting; all adapters share a
persisted twelve-attempt ledger, including failures. SDK transport retries are
zero. The closeout ledger is already halted after HTTP503 at 1/12: do not reset it
or substitute another ledger to resume probing under this authorization.

`condition_telemetry.json` and manifest usage contain only that condition's slice.
Injected SDK clients are test execution even when `allow_live=True`. Native live
success, failed live attempts, disabled clients, tagged mocks and unknown adapters
remain distinct. Missing tokens/billing are null. Pricing estimates require dated,
model-matching explicit inputs; no estimate is inferred from mock timings. Prompt/
payload fingerprints and available chunk IDs permit checking actual context access;
principal arms have comparable access, not identical role retrieval contexts.

For blind review, give two reviewers separate copies of `ratings_blank.csv` and the
anonymous reports/rubric; keep the arm mapping outside their packet. Each reviewer
fills their own identifier and 1?5 ratings independently, using source evidence to
check factual content. Combine completed CSV rows with one header, then run:

```powershell
.\.venv\Scripts\python.exe -c "from evaluation.batch2 import import_ratings; import json; print(json.dumps(import_ratings('path/to/completed_ratings.csv'), indent=2))"
```

Do not replace blanks with automatic ratings. A mock-only packet tests the review
workflow and does not constitute a live model-quality experiment. Reviewer knowledge
of provenance may reveal mechanism differences; anonymity does not guarantee blindness.


Principal live-pair admission is checked separately for every selected company,
before either principal arm or source preparation starts. The declared clean path
is one baseline attempt plus eight full-flow attempts (nine total). Underfunded pairs
produce two `executed: false` manifests and an unexecuted/invalid pair record without
spending any calls. Baseline/full run consecutively before other selected conditions;
provider failure still halts remaining generation. Single-condition and offline
selections retain their execution behavior. CLI summaries separate `condition_records`,
`conditions_executed`, `conditions_completed` and `conditions_unexecuted`; lifetime
`live_attempts` and this-invocation attempts are separate. No ledger is reset.
