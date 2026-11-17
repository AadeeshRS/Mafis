# MAFIS slide blueprint

16 slides, 16:9. Arial throughout. Graphite and off-white with teal and indigo accents. The two-digit footer is present on every slide and included in the word count.

Rubric: `report things/Final Guidelines.docx.pdf`. `report things/reportformat.pdf` is a sample report, with no slide layout to copy.

## 01. MAFIS

**Layout:** Dark typographic split.

**Placement:** Name and problem at left; retrieval headline on the right.

**Exact visible text** (26 words):

```text
ARTIFICIAL INTELLIGENCE COURSE PROJECT
MAFIS
Multi-Agent Financial
Intelligence System
Trace financial claims to filings
28/30
labelled queries hit the right page
in the top five
01
```

**Speaker notes:** Our project asks whether a report about a company can show exactly where its financial claims came from. MAFIS turns a filing and a question into a traceable analysis. Our strongest measured retrieval result is 28 page hits across 30 labelled queries using real MiniLM embeddings. This is a retrieval result on exposed queries. It does not tell us how often the complete report is correct.

**Sources:** `evaluation/results.md` · `Readme.md` · `evaluation/batch2.py::score_retrieval`

## 02. Financial analysis as a state graph

**Layout:** Three state blocks and two outcome paths.

**Placement:** Left-to-right state progression, with success and partial outcomes below the terminal state.

**Exact visible text** (35 words):

```text
Financial analysis as a state graph
Initial state
Working state
Terminal state
Question + filing
Empty run store
Versioned claims
Open issues
Retry budget
Traceable report
Partial if unresolved
Actions: retrieve, verify, calculate, retry
02
```

**Speaker notes:** Think of a state as everything the run knows so far. Initially we have the question, filing metadata and an empty run store. LangGraph actions retrieve, propose and verify evidence, compute ratios or rerun a dependency. The current state includes claims, issues and retry budget. We aim for a traceable report, but the graph also terminates with an honest partial report. It follows coded conditions, so a shortest-path search would not fit this task. The actual search is for source chunks, which I’ll show later.

**Sources:** `graph.py::Phase1State, ExtendedState, run_full_pipeline` · `agents/planner.py::PlannerAgent`

## 03. Seven filings support all four calculations

**Layout:** Three metric columns and nested coverage bar.

**Placement:** Counts across the top. Lower bar partitions the 13 source slots into admitted, local unsupported and blocked downloads.

**Exact visible text** (33 words):

```text
Seven filings support all four calculations
13
requested source slots
10
local official PDFs
7
admitted filings
7 Admitted
3 Local unsupported
3 Blocked downloads
Market context: 31 Jan 2024 FOMC snapshot
03
```

**Speaker notes:** The manifest reserves thirteen company slots. Ten official PDFs are present, and seven pass the extraction profile for all six required primitive values. The remaining three local PDFs do not. The dated market input is the January 31, 2024 FOMC statement excerpt. Amazon, Meta and PepsiCo were moved into development for parser work; AMD is validation and parser-development material. We cannot treat the successful cases as a fresh held-out set.

**Sources:** `tests/fixtures/batch2_cases.json` · `tests/fixtures/market_snapshots/fomc_2024_01_31.json` · `evaluation/results.md`

## 04. A claim keeps its source and version

**Layout:** Source strip above a three-column record.

**Placement:** NVIDIA revenue row cropped from the filing above editable value, fiscal context and provenance fields.

**Exact visible text** (38 words):

```text
A claim keeps its source and version
NVIDIA FY2024 income statement
60,922
USD millions
28 Jan 2024
Fiscal year end
PDF p. 150
Cell locator
SharedMemory: claim ID + version
04
Revenue $ 60,922 $ 26,974 $ 26,914
```

**Speaker notes:** Here is the actual source line from NVIDIA's income statement. For the January 28, 2024 column the parsed value is 60,922 in USD millions. The indexed TableCell retains the metric, accounting scope, fiscal period, scale and evidence location. The agent's Claim has a stable ID and an incrementing version. SharedMemory appends revisions and keeps the exact references. A calculation can become stale if one of its source versions changes, so verification is a property of a specific version.

**Sources:** `tests/fixtures/nvidia_2024/annual_report.pdf, PDF p. 150 (printed p. 50)` · `rag/models.py::TableCell` · `memory/shared_memory.py::Evidence, Claim, ClaimVersionRef, SharedMemory`

## 05. PDF parsing preserves table context

**Layout:** Two parallel native workflow lanes.

**Placement:** Narrative and statement routes meet the same index. Measured character window settings sit below the narrative lane.

**Exact visible text** (31 words):

```text
PDF parsing preserves table context
Born-digital PDF
Page text
Narrative chunks
Chroma index
Chars / overlap: page 900/150 · section 800/100
Statement rows
Dates + scale
Typed cells
Chroma index
05
```

**Speaker notes:** The ingest code reads born-digital PDFs with pdfplumber. It makes page-bounded narrative chunks using 900-character windows with 150 characters of overlap, plus section windows of 800 and 100. It also attaches the table title, fiscal headers, scale header and exact quote to supported statement rows. It resolves comparative dates and currency only when the source gives enough context. Narrative can still be searchable when a table is not admissible. This path has no OCR.

**Sources:** `rag/ingest.py::prepare_document, extract_financial_facts, chunk_text` · `requirements-extraction.txt`

## 06. Verification controls the report path

**Layout:** Top evidence chain and bottom conditional branch.

**Placement:** Native connectors show the evidence chain, reasoning path, and Planner's shared correction before reporting.

**Exact visible text** (36 words):

```text
Verification controls the report path
Planner
Document
+ verify
Financial
+ dated Market
Verify, Risk
+ verify
Health Gate
Pass
Blocked
Bull/Bear + Critic
Planner retry check
Targeted rerun
Analysis map
+ report
No rerun
06
```

**Speaker notes:** The upper row compresses the first part of the full graph. It verifies primitives before Financial runs, checks the Financial and dated Market outputs before Risk, then verifies Risk before the Health Gate. A pass can start Bull and Bear on the same eligible snapshot, then the Critic checks structured assertions. A blocked gate bypasses that stage. Planner combines eligible issues from the gate and Critic, allows one targeted rerun, and the ReportAgent renders the authoritative AnalysisMap. A clean run goes straight to reporting after the Planner's retry check.

**Sources:** `graph.py::build_extended_graph, build_full_graph` · `agents/full_workflow.py::requests_for, execute_targeted` · `agents/report_agent.py::ReportAgent`

## 07. Models propose; code checks and calculates

**Layout:** Two columns split by responsibility.

**Placement:** Model role labels on the left. Deterministic checks and operation family on the right.

**Exact visible text** (36 words):

```text
Models propose; code checks and calculates
Gemini proposals
Document: source cell selection
Financial: operation selection
Bull/Bear: qualified interpretations
Python rules
Verifier: exact evidence checks
FinancialEngine: Decimal arithmetic
Critic: structured contradictions
Constraints: metric, period, currency, version
07
```

**Speaker notes:** The production adapter asks Gemini for typed proposals. The Document and Financial agents select source facts and operations, while Bull and Bear select qualified interpretations. The Critic's optional language call can explain a finding; rules detect the structured contradiction. Verification checks the source quote and cell attributes. FinancialEngine accepts only revenue growth, operating margin, net margin and current ratio, using Decimal over checked input versions. In CSP terms, the variables are operation input roles, their domains are retrieved typed cells, and the constraints include metric, period, currency, unit, version and source identity. The code filters and validates these selections directly; it has no general CSP solver, fuzzy inference or unrestricted search over assignments. Support labels describe evidence, not calibrated probabilities.

**Sources:** `gemini.py::GeminiAdapter` · `agents/document_agent.py::DocumentAgent` · `agents/financial_agent.py::FinancialAgent` · `agents/critic_agent.py::CriticAgent` · `agents/verification_agent.py::VerificationAgent` · `engine/financial_engine.py::FinancialEngine`

## 08. Search ranks evidence within source filters

**Layout:** Four-stage retrieval strip with result callouts.

**Placement:** Editable flow across the canvas; per-query k and index behavior below.

**Exact visible text** (27 words):

```text
Search ranks evidence within source filters
Query
all-MiniLM-L6-v2
Filtered Chroma
Cosine-ranked
chunks
3
hits per narrative query
5
hits per metric query
No project-side model training
08
```

**Speaker notes:** SharedRetriever embeds on CPU with Chroma’s ONNX MiniLM implementation and searches the persistent Chroma collection with cosine distance. It can restrict results by document, section, chunk kind, page, period or metric, and uses chunk ID to break equal distances. DocumentAgent runs three narrative queries at top 3 and metric-specific table queries at top 5, then deduplicates chunks. State routing is rule-based and neither embedding nor generation model is trained or fine-tuned by this repository.

**Sources:** `config.py::EMBEDDING_MODEL` · `rag/retriever.py::SharedRetriever.retrieve` · `agents/document_agent.py::collect_context`

## 09. The Health Gate has an uncalibrated default

**Layout:** Three parameter columns above a calibration strip.

**Placement:** Production gate, shared retry budget and default adapter controls. Injected threshold sweep in a separate line.

**Exact visible text** (38 words):

```text
The Health Gate has an uncalibrated default
>0.5
ineligible rate blocks
1
analytical retry maximum
0
Gemini temperature
Empty evidence or upstream issues block
Adapter: 4096 tokens, 30 s, 2 transport retries
Injected sweep: 0–1 by 0.25
09
```

**Speaker notes:** By default, VerificationHealthGate blocks if the fraction of current factual claims ineligible as verified is strictly greater than 0.5. Empty evidence or any upstream issue blocks regardless of that rate. The one retry is analytical; it is separate from the adapter's two default transport retries. The production Gemini default is gemini-3.8-flash with temperature zero, 4096 output tokens and a 30-second timeout. The injected validation sweep runs from 0 to 1 in increments of 0.25. It minimizes false passes, then false blocks, then chooses the smaller threshold. It selected 0.25 on four synthetic rows and did not change the production value.

**Sources:** `config.py` · `gemini.py::GeminiSettings` · `agents/verification_gate.py::VerificationHealthGate` · `evaluation/mechanisms.py` · `evaluation/batch2.py::freeze_threshold`

## 10. Page hits outnumber passage hits

**Layout:** Editable bar chart left; two validation counts right.

**Placement:** Native horizontal bars with a 30-query denominator. Source-cell and engine totals sit in a separate right column.

**Exact visible text** (26 words):

```text
Page hits outnumber passage hits
30 labelled development queries · top 5
Page hit 28
Anchor passage 26
42
source-matching cells
28
correct engine operations
10
```

**Speaker notes:** The closeout used real MiniLM and labelled development queries. A page hit means one of the five retrieved chunks landed on a labelled page. Anchor coverage additionally asks whether a retrieved chunk contains the labelled passage. The logged counts were 28 of 30 for pages and 26 of 30 for anchors; the study did not measure six unindexed or unadmitted cases. Separately, the seven admitted documents gave 42 source-matching primitives and 28 correctly computed engine operations. The oracle computes independently using rational arithmetic.

**Sources:** `evaluation/results.md` · `evaluation/batch2.py::score_retrieval` · `evaluation/metrics.py::expectations` · `tests/fixtures/retrieval_validation.json`

## 11. Full and single-call arms tie with mocks

**Layout:** Baseline grid left; related-work comparison right.

**Placement:** Requested numerical slots for the two repo arms on the left. Scope comparison to two research references on the right.

**Exact visible text** (33 words):

```text
Full and single-call arms tie with mocks
Offline arm
Correct/requested
Full
28/52
Single call
28/52
Related work
Focus
FinanceBench ’23
Open-book QA
FinCARDS ’26
Evidence reranking
MAFIS
Verified reports
Comparable source access
11
```

**Speaker notes:** The repository baseline makes one call without the engine, verifier or Critic. The arms share a question and prebuilt filing and Fed evidence bundle. Specialists can retrieve additional scoped chunks, so their contexts are comparable in access, not identical. Both mock arms return the same 28 correct values across 52 requested slots. That is not measured live accuracy. For context, FinanceBench evaluates open-book financial questions, and FinCARDS reranks finance-aware evidence cards. Our system emphasizes checked claims and report generation. We did not run either publication's benchmark.

**Sources:** `evaluation/results.md` · `evaluation/batch2.py::CommonEvidence, validate_pair` · `evaluation/full_baseline.py` · <https://arxiv.org/abs/2311.11944> · <https://aclanthology.org/2026.findings-acl.1244/>

## 12. Missing source context blocks extraction

**Layout:** Failure examples left; injected confusion matrices right.

**Placement:** Three issuer-level failures. Two editable matrices with predicted columns (positive, negative) and actual rows (positive, negative).

**Exact visible text** (35 words):

```text
Missing source context blocks extraction
Intel
Currency unestablished
Walmart
Unsupported text encoding
Nike
No separate operating income
Injected cases
Verifier
8
0
0
1
Critic
7
0
0
5
Actual × predicted, positive first
12
```

**Speaker notes:** Intel's glyphs became readable, but the parser still lacked reporting currency. Walmart's statement fonts did not supply a usable Unicode mapping, and Nike also had no separately reported operating-income line. These are admission failures, not fabricated zeros. On the right are small injected tests of implemented rules: Verifier detects all eight injected errors and leaves one clean case alone. Critic catches seven structured contradictions and leaves five compatible cases alone. Rows are actual and columns predicted, positive first. These matrices cannot establish accuracy on free-form text.

**Sources:** `evaluation/results.md` · `tests/fixtures/batch2_cases.json` · `evaluation/mechanisms.py` · `evaluation/batch2.py::detection_metrics`

## 13. One retry recovers NVIDIA’s net margin

**Layout:** Embedded GIF left, outcome contrast right.

**Placement:** Left: assets/nvidia_correction.gif, animated during Slide Show. Right: persistent-omission outcome.

**Exact visible text** (30 words, longest animation frame included):

```text
One retry recovers NVIDIA’s net margin
Offline replay
Persistent omission:
partial report
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

**Speaker notes:** In this saved offline demo, the model double omits net income on its first pass. The Health Gate blocks because a required primitive is missing. Watch Planner spend its single retry, Document recover the source cell, and FinancialEngine compute the exact net margin from verified inputs. The report succeeds. When the same double omits it again in the persistent scenario, the budget is exhausted and the report stays partial. We replay the exported gate history; the real filing and retrieval are paired with mocked generation.

**Sources:** `scripts/batch2_demo.py` · `output/batch2/demo/nvidia_2024_corrected/evidence.json` · `output/batch2/demo/nvidia_2024_persistent/run_summary.json`

## 14. Ablations preserve the mock score

**Layout:** Large outcome at left; component evidence at right.

**Placement:** Mock score and totals on the left; behavior changes hard-coded by two representative interventions on the right.

**Exact visible text** (30 words):

```text
Ablations preserve the mock score
28/52
Correct/requested in all 8 arms
56 completions · 48 source failures
Without verification
Unchecked claims
Without engine
Mock arithmetic · no calculation artifacts
14
```

**Speaker notes:** The eight conditions were the full graph, single call, no verifier, no Bull/Bear, no Critic, no reanalysis, no engine and a unified analyst. Each completes on seven admitted filings and retains six source failures. All eight score 28 correct known slots out of 52 requested; the 28 returned scorable values are all correct. Removing verification keeps the unchecked path from fabricating check records. Removing the engine changes arithmetic to model output and drops calculation artifacts. The other interventions also change executed stages or consolidate role calls. These changes were exercised, but identical mock answers tell us nothing about which components improve live accuracy.

**Sources:** `evaluation/results.md` · `evaluation/batch2.py::CONDITIONS, _run_condition` · `evaluation/experimental.py::no_engine_run` · `evaluation/unified.py::unified_run`

## 15. Mean local inference time

**Layout:** Editable timing table left; latency caveats right.

**Placement:** All eight arms listed with aggregate logical mock calls and mean local inference seconds. Timing limits at right.

**Exact visible text** (39 words):

```text
Mean local inference time
Arm
Calls
Seconds
Full
56
24.147
Single-call
7
0.007
No-verifier
63
1.202
No-Bull/Bear
42
24.092
No-Critic
56
23.601
No-reanalysis
56
24.272
No-engine
28
2.261
Unified
21
13.577
Mock runs
Memory unmeasured
Live latency unknown
15
```

**Speaker notes:** The full condition made 56 mock logical requests across seven completed documents, compared with seven for the single-call comparator. The full arm's mean was 24.147 seconds versus 0.007 seconds for the single call. These are reported local inference times under concurrent validation load. The baseline reuses prepared context, while the full graph does additional scoped retrieval and validation. This is not a controlled overall latency benchmark. Peak RAM and live inference timing were not measured, and all arms have identical mock numerical scores.

**Sources:** `evaluation/results.md` · `evaluation/batch2.py::run_condition` · `evaluation/metrics.py::condition_usage`

## 16. Live quality remains unmeasured

**Layout:** Dark closing slide with three limitation-to-next-step rows.

**Placement:** Evidence limits left and proposed follow-up actions aligned to the right.

**Exact visible text** (30 words):

```text
Live quality remains unmeasured
HTTP 503 · no live pair
Run a controlled paired trial
Zero human ratings
Blind-review untouched filings
Encoding and currency gaps
Validate parser changes separately
16
```

**Speaker notes:** The attempted live comparator got HTTP 503 and no completed live pair. We need paired runs with the same model settings, logged retrieval and controlled timing and memory measurement. We also have no completed human ratings. Two reviewers should independently assess blinded reports and trace claims to the original sources, then compare results on untouched filings. Right now the parser's admission rules exclude some issuer formats; test new currency and encoding handling on separate data before expansion. Showing missing evidence matters because readers could otherwise mistake a limited risk screen for complete or actionable financial advice.

**Sources:** `evaluation/results.md` · `tests/fixtures/batch2_cases.json` · `evaluation/batch2.py::human_materials, import_ratings`
