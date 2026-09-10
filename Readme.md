# MAFIS — Multi-Agent Financial Intelligence System

MAFIS produces evidence-backed financial intelligence reports via a team of
specialized agents (Planner, Document, Financial, Market, Risk, Verification,
Bull, Bear, Critic, Report) coordinated through LangGraph, sharing state
through a single append-only Shared Memory object, with deterministic Python
for all arithmetic and a capped (max 1) targeted re-analysis loop.

This checkout is **scaffolding only**: module layout, Pydantic schemas, and
`raise NotImplementedError` stubs. No agent logic is implemented yet.

## Layout

- `agents/` — planner, document, financial, market, risk, verification, bull, bear, critic, report
- `engine/` — deterministic financial engine
- `rag/` — ingest + shared retriever
- `memory/` — Shared Memory schema + append-only store
- `graph.py` — LangGraph wiring
- `config.py` — health-gate threshold, re-analysis cap

## Reference docs

- [architecture.md](useful_md_files/architecture.md) — components, data flow, module layout
- [design.md](useful_md_files/design.md) — principles, key decisions, anti-patterns
- [memory.md](useful_md_files/memory.md) — Shared Memory schema and rules
- [plan.md](useful_md_files/plan.md) — build order and definition of done
- [phases.md](useful_md_files/phases.md) — phased build plan index
- [MAFIS_PRD.md](useful_md_files/MAFIS_PRD.md) — full product requirements
- [phase-1-core-mvp.md](useful_md_files/phase-1-core-mvp.md) — Phase 1 tasks
