# MAFIS — Design Principles & Rationale v1.1

> Read before changing the architecture. These principles incorporate lessons from the MAFIS literature review and are intended to prevent complexity from being added without a measurable reason.

## Principles

1. **Evidence over unsupported generation** — claims need traceable support.
2. **Deterministic computation over LLM arithmetic** — derived financial numbers come from the deterministic engine.
3. **Structured agent outputs, not raw agent-to-agent chat.**
4. **Single shared, append-only state** — agents collaborate through structured state.
5. **Single ownership of extraction** — avoid duplicate extraction paths for the same primitive.
6. **Explicit dependencies, not blind parallel fan-out.**
7. **Verification before downstream synthesis** — use fresh retrieval/calculation evidence rather than model self-knowledge.
8. **Opposing viewpoints are constrained by evidence.**
9. **Critique and re-analysis are controlled** — no infinite loops or automatic full-pipeline restarts.
10. **Fail early on systemic evidence failure** — do not spend downstream compute when upstream data quality is poor.
11. **Support level is a rubric, not a fake probability.**
12. **Uncertainty is an output** — unresolved issues are surfaced, not silently removed.
13. **Every extra mechanism must earn its cost** — agent count, debate, retrieval passes, and retries are hypotheses to evaluate, not assumptions of quality improvement.

## What the Literature Changes

The literature review supports several existing MAFIS decisions:

- Financial QA studies support separating language reasoning from deterministic calculation.
- Multi-agent financial research studies support task specialization, but also show that more agents can hurt simpler tasks.
- Debate-oriented financial systems support opposing perspectives but do not establish that debate always improves correctness.
- Recent financial deep-research work supports structured intermediate analytical state and dynamic evidence acquisition.
- Critic-agent studies show that critique can help in some settings and harm in others; therefore the Critic is an experimental component, not a guaranteed improvement.

## Key Decisions and Why

**Why use a shared structured state?**

Agents need reusable findings without forcing every downstream component to consume long natural-language histories. Structured state also makes provenance, debugging, replay, and contradiction checks practical.

**Why make RAG a shared tool?**

Financial, Market, Risk, and Verification agents may need to inspect source evidence directly. A single shared retrieval layer avoids forcing every agent to trust a secondhand summary.

**Why not add agents simply because other papers use more?**

The reviewed collaboration study found that larger agent groups can improve complex tasks such as risk analysis while reducing quality on simpler tasks. MAFIS therefore keeps one role per meaningful analytical responsibility rather than maximizing agent count.

**Why a deterministic financial engine?**

The literature on financial numerical reasoning shows a consistent advantage from external/deterministic calculation. The LLM decides what should be calculated and interprets the result; deterministic code executes it.

**Why separate Verification and Critic?**

Verification asks whether evidence and calculations support a claim. Critic asks whether a collection of supported claims is internally consistent and logically coherent. Keeping them separate avoids using one LLM judgment as both evidence validation and higher-level reasoning.

**Why can Bull/Bear request more evidence?**

A constrained adversarial analyst should be able to say that an important claim cannot yet be supported. Allowing an evidence request is more useful than forcing it to reason only with an incomplete evidence set. New evidence still has to pass Verification before it can support a factual assertion.

**Why an Evidence / Analysis Map before final report writing?**

Financial deep-research systems show value in converting raw research into structured intermediate analytical units before writing the final narrative. MAFIS uses a lightweight version of this idea inside the Report Generation Agent instead of adding another agent.

**Why is the health-gate threshold configurable?**

A threshold such as 50% is an implementation starting point, not a scientifically established constant. The final threshold should be calibrated on a validation set.

**Why is the retry cap configurable?**

A single retry is a practical default that bounds cost and latency. The evaluation should test whether zero, one, or more retries materially improve reliability; the architecture should not claim that one is universally optimal.

## Anti-Patterns — Do Not Implement These

- Do not let agents communicate by passing raw, unbounded conversation histories as their primary state.
- Do not let the Financial Agent re-extract a primitive already owned by Document Agent unless Planner explicitly scopes a re-analysis.
- Do not present a derived financial number as authoritative unless it has a deterministic calculation reference.
- Do not treat a raw extracted numeric primitive as a final analytical metric.
- Do not let Bull/Bear assert an unverified claim as fact.
- Do not let newly retrieved Bull/Bear evidence bypass Verification.
- Do not let Critic directly overwrite or silently rewrite claims.
- Do not let a Critic decision trigger an unlimited recursive loop.
- Do not treat the number of agents as evidence that the system is better.
- Do not add multi-model routing, real-time streaming, or visualization-heavy features unless the research question requires them and the evaluation justifies the added complexity.
