# MAFIS closeout evaluation results

Research question: does structured evidence verification, deterministic arithmetic,
adversarial interpretation and a bounded correction improve reliability relative
to a single-model call? This closeout establishes bounded engineering behavior and
mock harness execution. It does not establish empirical superiority.

The implementation retains Planner -> Document -> primitive verification -> Financial
and dated Market -> verification -> Risk -> verification -> Health Gate -> Bull/Bear ?
argument traceability -> mechanical Critic -> one Planner-owned targeted correction
when needed -> authoritative map and deterministic report. The old entry points keep
their scope. Market/Risk are bounded deterministic screens; Bull/Bear select qualified
interpretations, and Critic covers explicit structured rules, not unrestricted prose.

## Dataset and source coverage

Thirteen source slots contain ten actual official PDFs and three blocked downloads.
Seven documents admit six primitives each: 42 source-matching values and 28 correct
engine operations, up from 18 primitives/12 operations on the original three.
Across local PDFs, 59 numeric rows were source-inspected against 60 requested rows;
several lack admissible currency/context. These are not 10 supported formats.
All 52 requested numerical output slots across 13 cases remain in the accounting;
39 have source-inspected operation inputs, 13 have unavailable gold (blocked sources
or Nike operating income). Missing outputs are never counted correct.

| Document | Current split | Inspected rows | Prior extracted (reviewed Batch2) | Now extracted | Correct operations | PDF statement pages | Status/failure |
|---|---|---:|---:|---:|---:|---|---|
| nvidia_2024 | development | 6 | 6 | 6 | 4/4 | 150,152 | supported |
| apple_2024 | development | 6 | 6 | 6 | 4/4 | 32,34 | supported |
| coca_cola_2024 | development | 6 | 6 | 6 | 4/4 | 64,66 | supported |
| intel_2024 | validation | 6 | 0 | 0 | 0/4 | 65,67 (inspected) | missing_currency |
| microsoft_2024 | validation | unknown | 0 | 0 | 0/4 | unavailable | source_unavailable |
| walmart_2024 | validation | 6 | 0 | 0 | 0/4 | 56,58 (inspected) | missing_statement, unsupported_text_encoding |
| alphabet_2024 | test | unknown | 0 | 0 | 0/4 | unavailable | source_unavailable |
| nike_2024 | test | 5 | 0 | 0 | 0/4 | 60,62 (inspected) | missing_currency |
| amazon_2024 | development | 6 | 0 | 6 | 4/4 | 49,51 | supported |
| pepsico_2024 | development | 6 | 0 | 6 | 4/4 | 73,77 | supported |
| netflix_2024 | test | unknown | 0 | 0 | 0/4 | unavailable | source_unavailable |
| meta_2024 | development | 6 | 0 | 6 | 4/4 | 88,89 | supported |
| amd_2024 | validation | 6 | 0 | 6 | 4/4 | 75,77 | supported |

Original PDF bytes and the three original gold hashes were rechecked unchanged.
New complete annotations are AI source-inspected, not human-reviewed. They retain
source URLs/hashes, entity/scope, fiscal headers, scale/currency, raw row quotations,
geometry, page/table/column locators and ambiguities. Gold is opened after inference.
Amazon, Meta and PepsiCo moved explicitly from test to development for parser work;
the original assignments/exposure remain recorded. AMD is validation/parser-development
material. Nike was not tuned on its closeout failure. No untouched held-out model-quality
result is claimed. See [case manifest](../tests/fixtures/batch2_cases.json) and
[exact source references](../output/final_closeout/source_coverage_final.json).

Intel's native glyphs are now readable and signed-row parsing is supported, but its
reporting currency remains unestablished; sales currency is insufficient. Walmart
has no ToUnicode or embedded Unicode cmap in inspected statement fonts; no arbitrary
glyph guessing/OCR was added. Nike has no separately reported operating-income row
and fails current currency admission. Its value was not manufactured from other lines.
Microsoft, Alphabet and Netflix download failures remain retained.

| Document | Revenue growth % | Operating margin % | Net margin % | Current ratio |
|---|---:|---:|---:|---:|
| nvidia_2024 | 125.8545 | 54.1217 | 48.8493 | 4.1713 |
| apple_2024 | 2.0220 | 31.5102 | 23.9713 | 0.8673 |
| coca_cola_2024 | 2.8566 | 21.2320 | 22.6281 | 1.0296 |
| amazon_2024 | 10.9909 | 10.7519 | 9.2871 | 1.0637 |
| pepsico_2024 | 0.4187 | 14.0299 | 10.4797 | 0.8189 |
| meta_2024 | 21.9411 | 42.1760 | 37.9086 | 2.9779 |
| amd_2024 | 13.6905 | 7.3686 | 6.3642 | 2.6163 |

## Measured execution

Default root suite: **575 passed in 1864.47s (0:31:04)**, exit 0. No tests skipped/deselected or removed.
Eight real-PDF/Chroma/MiniLM offline demonstrations completed: four clean reports,
one successful targeted correction, persistent partial failure, irrecoverable
blocked evidence, and compatible opposing interpretations. Exact current calculation
inputs/dependencies and consecutive verification history were checked in exports.

All eight conditions ran on seven admitted documents (56 completed conditions).
Six source cases generated 48 explicit preparation-failure records. The table's
28/52 is correct known outputs per requested slot, not an accuracy claim on unknown
gold; among returned scorable outputs it is 28/28. All arithmetic/model responses
here are explicit test doubles. Equal mock results cannot establish model quality.

| Condition | Completed | Source failures | Correct/requested slots | Mock logical requests | Mean local inference seconds |
|---|---:|---:|---:|---:|---:|
| full | 7 | 6 | 28/52 | 56 | 24.147 |
| single_llm | 7 | 6 | 28/52 | 7 | 0.007 |
| without_verification | 7 | 6 | 28/52 | 63 | 1.202 |
| without_bull_bear | 7 | 6 | 28/52 | 42 | 24.092 |
| without_critic | 7 | 6 | 28/52 | 56 | 23.601 |
| without_reanalysis | 7 | 6 | 28/52 | 56 | 24.272 |
| without_engine | 7 | 6 | 28/52 | 28 | 2.261 |
| unified_analyst | 7 | 6 | 28/52 | 21 | 13.577 |

Experimental unchecked results never forge verification records; no-engine results
create no deterministic artifacts; baseline is one call without engine/Verifier/
Critic; unified analysis consolidates selection/planning and retains engine access.
Removing Critic or re-analysis changes those execution paths, including when clean
inputs would not otherwise trigger their calls. See manifests and request traces.

Principal arms share a pre-inference source bundle, exact mock/model settings,
question and dated Fed pool. Full agents have additional scoped retrieval: comparable
source access, not identical role contexts. All seven offline pairs pass that policy;
there is no completed live pair. Source/context/configuration/split hashes, dirty-code
identity, retries, stage timings and current-condition telemetry remain in manifests.

Real MiniLM Hit@5/page recall: 28/30 labelled queries. Representative
anchor passage coverage: 26/30, separately measured. Two page misses
were Coke currency and AMD income; NVIDIA operating-cash and Apple calendar hit their
pages without the labelled anchor. Six unindexed/unadmitted cases remain explicitly
unmeasured for this retrieval study. Page hits and reference membership are not
semantic citation correctness or analytical depth.

Injected verification: {'tp': 8, 'fp': 0, 'fn': 0, 'tn': 1, 'precision': 1.0, 'recall': 1.0, 'compatible_false_positive_rate': 0.0, 'count': 9}; contradictions:
{'tp': 7, 'fp': 0, 'fn': 0, 'tn': 5, 'precision': 1.0, 'recall': 1.0, 'compatible_false_positive_rate': 0.0, 'count': 12}. These small labelled fixtures test implemented
rules, not broad natural-language accuracy. The threshold study remains injected-only;
production retains its explicitly uncalibrated engineering default 0.5. Labels are
support categories, not calibrated probabilities. Broad semantic support and probability
calibration remain unavailable.

Local timings include real retrieval under concurrent validation load, not controlled
latency benchmarking or live model latency. Mock token usage/cost is not provider usage.
The live attempt returned no tokens; actual billing and cost estimates remain unknown.

## Live and human status

One `gemini-3.8-flash` comparator/readiness attempt returned HTTP503 after
3.890 seconds. Settings: temperature 0, output cap 8192, timeout 60000ms, transport
retries 0. The shared persisted 12-attempt ledger halted at 1/12; full arm/ablations
were not started. Historical HTTP504 failures remain historical. Metadata access
and a documented [model free tier](https://ai.google.dev/gemini-api/docs/pricing)
do not establish generation access or independently observed project billing;
free-tier project status is user attestation. No credential/quota/schema diagnosis
or superiority claim follows from these server failures.

Fourteen anonymous mock reports, a separate private mapping, rubric and blank CSV
are exported. Imported completed human ratings: zero. Two independent reviewers must
inspect reports/source PDFs and supply ratings; no human quality result is claimed.
Mechanism disclosures/styles may reveal arms even after names are removed.

Engineering corrections and feasible offline validation are complete within the
bounded scope. Broader source-format support, a successful live paired experiment,
live ablations, real-data threshold validation and blind human review remain incomplete.
See [handoff](../output/final_closeout/final-handoff.md) and [commands](README.md).
