# Phase 3 — Adversarial Reasoning Layer

## Goal

Add opposing analysis, structured contradiction checking, and the bounded targeted re-analysis loop.

This phase should not turn MAFIS into a long debate system. The purpose is controlled adversarial review of an already grounded analytical state.

## Tasks

- [ ] Build `agents/bull_agent.py` and `agents/bear_agent.py`.
- [ ] Bull and Bear may assert conclusions only from verified claims in Shared Memory.
- [ ] Allow Bull/Bear to identify an evidence gap or request additional evidence, but do not allow them to treat newly retrieved evidence as usable until it passes Verification.
- [ ] Ensure Bull/Bear outputs reference the underlying `claim_id`s so every argument can be traced to the evidence base.
- [ ] Add post-generation validation that rejects Bull/Bear assertions that cannot be mapped to permitted claim IDs.
- [ ] Build `agents/critic_agent.py`.
- [ ] Implement deterministic contradiction checks before LLM explanation.
- [ ] Introduce structured contradiction categories:
  - `NUMERICAL`
  - `TEMPORAL`
  - `UNIT`
  - `SOURCE`
  - `LOGICAL`
  - `CAUSAL`
  - `RISK_INTERPRETATION`
  - `MISSING_EVIDENCE`
- [ ] The Critic must distinguish a genuine contradiction from two statements that are simply different perspectives. For example, increased debt and an assertion that the balance sheet remains manageable are not automatically contradictory; the Critic should determine whether the underlying financial indicators actually conflict.
- [ ] Use the LLM primarily to explain and contextualize mechanically flagged conflicts, rather than relying on free-form LLM judgment to discover every contradiction.
- [ ] Critic output must include:
  - problem detected;
  - contradiction type;
  - implicated claim IDs;
  - implicated agent(s);
  - suspected root cause;
  - missing evidence, if any;
  - recommended re-analysis scope.
- [ ] Implement the Planner-driven targeted re-analysis loop in `graph.py`.
- [ ] Use a single shared retry counter in Planner state.
- [ ] Keep the hard cap at one retry for the course MVP.
- [ ] Re-run only the implicated agent(s) and necessary downstream dependents rather than restarting the entire pipeline.
- [ ] On retry, preserve prior Shared Memory versions and append new versions so the original reasoning remains auditable.
- [ ] Re-run Verification after the affected analysis is regenerated.
- [ ] Re-run Critic after re-verification when the problem originated in the Critic stage.
- [ ] Implement the `Unresolved` terminal state. If the problem survives the single retry, stop looping and surface the unresolved issue in the final report.
- [ ] Update `agents/report_agent.py` to include:
  - Key Contradictions;
  - Confidence/Support and Uncertainty;
  - Limitations;
  - provenance from the final Shared Memory state.
- [ ] Ensure the report agent never silently selects a side in an unresolved contradiction.

## Exit Criteria

- Bull and Bear generate opposing evidence-backed analyses from the same verified evidence base.
- Bull/Bear cannot introduce unverified evidence as fact.
- Critic detects manually injected contradictions using structured fields where possible.
- Critic distinguishes actual contradictions from legitimate differences in interpretation.
- A re-analysis request contains a concrete scope rather than a generic "try again".
- Re-analysis reruns only the affected component(s) and necessary dependents.
- The system terminates after the single allowed retry.
- A persistent injected contradiction reaches `Unresolved` instead of looping indefinitely.
- The final report explicitly surfaces unresolved contradictions and support limitations.

## Design Notes

Batch 2 implements the opt-in `run_full_pipeline` graph, bounded structured
Bull/Bear interpretations, exact-premise traceability checks, separate append-only
Critic findings and one Planner-owned targeted correction. Earlier entry points
retain their scope. Mechanical Critic coverage is limited to compatible identities,
dimensions, exact source identities and explicit predicates; it does not perform
unrestricted language contradiction detection. No detected finding does not establish
universal consistency. Offline doubles and actual PDFs exercise these mechanics;
live interpretive quality remains unvalidated.

The purpose of Bull/Bear is not to determine a winning investment recommendation. They are adversarial analytical views over the same evidence base. The Critic is a quality-control layer, not a judge that arbitrarily chooses whichever narrative sounds stronger.


Closeout regressions additionally enforce authoritative section membership and
normal rejection of malformed argument numeric snapshots. Those failures use the
same Planner-owned retry budget and terminal partial-report path; no repair call
or retry budget was added to argument generators.
