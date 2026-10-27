# MAFIS — Implementation Plan v1.1

> Build in the following order. The priority reflects both the project requirements and the literature review.

## Build Priority

| Priority | Scope |
|---|---|
| Must have | Planner, Document Agent + shared RAG, Financial Agent + Deterministic Engine, structured Shared Memory, Report Generation, single-LLM baseline |
| Should have | Market Agent, Risk Agent, Verification, Health Gate, Bull/Bear, Critic, bounded targeted re-analysis |
| Useful experiments | Unified analyst vs specialists, Deterministic Engine ablation, Critic ablation, retrieval-quality ablation, optional different models for adversarial agents |
| Future / remove from current scope | Multi-provider LLM routing, live real-time streaming, advanced multimodal chart feedback, more than the configured retry budget, persistent cross-session storage unless required |

## Definition of Done — MVP

- Real annual-report format processes without manual cleanup.
- Financial Agent uses the Deterministic Engine for required metrics.
- Shared Memory stores structured claims, evidence, and calculation references.
- Final report is traceable to Shared Memory.
- Single-LLM baseline can be run on the same inputs.

## Top Priorities

1. Document parsing + evidence retrieval.
2. Deterministic financial computation.
3. Structured Shared Memory and provenance.
4. Independent Verification + retrieval evaluation.
5. Bull/Bear/Critic + targeted re-analysis only after the earlier layers are working.
6. Baseline + component ablations from the beginning of serious evaluation.

## Cross-References

- `architecture.md` — components and data flow
- `memory.md` — Shared Memory schema and rules
- `design.md` — design rationale and anti-patterns
- `phases.md` — phase index
- `phase-1-core-mvp.md` through `phase-4-evaluation.md` — detailed scope
