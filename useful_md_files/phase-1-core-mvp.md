# Phase 1 — Core MVP

## Goal

Build the smallest end-to-end MAFIS system that already enforces the two most important reliability properties:

1. evidence-backed extraction; and
2. deterministic financial computation.

The Phase 1 pipeline is:

`Document Agent → Financial Agent → Deterministic Engine → Structured Shared Memory → Analysis Map → Report Generation Agent`

No Verification, Bull/Bear, Critic, or adaptive re-analysis yet.

## Tasks

- [ ] Stand up `memory/shared_memory.py` using the revised `memory.md` schema — append-only, versioned, structured claims, typed evidence, support level, and calculation references.
- [ ] Build `rag/ingest.py` (chunk, embed, index) and `rag/retriever.py` (`retrieve(query, filters)`).
- [ ] Stress-test document parsing/OCR on 3–5 real annual reports before building agents on top of it. Test page mapping, tables, section metadata, and common PDF failure cases.
- [ ] Add retrieval evaluation fixtures during ingestion testing: maintain a small manually labelled set of queries with their expected relevant passages/pages so retrieval quality can be measured later.
- [ ] Build `agents/document_agent.py`: extract raw primitives (facts, numbers, dates, units) with citations. Every written claim must have either an evidence reference or a valid source-linked extraction record.
- [ ] Build `engine/financial_engine.py`: revenue growth, margins, at least one liquidity/leverage ratio, and basic validation/sanity checks. Reject invalid inputs rather than silently calculating with them.
- [ ] Build `agents/financial_agent.py`: decide what calculations are needed, construct structured calculation requests, read source primitives from Shared Memory, and never perform the final arithmetic itself.
- [ ] Store calculation artifacts with a unique `calculation_ref`, input references, formula/operation, output value, unit, period, and sanity-check status.
- [ ] Build `agents/report_agent.py` with a two-stage internal flow:
  1. create an `Analysis Map` linking report sections to claims, evidence, calculations, and support status;
  2. generate the report from that structured map.
- [ ] Wire `graph.py` for the Phase 1 flow in LangGraph.
- [ ] Build the single-LLM baseline in Phase 1 so the same companies/documents can later be run through both systems without changing the evaluation dataset.
- [ ] Instrument latency, token usage, API cost, retrieval calls, and calculation calls from the first end-to-end run.

## Exit Criteria

- Pipeline runs end-to-end on 3–5 real reports.
- Core claims are represented in structured Shared Memory rather than free-form agent-to-agent messages.
- Every numeric claim in the output report traces to both an evidence reference and a `calculation_ref` where the number is derived.
- No numeric result in the report is produced by free-form LLM arithmetic.
- Calculation inputs and outputs pass the engine's sanity checks or are explicitly rejected.
- A small retrieval test set exists with known relevant passages/pages.
- A single-LLM baseline can run on the same input set.

## Explicitly Out of Scope for This Phase

Market Agent, Risk Agent, Verification, Verification Health Gate, Bull, Bear, Critic, adaptive re-analysis, advanced DCF/sensitivity analysis, multi-model routing, portfolio/trading logic.

## Design Notes

Do not add more agents to Phase 1 just to increase apparent system complexity. The literature suggests that agent count and collaboration should be justified by the task and measured experimentally rather than assumed to help.
