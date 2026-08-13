# Phase 1.5B R2 calibration log

## Calibration A v1 — invalidated evaluator pass

- 24 families, one task per family, one repetition, all three models.
- Actual cost: $0.4118184.
- Stored success: GPT 37.5%, Claude 75.0%, Gemini 70.8%.
- Invalidated for difficulty decisions after trace audit found strict non-terminal call limits, non-equivalent free-text matching, an exclusive implementation of an inclusive minimum filter, and one instruction missing the email it said was available.
- Raw rows remain in `artifacts/phase15b_r2/calibration_a_v1`.

## Calibration A v2 — corrected evaluator, benchmark still too easy

- Same deterministic 24-family selection and one repetition.
- One Gemini cell was resumed after a provider 503; the other 57 observations were not repeated.
- Actual cost: $0.4090697.
- GPT: 15/24 (62.5%).
- Claude: 23/24 (95.8%), with the remaining miss attributable to a workflow-specification mismatch.
- Gemini: 18/24 (75.0%).

R2 was not split or sealed. Eight eligible families were revised into realistic audit, conditional, state-comparison, and recovery workflows.

## Calibration A v3 — preliminary headroom achieved

- 24 families, one task per family, one repetition, all three models.
- Actual cost: $0.4751016.
- GPT: 18/24 (75.0%).
- Claude: 20/24 (83.3%).
- Gemini: 18/24 (75.0%).

All three models showed measurable preliminary headroom, authorizing one-repetition Calibration B on the 84 development-eligible tasks.

## Calibration B — complete R2 V0 development pass

- Experiment: `3efaa755-bb11-4261-9209-66519a8d5d99`.
- 84 tasks from 28 development families × 3 models × 1 repetition = 252 observations.
- Actual API cost: $1.6807296.
- A Gemini billing cell returned transient 503 errors and a Claude CRM cell returned transient 529 errors. The resume workflow reran only missing provider/domain cells.

The terminal audit found four explicit safety refusals that the text normalizer did not recognize. The stored terminal messages and traces were retained unchanged; only deterministic terminal-behavior fields were re-adjudicated. A second audit found that optional server-side filters had been treated as mandatory despite equivalent correct collection retrieval, and that one valid precondition lookup was counted as a post-success overrun. Ten observations were deterministically promoted after those equivalence fixes. No provider was called for either repair.

Final audited V0 development success:

| Model | Success | Rate | Remaining headroom |
|---|---:|---:|---:|
| GPT-4.1-mini | 54/84 | 64.3% | 35.7 points |
| Claude Sonnet 5 | 72/84 | 85.7% | 14.3 points |
| Gemini 3.6 Flash | 67/84 | 79.8% | 20.2 points |

Claude is 0.7 points above the approximate 65–85% target band but remains below the explicit 90% ceiling-review threshold and retains twelve observed failures. The benchmark therefore has meaningful, if narrower, Claude headroom.

## Evaluator corrections retained in R2 v2

- Explicit refusal normalization for delete/erase/alter/decline and ethical-objection forms.
- Targeted clarification recognition and refusal precedence over incidental questions.
- Semantic containment for equivalent names such as `Acme` and `Acme Inc.`.
- Optional status filters accepted when the correct collection is retrieved and the correct entity/action is deterministically verified.
- Inclusive CRM minimum-value filtering (`>=`).
- Ordered required sequences, bounded justified tool calls, recovery-mode semantics, and separate schema/semantic argument checks.
- A valid `get_order` precondition read is permitted before shipment-conditioned refund execution.

The final evaluator version is `phase15b-r2-deterministic-v2`.
