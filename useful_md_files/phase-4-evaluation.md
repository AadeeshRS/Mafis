# Phase 4 — Evaluation

## Goal

Batch 2 supplies executable offline conditions, pairing checks, injected-error
metrics, source inventory/acquisition records, threshold-freeze utilities and blank
blind-review materials. This does not complete scientific evaluation: live Gemini
quality/ablations, held-out model-quality inference and human ratings remain pending.
New-layout extraction failures and blocked official downloads remain in accounting.
The engineering gate default is still explicitly uncalibrated; an injected-case
operating-point study is not broad real-world calibration.

Determine experimentally whether MAFIS's added structure actually improves financial-analysis reliability and quality.

Do not assume that every component helps. The literature contains cases where calculator/tool separation improves numerical reasoning while critic-based reflection is inconsistent, and cases where larger agent groups help complex tasks but hurt simpler ones. The evaluation must therefore isolate individual contributions.

## Tasks

- [ ] Build a manually annotated ground-truth set of 10–15 real company reports with known-correct figures, source locations, and representative analytical claims.
- [ ] Include deliberately injected:
  - numerical errors,
  - citation errors,
  - unsupported claims,
  - temporal inconsistencies,
  - contradictory financial interpretations.
- [ ] Build a retrieval benchmark containing representative queries with human-labelled relevant evidence passages/pages.
- [ ] Run the single-LLM baseline and full MAFIS on exactly the same companies, documents, and user questions.
- [ ] Record:
  - numerical correctness,
  - unsupported claim rate,
  - citation coverage,
  - evidence retrieval Recall@k / Hit@k where labels are available,
  - verification precision/recall on injected verification cases,
  - contradiction detection precision/recall,
  - support/confidence calibration,
  - analytical coverage/depth,
  - end-to-end latency,
  - token/API cost.
- [ ] Run component ablations on the same dataset:
  - MAFIS without Verification,
  - MAFIS without Bull/Bear,
  - MAFIS without Critic,
  - MAFIS without the re-analysis loop,
  - MAFIS without the Deterministic Financial Engine,
  - MAFIS with a unified analyst instead of specialized analysis agents.
- [ ] For the specialization ablation, keep the same base model, evidence access, and tools so the comparison isolates task decomposition rather than model capability.
- [ ] For the deterministic-engine ablation, compare against a version in which the LLM is allowed to produce the numerical reasoning/output under otherwise comparable conditions.
- [ ] Evaluate the Health Gate threshold on validation data before using the final test set. Do not tune the threshold directly on the test results.
- [ ] Collect blind human ratings of final-report quality. Reviewers should not know whether a report came from the baseline, full MAFIS, or an ablation.
- [ ] Rate at least:
  - factual accuracy,
  - evidence quality,
  - analytical coverage,
  - internal consistency,
  - clarity/readability.
- [ ] Measure the cost of the reliability mechanisms themselves:
  - extra LLM calls,
  - retrieval calls,
  - calculation calls,
  - latency added by verification,
  - latency added by Bull/Bear/Critic,
  - latency added by re-analysis.
- [ ] Report negative findings explicitly. If a component does not improve reliability, causes extra cost without measurable benefit, or degrades performance on some task, record that result rather than hiding it.
- [ ] Perform a small error analysis identifying where MAFIS succeeds and fails relative to the baseline.

## Exit Criteria

- The baseline and full MAFIS have been evaluated on the same test set.
- Retrieval quality is reported with an actual metric rather than described qualitatively.
- At least one numerical-reliability ablation and one specialization/collaboration ablation are completed.
- Verification and contradiction detection are evaluated against labelled/injected cases.
- Report quality is evaluated blindly by human reviewers.
- Latency and cost are reported alongside reliability metrics.
- The final analysis identifies which components measurably contribute to reliability and which do not.

## Design Notes

The purpose of Phase 4 is not to prove MAFIS is better by default. The purpose is to test the research question honestly. A result showing that a component is unnecessary or only useful for certain task types is still a valuable finding.


Closeout status and measured denominators are in `evaluation/results.md`. Amazon,
Meta and PepsiCo were explicitly reclassified from test to parser development after
compatibility exposure. Their later success cannot establish untouched held-out
performance. SDK identity/usage manifests distinguish real live calls from injected
SDK responses and mocks, slice reused adapters per condition and leave missing
usage/billing unknown. One closeout comparator attempt returned HTTP503 and halted
the shared 12-attempt ledger; no live principal pair completed. Blind human ratings
remain pending. Original scientific exit criteria above are unchanged.
