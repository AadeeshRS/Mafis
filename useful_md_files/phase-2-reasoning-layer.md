# Phase 2 — Reasoning Layer

## Goal

Add grounded verification, market context, and risk assessment on top of the working Phase 1 pipeline.

The central change in this phase is that MAFIS must distinguish:

- whether a claim is supported by evidence/calculation; and
- how strongly that support is established.

Verification is therefore an independent checking stage, not simply another LLM opinion.

## Tasks

- [ ] Build `agents/market_agent.py`: perform market, industry, macro, and catalyst research through the shared RAG/tool layer and write structured findings to Shared Memory.
- [ ] Keep Market Agent findings descriptive and evidence-backed. It should not silently convert market observations into company-specific risk judgments.
- [ ] Update `agents/risk_agent.py`: consume Financial and Market findings, use their `claim_id` / `calculation_ref` references, and perform additional direct retrieval only when risk-specific evidence is required.
- [ ] Ensure Risk Agent does not re-derive financial ratios that already exist in the Deterministic Engine. It should interpret them and connect them to risk categories.
- [ ] Build `agents/verification_agent.py`: independently re-query RAG for source-backed claims, validate calculation references against engine outputs, and assign structured verification status plus a `support_level`.
- [ ] Make verification checks claim-type aware:
  - source-backed factual claims → evidence match check;
  - derived financial metrics → calculation/input consistency check;
  - risk claims → evidence plus referenced financial/market support;
  - agent interpretations → traceability check rather than treating interpretation as a raw fact.
- [ ] Record evidence gaps explicitly. A verifier should be able to state that a claim is plausible but insufficiently supported, rather than forcing a binary yes/no conclusion.
- [ ] Build the Verification Health Gate as a conditional edge in `graph.py`.
- [ ] Do not treat `50%` as a scientifically fixed threshold. Keep the value configurable, but select/calibrate it using validation data before final evaluation.
- [ ] Have the Health Gate consider aggregate quality signals, not only unsupported-claim percentage where practical (for example unsupported claims, citation mismatches, and extraction failures).
- [ ] If the Health Gate fails and the retry budget is available, produce a structured re-analysis request containing:
  - implicated agent(s),
  - suspected failure type,
  - missing evidence or correction needed.
- [ ] Update `agents/report_agent.py` to include support/verification information and a basic Limitations section.
- [ ] Add tests showing that Verification checks the source independently instead of trusting the original citation blindly.

## Exit Criteria

- Market and Risk findings are represented as structured claims with traceable references.
- Verification correctly flags manually injected source/citation errors and calculation inconsistencies.
- Verification can distinguish unsupported claims from supported claims without inventing replacement evidence.
- The Health Gate responds correctly to deliberately degraded runs.
- The Health Gate threshold remains configurable and a validation procedure for selecting it is documented.
- Report generation surfaces unsupported/low-support findings instead of silently turning them into settled facts.

## Explicitly Out of Scope for This Phase

Bull/Bear, Critic, full adaptive re-analysis, trading/portfolio logic, model routing.

The Health Gate may emit a structured re-analysis request or halt safely in this phase. The complete Planner-driven re-analysis workflow is finalized in Phase 3.

## Design Notes

Verification must remain independent from the agent that produced the original claim. The goal is not to ask a second model whether the first model sounds convincing; the goal is to check the claim against source evidence and deterministic results.
