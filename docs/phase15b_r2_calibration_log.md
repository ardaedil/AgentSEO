# Phase 1.5B R2 calibration log

## Calibration A v1 — invalidated evaluator pass

- 24 families, one task per family, one repetition, all three models.
- Actual cost: $0.4118184.
- Stored success: GPT 37.5%, Claude 75.0%, Gemini 70.8%.
- Invalidated for difficulty decisions after trace audit found strict non-terminal call limits, non-equivalent free-text matching, an exclusive implementation of an inclusive minimum filter, and one instruction missing the email it said was available.
- Raw rows remain in `artifacts/phase15b_r2/calibration_a_v1`.

## Calibration A v2 — corrected evaluator

- Same deterministic 24-family selection and one repetition.
- One Gemini cell was resumed after a provider 503; the other 57 observations were not repeated.
- Actual cost: $0.4090697.
- GPT: 15/24, 62.5% — within the approximate 55–75% target.
- Claude: 23/24, 95.8% — still a severe ceiling.
- Gemini: 18/24, 75.0% — within the approximate 65–85% target.

The remaining Claude failure was itself a workflow-specification mismatch: the evaluator required a post-refund customer retrieval although the sampled wording only required preserving service. Audited Claude performance was therefore effectively 24/24. R2 was not split or sealed.

## Candidate revision for Calibration A v3

The candidate pool retains 120 tasks, 40 families, and the same ten-category distribution. Eight calibration-eligible families were revised from direct operations into realistic audit workflows that explicitly require post-action verification, conditional execution after error semantics, or comparison of multiple related states. These revisions preferentially replace tasks that GPT already failed in v2, limiting the risk that stronger Claude headroom is purchased by pushing GPT below its useful range.

Calibration A v3 must run before Calibration B. No R2 holdout exists.
