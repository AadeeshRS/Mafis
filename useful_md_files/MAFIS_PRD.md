# MAFIS — Multi-Agent Financial Intelligence System
### Product Requirements Document v1.1

**Status:** Draft for course submission  
**Updated:** September 24, 2026

---

## 1. Overview

MAFIS is a multi-agent AI system that produces evidence-backed financial intelligence reports on a company given a query and optional source documents. It is not a chatbot, trading system, or investment execution engine.

The research question is whether a structured combination of specialized agents, evidence retrieval, deterministic computation, verification, opposing viewpoints, and controlled critique can improve the reliability of company-level financial analysis relative to a single LLM.

The system is designed around a simple principle: **add structure where it reduces a known failure mode, and verify whether the added structure actually improves results.**

## 2. Goals

- Decompose company analysis into meaningful specialist tasks.
- Ground factual claims in traceable source evidence.
- Separate probabilistic language reasoning from deterministic financial computation.
- Preserve findings, citations, calculations, and verification state in structured Shared Memory.
- Independently verify important claims before synthesis.
- Construct evidence-backed Bull and Bear cases without allowing either side to invent evidence.
- Use structured critique to detect contradictions and request targeted re-analysis.
- Surface unresolved uncertainty instead of silently producing a clean-looking answer.
- Experimentally measure whether each added mechanism improves reliability.

## 3. Non-Goals / Out of Scope

- Automated trading, order execution, or portfolio management.
- Buy/sell/hold recommendations.
- Custom foundation-model training.
- High-frequency or live streaming market infrastructure.
- Unlimited debate or re-analysis loops.
- Multi-provider model routing unless needed for a later experiment.
- Advanced multimodal chart-generation infrastructure unless later justified by the research question.

## 4. Core Architecture

```text
User Query
    ↓
Planner
    ↓
Dependency-aware analysis
    ├── Document Agent → RAG
    ├── Financial Agent → Deterministic Engine
    ├── Market Agent → RAG / external sources
    └── Risk Agent ← Financial + Market + RAG
    ↓
Shared Memory / Evidence Store
    ↓
Verification
    ↓
Verification Health Gate
    ↓
Bull + Bear
    ↓
Critic
    ↓
Problem?
  ├── Yes → Planner → targeted re-analysis (shared cap)
  └── No
    ↓
Evidence / Analysis Map
    ↓
Report Generation
    ↓
Final Financial Intelligence Report
```

## 5. Architectural Updates From Literature Review

### 5.1 Structured claim representation

Shared Memory now distinguishes raw primitives from derived metrics and supports structured fields such as entity, metric, value, unit, and period. This makes numerical and temporal contradiction checks less dependent on interpreting free-form prose.

### 5.2 Evidence-gap handling

Bull, Bear, and Critic may identify missing evidence. Planner can request targeted retrieval or re-analysis, but newly retrieved evidence must pass Verification before it can support an assertion.

### 5.3 Intermediate report representation

Report Generation first builds an internal Evidence / Analysis Map linking sections to claims, evidence, calculations, support levels, and unresolved issues. It then synthesizes the final narrative. This is an internal stage, not a new agent.

### 5.4 Retrieval evaluation

The RAG layer should support task-aware retrieval profiles and be evaluated independently using labeled retrieval examples. A retrieval failure should not automatically be interpreted as an LLM reasoning failure.

### 5.5 No assumed benefit from critique

Verification and Critic remain explicit stages, but the project will test whether they actually improve reliability. Prior work shows that critic agents can improve some financial reasoning settings while harming others.

## 6. Functional Requirements

| ID | Component | Requirement |
|---|---|---|
| FR-1 | Planner | Build a dependency graph and determine the minimal subgraph for re-analysis. |
| FR-2 | Document Agent | Extract source-grounded primitives with document/page/section metadata. |
| FR-3 | RAG | Provide shared task-aware retrieval with source metadata. |
| FR-4 | Financial Agent | Create structured calculation requests and interpret deterministic results. |
| FR-5 | Financial Engine | Perform exact financial calculations and input/output sanity checks. |
| FR-6 | Market Agent | Produce descriptive market/industry/news findings with evidence. |
| FR-7 | Risk Agent | Combine financial and market evidence into structured risk findings and optionally retrieve missing source evidence. |
| FR-8 | Shared Memory | Store append-only versioned claims, evidence, calculations, verification state, and contradictions. |
| FR-9 | Verification | Independently validate claims using fresh retrieval or deterministic results. |
| FR-10 | Health Gate | Detect systemic upstream evidence failure before Bull/Bear/Critic. Threshold must be configurable and later calibrated. |
| FR-11 | Bull/Bear | Use verified claims for factual assertions; may generate structured evidence-gap signals. |
| FR-12 | Critic | Run mechanical contradiction checks before LLM explanation; classify contradiction type and recommend scope. |
| FR-13 | Re-analysis | Re-run only implicated agents/dependents; use one shared retry budget by default. |
| FR-14 | Report Generation | Build Evidence / Analysis Map, then write final report only from supported Shared Memory state. |

## 7. Evaluation Plan

### Baselines

**Single-LLM baseline:** company + same documents/data → one LLM → financial analysis report.

**MAFIS:** complete architecture using the same underlying model family unless an experiment explicitly studies model diversity.

### Core Metrics

| Metric | Measurement |
|---|---|
| Numerical correctness | Ground-truth figures and calculations |
| Unsupported claim rate | Final-report claims lacking sufficient support |
| Citation coverage | Final-report claims with traceable evidence |
| Evidence retrieval | Hit@k / Recall@k on labeled evidence queries |
| Verification precision/recall | Injected supported/unsupported/contradicted cases |
| Contradiction detection | Injected structured contradictions |
| Support-level calibration | Support label versus actual correctness |
| Analytical coverage/depth | Human rubric across financial, market, risk, valuation, Bull/Bear, and evidence coverage |
| Latency | End-to-end and stage-level wall-clock time |
| Cost | Token/API/tool cost per run |
| Overall quality | Blind human evaluation |

### Ablations

At minimum:

- MAFIS without Verification
- MAFIS without Bull/Bear
- MAFIS without Critic
- MAFIS without targeted re-analysis
- MAFIS without the Deterministic Financial Engine
- MAFIS with a unified analyst instead of specialized agents

The goal is to determine which components actually contribute to reliability rather than assuming the full pipeline is better.

## 8. MVP Definition of Done

- One real annual-report format can be processed without manual cleanup.
- Financial Agent produces revenue growth, margins, and at least one leverage/liquidity metric through the deterministic engine.
- Structured Shared Memory is populated with source evidence and calculation references.
- Report contains traceable citations for factual claims and calculation references for derived numeric claims.
- Single-LLM baseline can be run on the same evaluation set.

## 9. Phased Roadmap

| Phase | Scope | Exit Criteria |
|---|---|---|
| Phase 1 — Core MVP | RAG, Document Agent, Financial Agent, Deterministic Engine, structured Shared Memory, Report Generation, baseline skeleton | End-to-end analysis works on real reports |
| Phase 2 — Reliability | Market, Risk, Verification, retrieval metrics, Health Gate | Injected evidence/calculation problems are detected reliably |
| Phase 3 — Adversarial reasoning | Bull, Bear, structured Critic, evidence-gap handling, capped targeted re-analysis | Contradictions and targeted reruns behave correctly |
| Phase 4 — Evaluation | Baseline, ablations, human rating, final metrics | Research question answered with measured results |

## 10. Risks / Mitigations

| Risk | Mitigation |
|---|---|
| PDF/OCR failure | Stress-test multiple real annual reports first |
| Retrieval failure | Measure retrieval independently and preserve source metadata |
| Correlated Bull/Bear/Critic bias | Evidence-only inputs, distinct prompts, optional model diversity as an experiment |
| Critic overthinking | Evaluate Critic against a no-Critic ablation; do not assume it improves accuracy |
| Excessive tool/LLM calls | Explicit dependency graph and shared retry budget |
| False confidence | Rubric support levels, not raw self-reported probabilities |
| Unresolved contradictions | Surface them explicitly in the final report |

## 11. Future Work

- More than one re-analysis retry only if evaluation shows a clear benefit.
- Different underlying models for Bull/Bear/Critic if correlated bias becomes a measured problem.
- Persistent cross-session memory if required by the application.
- More advanced multimodal report generation if the project later evaluates presentation quality.
