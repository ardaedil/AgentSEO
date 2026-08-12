# Phase 1.5 manual optimization log

V2 is a human-authored, frozen general interface. The runner executes V0 on development tasks and stores the observed development failure histogram before creating V2. Hidden outcomes are unavailable until all variants are frozen.

| Observed/anticipated development failure | Hypothesis | Interface change | Expected effect |
|---|---|---|---|
| Search and unique-ID retrieval are easy to confuse | Explicit semantic boundaries reduce wrong-tool calls | State intended identifier type and when broad search or exact retrieval must not be used | Lower `WRONG_TOOL` |
| Generic `id`, `q`, or body fields invite wrong values | Parameter meaning matters independently of schema type | Describe required identifiers and required fields | Lower `MISSING_ARGUMENT` and `WRONG_ARGUMENT` |
| Cancellation, deletion, termination, and refund overlap | Negative safety constraints prevent destructive substitution | Require a unique target and authorization; prohibit lookup/search use | Lower `DESTRUCTIVE_ACTION_ERROR` |
| A rejected identifier can terminate the attempt | Recovery guidance encourages a bounded retry or clarification | Require reject-then-success traces and advise input inspection | Higher error-recovery rate |
| Long explanations may distract some models | Description length may have model-specific optima | Keep V2 moderate; test concise and verbose alternatives separately | Reveal cross-model preference without hidden-task tuning |

Every V2 description is generated from canonical operation semantics. No backend behavior, task, initial state, expected state, evaluator, or provider setting changes with V2.

## Local system-validation checkpoint

Experiment `f67c4e98-9d5b-4046-bed3-2ed5889a5bbb` produced no MockAgent baseline failures. V2 was therefore not adapted to synthetic outcomes. OpenAI, Anthropic, and Gemini were unavailable, so no real development failure trace was used and no claim of optimization lift is made.
