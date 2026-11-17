# MAFIS slide blueprint

16 slides, 16:9. Poppins. Deep green (#013230), cream (#F3EBDD) and orange (#FF6A1F).

Sources: current implementation, saved workflow runs and the offline evaluation records. Course rubric: `report things/Final Guidelines.docx.pdf`.

## 01. MAFIS

**Layout:** Dark cover with title and two results.

**Placement:** Project scope on the left, Apple demo and retrieval findings on the right.

**Exact visible text** (46 words):

```text
ARTIFICIAL INTELLIGENCE COURSE PROJECT
MAFIS
Multi-Agent Financial
Intelligence System
Cited filing answers with local DeepSeek-R1 and a deterministic financial engine.
4/4
fully supported results in the Apple demo vs 0/4 for single DeepSeek
28/30
labelled queries found the right PDF page in the top five
01
```

**Speaker notes:** MAFIS takes a question and a company filing and gives the reader a cited answer. A disclosure question can return checked excerpts, while a financial analysis can trace its calculations to filing cells. I'll show how we assign those cells to calculations, what happens when a required cell is missing, and what we measured in the Apple FY2024 demonstration. Both workflows ran local DeepSeek-R1. Full MAFIS delivered four results with correct values and inputs, and the single-call baseline delivered zero. The saved runs use one development filing.

**Sources:** `report things/MAFIS Project Report.docx` · `Readme.md` · `agents/question_answer.py` · `output/test_lab/dashboard/336dbc93d17f41c7843b48d93f49f153/benchmark.json` · `evaluation/results.md`

## 02. The correct row can contain the wrong answer

**Layout:** Problem and example above an objective band.

**Placement:** Question, source ambiguity and supported outputs appear in two columns.

**Exact visible text** (90 words):

```text
INTRODUCTION
The correct row can contain the wrong answer
Task
Answer questions about a filing. Full financial analysis also draws on dated market context.
A concrete risk
The NVIDIA revenue row contains FY2024, FY2023 and FY2022. The chosen cell must match the requested fiscal period.
Four financial calculations
Annual revenue growth, operating margin, net margin and the current ratio.
Design objective
Link each answer to filing evidence. Show which inputs or disclosures the source leaves unavailable.
Can source checks, exact arithmetic and a targeted correction improve annual filing analysis?
02
```

**Speaker notes:** A filing row can contain several years. Finding the revenue row is only the first step. For the NVIDIA example, the system also needs to choose the right fiscal column and preserve the scale in millions. A balance-sheet number is a position on a date, while income describes activity over a period. For a disclosure question, the answer is drawn from verified passages. We compare the full financial workflow against a single model call on common source material.

**Sources:** `report things/MAFIS Project Report.docx` · `graph.py` · `agents/question_answer.py` · `tests/fixtures/nvidia_2024/annual_report.pdf`

## 03. How MAFIS relates to prior financial QA work

**Layout:** Three-column comparison table.

**Placement:** Six papers from report Table 1, compared with the matching design choice in MAFIS.

**Exact visible text** (96 words):

```text
LITERATURE REVIEW
How MAFIS relates to prior financial QA work
Related work
Technique or focus
MAFIS design choice
FinQA (2021)
Annotated numerical reasoning
Fixed operations and exact input versions
FinanceBench (2023)
Questions with reference evidence
Source-based scoring on local filings
FinRAGBench-V (2025)
Retrieval with visual citations
Page and bounding-box locators
FinDebate (2025)
Specialist analysis and debate
Checked Bull/Bear views and Critic rules
FinRank (2026)
Ranking confusable SEC passages
Source and fiscal-period constraints
CLAIR-Fin (2026)
Claim ledger and adaptive rebuttal
Versioned claims and one shared retry
The course experiment uses its own single-call and unified-analyst baselines.
03
```

**Speaker notes:** FinQA and FinanceBench give examples of evaluating reasoning and checking evidence. FinRAGBench-V and FinRank focus on evidence location and confusing alternatives. FinDebate and CLAIR-Fin are closer to our workflow. We use two interpretations of the same verified evidence and a mechanical Critic. These studies use different benchmarks, so our comparison here is about the technique.

**Sources:** `report things/MAFIS Project Report.docx` · <https://aclanthology.org/2021.emnlp-main.300/> · <https://arxiv.org/abs/2311.11944> · <https://aclanthology.org/2025.emnlp-main.211/> · <https://aclanthology.org/2025.finnlp-2.20/> · <https://arxiv.org/abs/2608.07400> · <https://aclanthology.org/2026.finnlp-1.41/>

## 04. A state graph routes each filing question

**Layout:** State notation above three stages and a search explanation.

**Placement:** Editable state tuple, transition chain and search comparison.

**Exact visible text** (76 words):

```text
METHODOLOGY / STATE-SPACE SEARCH
A state graph routes each filing question
S = (q, d, p, M, g, b, i)
Question, document, plan, SharedMemory,
gate decision, retry budget, issues
Initial state
Graph transitions
Terminal state
Question and document
Fresh run store
Route the question, retrieve,
verify and calculate if needed
Cited answer and report
Evidence gaps when applicable
Where search happens
LangGraph follows prescribed stages and checks branch conditions. SharedRetriever ranks evidence by cosine distance.
04
```

**Speaker notes:** This is the report's state-space abstraction of ExtendedState. We start with a question, its document descriptor and a fresh run store. Every transition changes the plan, evidence, verification status or retry budget. The Test Lab routes a disclosure question to document lookup. The financial path plans requested facts and operations. Both routes end with a cited answer or a record of what evidence is missing. The system searches the evidence index by cosine distance, so BFS over alternative workflows would solve a different problem.

**Sources:** `report things/MAFIS Project Report.docx` · `graph.py` · `agents/planner.py::PlannerAgent` · `scripts/test_lab.py::sample_run` · `rag/retriever.py::SharedRetriever`

## 05. Versioned claims preserve the evidence chain

**Layout:** Index records and analytical records in parallel columns.

**Placement:** Two record types above a four-node provenance chain.

**Exact visible text** (96 words):

```text
METHODOLOGY / KNOWLEDGE REPRESENTATION
Versioned claims preserve the evidence chain
Retrieval index
SourceChunk holds page-bounded text. TableCell adds typed values, fiscal headers and source locators.
Run ledger
ClaimVersionRef binds a run ID, claim ID and version. VerificationRecord and CalculationArtifact retain the evidence trail.
A financial primitive records
Metric, value, entity, currency, scale, fiscal period and accounting scope.
The source link records
PDF page, printed page, quoted text, bounding box and table row or column.
Filing cell
Verified claim
version
Calculation
artifact
Report entry
The eligibility check follows the current claim and every dependency it cites.
05
```

**Speaker notes:** The index holds chunks for finding candidate evidence. The ledger holds the claims we can verify and the version each calculation used. A record includes its fiscal period, scale and exact source location. When a claim is revised, the old version remains in the ledger. is_current_verified checks that the referenced claim and its dependencies are still current before the result can support the report.

**Sources:** `report things/MAFIS Project Report.docx` · `rag/models.py` · `memory/shared_memory.py`

## 06. NVIDIA revenue growth as a CSP

**Layout:** Report figure above an input-assignment table and formula.

**Placement:** The report’s NVIDIA income statement excerpt sits above the editable constraints and worked result.

**Exact visible text** (107 words):

```text
METHODOLOGY / CONSTRAINT SATISFACTION
NVIDIA revenue growth as a CSP
NVIDIA annual report, PDF page 150 (printed page 50)
Variable
Assigned cell
Admissibility
Current revenue
60,922 · FY2024
Same entity, scope and USD scale
Previous revenue
26,974 · FY2023
Adjacent fiscal year, positive denominator
Input domain  ·  Verified primitive claim versions in this run
(60,922 − 26,974) ÷ 26,974 × 100 = 125.8545%   ·   Swapping the years fails the period check.
06
NVIDIA Corporation and Subsidiaries. Consolidated Statements of Income. In millions, except per share data. Year Ended. Jan 28, 2024. Jan 29, 2023. Jan 30, 2022. Revenue $60,922 $26,974 $26,914. Cost of revenue 16,621 11,618 9,439.
```

**Speaker notes:** The operation is annual revenue growth. The variables are the current and previous revenue inputs. Their domain is the checked primitive references in this run. Both cells belong to NVIDIA's consolidated income statement. They have comparable adjacent annual periods, the same currency and scale, and the previous revenue is positive. Switching the two cells fails the period-role check. The engine validates the selected pair with Boolean rules.

**Sources:** `report things/MAFIS Project Report.docx` · `engine/financial_engine.py::_prepare` · `tests/fixtures/nvidia_2024/annual_report.pdf, PDF page 150` · `evaluation/results.md`

## 07. The retriever preserves fiscal context

**Layout:** Four-stage pipeline above retrieval settings.

**Placement:** Editable source-to-selection workflow and paired interpretation of retrieval parameters.

**Exact visible text** (112 words):

```text
IMPLEMENTATION / DOCUMENT PREPARATION
The retriever preserves fiscal context
Parse PDF
Chunk text
and tables
Filter and
rank in Chroma
Select cells
and quotations
Narrative windows
Page text 900 characters with 150 overlap. Section text 800 characters with 100 overlap.
Structured table chunks
Retain the exact statement row, fiscal header, units and source locator.
Text embeddings
all-MiniLM-L6-v2 runs on CPU. Chroma ranks by cosine distance within document and task filters.
Retrieval limits
Analysis uses up to 3 hits per narrative query and 5 per table query. Document Q&A selects up to 3 excerpts from 5 narrative hits.
MiniLM and the generation models run inference. The project uses no training or fine-tuning.
07
```

**Speaker notes:** The parser reads born-digital annual filings. Narrative windows preserve page boundaries and table chunks retain headers, typed cells and evidence locations. The Apple benchmark uses all-MiniLM-L6-v2 text embeddings through ONNX on the CPU. DeepSeek-R1 handles generation and selection on this machine. Chroma ranks by cosine distance after applying metadata filters. Structured analysis uses a schema-bound choice of cells and quotes. In document lookup, the model chooses up to three excerpt IDs from the five retrieved narrative chunks. The code resolves the IDs to verbatim text and the verifier checks the citation.

**Sources:** `report things/MAFIS Project Report.docx` · `config.py::EMBEDDING_MODEL` · `rag/ingest.py::prepare_document` · `rag/retriever.py::SharedRetriever` · `agents/document_agent.py::collect_context`

## 08. Verification determines the next stage

**Layout:** Two-row workflow recreated from report Figure 1.

**Placement:** The main diagram shows full financial analysis. A separate strip summarizes document Q&A.

**Exact visible text** (76 words):

```text
IMPLEMENTATION / WORKFLOW
Verification determines the next stage
Planner
Set scope
Prepare PDF
Parse + index
DocumentAgent
Select + verify
Financial, Market, Risk
Check findings
Health Gate
Test eligibility
Pass
Blocked
Bull, Bear, Critic
Interpret + check
Planner decision
At most one retry
Targeted correction
Rerun affected stages
Analysis map + report
Findings and gaps
No retry needed or available
Document Q&A   Retrieve passages → select excerpts → verify wording and pages → cited answer.
08
```

**Speaker notes:** Planner decides scope, then we prepare the filing and select and verify its primitives. Financial and dated Market findings feed Risk, which is also verified. The gate checks the current evidence. If it passes, Bull and Bear use the same checked claims and Critic tests their structured assertions. A blocked gate routes straight to Planner. A retry reruns affected dependencies. Early planning or ingestion failures route to the gate. In document Q&A, the verifier checks the selected quotations before the report and answer use them. Test Lab shows the answer and offers the Markdown report for download. Its Shared Memory feed displays committed claims, calculation artifacts and stage events as the run proceeds.

**Sources:** `report things/MAFIS Project Report.docx` · `graph.py` · `agents/full_workflow.py` · `agents/report_agent.py` · `agents/question_answer.py` · `dashboard/server.py` · `memory/live_feed.py`

## 09. Models propose. Rules decide eligibility.

**Layout:** Two responsibility columns above a settings strip.

**Placement:** Left presents model roles. Right presents arithmetic, screening and routing checks.

**Exact visible text** (103 words):

```text
IMPLEMENTATION / AGENTS AND SETTINGS
Models propose. Rules decide eligibility.
Model calls
Document and Financial agents propose source cells and operations. Bull and Bear propose interpretations from one checked snapshot.
Deterministic checks
Verification can replay 50-digit Decimal calculations. The Critic applies conflict rules to typed claims.
Local Ollama · deepseek-r1:8b
4,096-token context and 8 KiB JSON request limit. Compact IDs resolve to exact filing references.
Demo settings for both arms
Temperature 0, thinking disabled, 1,024 output tokens per request. Gemini is an opt-in cloud path.
Health Gate blocks above 0.5 ineligible, on empty evidence or on explicit upstream issues. One analytical retry.
09
```

**Speaker notes:** DocumentAgent selects filing cells. FinancialAgent selects allowed operations. The Bull and Bear agents use the same verified snapshot, and an optional Critic model call describes findings already detected by rules. The arithmetic runs in a 50-digit Decimal context, with half-up rounding for the four-decimal display. Market screens dated sources and Risk labels hypotheses. Ollama runs DeepSeek-R1 on the same machine. It uses compact evidence IDs for structured selection and restores full references before agent checks. The Apple comparison used temperature 0, thinking disabled and a 1,024-token output cap for both arms. The injected validation sweep from 0 to 1 in steps of 0.25 leaves the 0.5 engineering default in place.

**Sources:** `report things/MAFIS Project Report.docx` · `config.py` · `gemini.py::GeminiSettings` · `ollama_adapter.py::OllamaAdapter` · `agents/verification_gate.py` · `agents/critic_agent.py` · `engine/financial_engine.py` · `evaluation/batch2.py::freeze_threshold`

## 10. Seven filings produced all four calculations

**Layout:** Coverage metrics above the report’s seven-issuer result table.

**Placement:** Editable reproduction of report Table 3, with fiscal-year percentages and unitless current ratios.

**Exact visible text** (83 words):

```text
OFFLINE CLOSEOUT / SOURCE COVERAGE
Seven filings produced all four calculations
13
FY2024 source slots
10
local PDFs
7
admitted filings
Filing
Revenue growth %
Operating margin %
Net margin %
Current ratio
NVIDIA
125.8545
54.1217
48.8493
4.1713
Apple
2.0220
31.5102
23.9713
0.8673
Coca-Cola
2.8566
21.2320
22.6281
1.0296
Amazon
10.9909
10.7519
9.2871
1.0637
PepsiCo
0.4187
14.0299
10.4797
0.8189
Meta
21.9411
42.1760
37.9086
2.9779
AMD
13.6905
7.3686
6.3642
2.6163
Market source  ·  31 January 2024 FOMC statement excerpt. The closeout includes parser-exposed filings.
10
```

**Speaker notes:** Thirteen FY2024 source slots yielded ten local PDFs. Seven were admitted and each contributed six primitives and four calculations. The other three local filings failed preparation, and three requested sources were unavailable. The market excerpt was from the January 31, 2024 FOMC statement. Some layouts had already informed parser development, so the admitted files do not represent a fresh held-out evaluation.

**Sources:** `report things/MAFIS Project Report.docx` · `evaluation/results.md` · `tests/fixtures/batch2_cases.json`

## 11. Page retrieval and numerical coverage

**Layout:** Native retrieval chart beside numerical scoring and misses.

**Placement:** Top-five page and anchor counts on the left. Reference arithmetic and denominators on the right.

**Exact visible text** (85 words):

```text
RESULTS / EVALUATION METRICS
Page retrieval and numerical coverage
MiniLM retrieval · 30 labelled queries · top 5
Page hit 28
Anchor passage 26
Page recall 28/30
Page misses  Coca-Cola currency and AMD income
Independent calculation reference
Fraction arithmetic and 80-digit Decimal division. Absolute tolerance 0.00005 in the reported unit.
28/28 returned and scorable
All returned, scorable results matched. The 28/52 figure counts correct results across all requested slots.
Missing reference values
39 slots had source-inspected inputs. The other 13 had no reference value.
11
```

**Speaker notes:** The first bar counts queries with a labelled page among the top five chunks. The second bar requires the labelled text anchor to appear in a retrieved chunk. Coca-Cola currency and AMD income missed the page. NVIDIA operating cash and Apple's calendar missed the anchor despite making the page. The independent oracle uses Fraction and 80-digit Decimal. Twenty-eight returned scorable outputs all matched within 0.00005 in the reported unit. Across the 52 requested slots, 13 lacked reference values.

**Sources:** `report things/MAFIS Project Report.docx` · `evaluation/results.md` · `evaluation/batch2.py::score_retrieval` · `evaluation/metrics.py::numerically_equal`

## 12. Source failures and injected checks

**Layout:** Reasons for rejected filings on the left, detection counts on the right.

**Placement:** The report’s admission examples and counts from the verification and contradiction tests.

**Exact visible text** (79 words):

```text
RESULTS / FAILURE ANALYSIS
Source failures and injected checks
Filing
Why admission failed
Intel
Reporting currency unestablished
Walmart
Unsupported statement text encoding
Nike
Currency unclear and no operating-income row
Unavailable PDFs  Microsoft, Alphabet and Netflix
Injected test
TP
TN
FP
FN
Verification
8
1
0
0
Contradictions
7
5
0
0
Precision and recall 1.0 on these small injected sets.
Apple FY2024, PDF p. 10  ·  The cited passage describes a minority smartphone share and gives no percentage.
12
```

**Speaker notes:** Intel lacked admissible currency evidence. Walmart's statement fonts lacked a usable Unicode mapping in this parser. Nike failed currency admission and lacked a separately reported operating-income row. Microsoft, Alphabet and Netflix were unavailable. The verifier and Critic were also tested on small injected cases. The Apple document run shows a different kind of evidence gap. It verified a passage describing market share qualitatively, and flagged the missing percentage. Verification checks wording and source location, while coverage depends on whether the passage answers the question.

**Sources:** `report things/MAFIS Project Report.docx` · `evaluation/results.md` · `evaluation/mechanisms.py` · `tests/fixtures/batch2_cases.json` · `output/test_lab/dynamic-apple-final/run_summary.json`

## 13. One retry restores NVIDIA’s net margin

**Layout:** Animated trace beside gate states and the recovered result.

**Placement:** The looping GIF is embedded on the left. The report’s saved Test Lab counters and outcome are on the right.

**Exact visible text** (75 words, longest animation frame included):

```text
DEMONSTRATION / SAVED OFFLINE RUN
One retry restores NVIDIA’s net margin
Before correction
14/14 present claims eligible. Missing net income blocks the gate.
After one correction
17/17 eligible. All four calculations present, including 48.8493% net margin.
10 mock calls · 0 live requests
If the mock omits net income again, the report stays partial after the retry.
13
```

Embedded GIF text by frame (the final frame holds briefly):

```text
STEP 01 / 05 / Net income omitted / First model response / Omission Gate Planner Recheck Report
STEP 02 / 05 / Health Gate blocks / Required evidence missing / Omission Gate Planner Recheck Report
STEP 03 / 05 / Planner allocates retry / Budget: 1 to 0 / Omission Gate Planner Recheck Report
STEP 04 / 05 / Net income verified / Financial Engine recomputes / Omission Gate Planner Recheck Report
STEP 05 / 05 / 48.8493% net margin / Gate passes · report succeeds / Omission Gate Planner Recheck Report
```

**Speaker notes:** The first mock response omits net income, so net margin is unavailable. All 14 factual claims present were eligible, but the gate had an explicit upstream issue and blocked. Planner spent its only retry on net income and net margin. Document, Financial and Risk reran with checks. The final gate had 17 eligible factual claims, and the report recovered net margin at 48.8493%. The persistent scenario stayed partial.

**Sources:** `report things/MAFIS Project Report.docx` · `output/test_lab/verify-corrected/scenario.json` · `output/test_lab/verify-corrected/evidence.json` · `output/batch2/demo/results.json` · `scripts/test_lab.py`

## 14. Apple FY2024 demo benchmark

**Layout:** Editable four-metric result table above the score and run counts.

**Placement:** Oracle values next to the outputs of single-call DeepSeek-R1 and Full MAFIS.

**Exact visible text** (87 words):

```text
RESULTS / PAIRED LOCAL INFERENCE
Apple FY2024 demo benchmark
Same local DeepSeek-R1, Apple filing and dated market evidence
Metric
Independent reference
Single DeepSeek-R1
Full MAFIS
Revenue growth
2.0220%
4.37%
2.0220%
Operating margin
31.5102%
31.55%
31.5102%
Net margin
23.9713%
24.00%
23.9713%
Current ratio
0.8673×
0.87×
0.8673×
Fully supported
Value, unit, period + inputs
0/4
4/4
Input citations 4/4 in both arms   ·   Requests 1 vs 8   ·   Observed wall time 37.2 s vs 18.1 s
One development filing. Wall time excludes shared indexing. Narrative quality was unscored.
14
```

**Speaker notes:** Both arms ran deepseek-r1:8b in Ollama with the same Apple question, filing, model settings and dated market source. The single model calculated the metrics. Full MAFIS used its deterministic engine and additional verification retrieval. A score requires the right value, fiscal period, unit and both input citations. Both arms cited the correct inputs for four of four metrics. The baseline reports two decimal places, and all four values miss the numerical tolerance. Narrative quality was unscored. Shared indexing was excluded from wall time, and run order, caches and warm-up can affect it. The table uses the more recent saved run. An earlier run on the same development case reproduced the scores. The Test Lab command is python -m scripts.test_lab apple-benchmark.

**Sources:** `report things/MAFIS Project Report.docx` · `evaluation/apple_benchmark.py::run_apple_benchmark` · `output/test_lab/dashboard/336dbc93d17f41c7843b48d93f49f153/benchmark.json` · `output/test_lab/dashboard/7ce217b5d5674cf19471b57140aace5e/benchmark.json` · `tests/fixtures/apple_2024/annotations.json`

## 15. What changes when components are removed

**Layout:** Five-row ablation table with timing and interpretation.

**Placement:** Editable timing and call-count table, plus changes to the path each condition can exercise.

**Exact visible text** (97 words):

```text
RESULTS / ABLATIONS AND TRADE-OFFS
What changes when components are removed
Component removed
Change in execution
Mock calls
Mean local s
Verification
Claims remain unchecked
63
1.202
Bull and Bear
No paired interpretations
42
24.092
Critic
No mechanical conflict check
56
23.601
Re-analysis
No targeted rerun
56
24.272
Financial Engine
Model arithmetic without artifacts
28
2.261
Mock evaluation  ·  28/52 correct per condition, 56 completions and 48 preparation failures.
Apple local example  ·  Context shrank from 85,178 to 3,828 bytes across 8 requests.
Mock timings include retrieval under load. Controlled latency and peak memory remain unmeasured.
15
```

**Speaker notes:** This table is from the separate mock evaluation. Every condition completed on seven admitted filings and retained six preparation failures. Over eight conditions that gives 56 completions and 48 failures. Removing verification changes which claims can support the report. Removing the engine changes who does the arithmetic. The timings include retrieval under concurrent validation load. In one saved Apple full run on Ollama, context compaction reduced the cumulative context from 85,178 to 3,828 bytes across eight model requests. The context counts exclude the rest of the request body. This is a run example. Controlled latency and peak memory remain unmeasured.

**Sources:** `report things/MAFIS Project Report.docx` · `evaluation/results.md` · `evaluation/batch2.py::CONDITIONS` · `evaluation/experimental.py` · `output/test_lab/ollama-full-verify/scenario.json`

## 16. Paired evaluation on unseen filings

**Layout:** Three limitation-and-action rows above an ethics band.

**Placement:** Each gap from the report is paired with the next measurement.

**Exact visible text** (71 words):

```text
DISCUSSION / LIMITS AND NEXT STEPS
Paired evaluation on unseen filings
One development filing
Repeat matched local trials on unseen filings. Measure latency variance and peak memory.
Zero imported reviewer ratings
Grade numerical answers and source support independently against the filings.
Parser admission varies by filing
Test new layouts and retain preparation failures in coverage by format.
Expose evidence gaps, label risk as a hypothesis and keep cloud execution opt-in.
16
```

**Speaker notes:** The Apple runs exercised both arms on one known development filing. The next evaluation needs matched local runs on unseen filings and repetitions to measure runtime variability. No human ratings have been imported. To test reliability, we'd run those pairs, have independent reviewers trace the claims, and measure timing and peak memory under controlled conditions. We also need to record failures by filing format and keep missing evidence visible. In live mode, the question and retrieved excerpts are sent to the model service. Ollama sends its requests to the local service.

**Sources:** `report things/MAFIS Project Report.docx` · `output/test_lab/dashboard/336dbc93d17f41c7843b48d93f49f153/benchmark.json` · `evaluation/results.md` · `evaluation/batch2.py::import_ratings` · `tests/fixtures/batch2_cases.json` · `ollama_adapter.py`
