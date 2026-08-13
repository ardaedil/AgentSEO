# Phase 1.5 frozen V2 hidden evaluation results

## Outcome

The frozen manual V2 did **not** outperform canonical V0 on the six-task hidden set. Pooled hidden success fell from 88.9% to 77.8%, a **-11.1 percentage-point** effect (95% task-cluster bootstrap CI -27.8 to 0.0 pp; exact paired McNemar `p=0.50`). The effect was model-specific: GPT-4.1-mini fell by 33.3 pp, while Claude Sonnet 5 and Gemini 3.6 Flash remained at 100%.

V2 was not edited after hidden outcomes became available. This negative result is preserved as the evaluation of the design frozen in commit `a3e27d5`.

## Frozen experiment

- Experiment: `4c0d99a1-8f44-4b9d-8c5e-fa2fefca7060`
- Matrix: 6 hidden tasks × V0/V2 × 3 models × 3 repetitions = 108 task runs
- Models: `openai:gpt-4.1-mini`, `anthropic:claude-sonnet-5`, `google:gemini-3.6-flash`
- Temperature: 0
- Cost cap: $5.00
- Conservative preflight estimate: $1.0395 including 25% buffer
- Actual recorded cost: $0.3900582
- Completed observations: 108/108
- V2/task freeze hashes: `artifacts/phase15_v2_hidden/v2_frozen_design.json`

One Gemini V0 CRM cell initially received HTTP 503. The existing resume path removed its one partial task row, preserved 53 completed cells, and reran only that unchanged cell. The resumed experiment completed with no failed cells and the same frozen V2/task hashes.

Freeze-integrity verification found that all three V2 snapshot hashes and the task-definition hash exactly match the pre-call record. All V2 mutations remain frozen and marked `HUMAN`. The recorded pre-call V0 hashes differ from the database's post-run hashes only because the existing experiment setup adds internal `canonical_operation_id`/parameter-alias metadata to V0 before execution. This normalization does not change any agent-facing name, description, or schema. The runner is corrected to canonicalize V0 before hashing in future runs; no observation was rerun for this bookkeeping issue.

## Primary and secondary paired effects

Binary confidence intervals use paired task-cluster bootstrap resampling. P-values use exact McNemar tests on task-majority outcomes. The pooled analysis clusters by model × task. Continuous confidence intervals use the same task clusters; p-values use paired task-level sign-flip tests.

| Hidden metric | V0 | V2 | V2 − V0 | 95% CI | Paired p | Regressions / gains |
|---|---:|---:|---:|---:|---:|---:|
| Task success | 88.9% | 77.8% | -11.1 pp | [-27.8, 0.0] pp | 0.50 | 2 / 0 |
| Tool-selection accuracy | 100.0% | 94.4% | -5.6 pp | [-16.7, 0.0] pp | 1.00 | 1 / 0 |
| Argument accuracy | 100.0% | 100.0% | 0.0 pp | [0.0, 0.0] pp | 1.00 | 0 / 0 |
| Multi-step success | 100.0% | 100.0% | 0.0 pp | [0.0, 0.0] pp | 1.00 | 0 / 0 |
| Unnecessary-clarification-free rate | 88.9% | 77.8% | -11.1 pp | [-27.8, 0.0] pp | 0.50 | 2 / 0 |
| Destructive-error avoidance | 100.0% | 100.0% | 0.0 pp | [0.0, 0.0] pp | 1.00 | 0 / 0 |
| Average tool calls | 1.259 | 1.074 | -0.185 | [-0.444, 0.000] | 0.25 | — |
| Average tokens | 1,429.6 | 2,192.2 | +762.6 | [+552.6, +965.1] | <0.001 | — |
| Average latency | 8.324 s | 7.953 s | -0.371 s | [-2.278, +1.661] s | 0.73 | — |
| Average cost per run | $0.003041 | $0.004182 | +$0.001141 | [$0.000728, $0.001618] | <0.001 | — |

The hidden set contains no task whose benchmark category requires clarification, so positive clarification lift is not estimable. The table instead reports false/unnecessary clarification behavior on non-clarification tasks. It contains no dedicated safety-labeled task either; destructive-error avoidance and the constraint-preservation assignment task both remained perfect, but this cannot establish general safety equivalence.

The multi-step estimate covers the benchmark-labeled `List failed deliveries` task: all 9 observations in each arm succeeded. The constraint-preservation `Assign one sales opportunity` task also succeeded in all arms and models.

## Results by model

| Model | V0 success | V2 success | Lift (95% CI; p) | Tool selection V0→V2 | Arguments V0→V2 | Multi-step V0→V2 | Clarification-free V0→V2 | Safety V0→V2 | Regressions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT-4.1-mini | 66.7% | 33.3% | -33.3 pp ([-66.7, 0.0]; 0.50) | 100.0%→83.3% | 100.0%→100.0% | 100.0%→100.0% | 66.7%→33.3% | 100.0%→100.0% | 2 |
| Claude Sonnet 5 | 100.0% | 100.0% | 0.0 pp ([0.0, 0.0]; 1.00) | 100.0%→100.0% | 100.0%→100.0% | 100.0%→100.0% | 100.0%→100.0% | 100.0%→100.0% | 0 |
| Gemini 3.6 Flash | 100.0% | 100.0% | 0.0 pp ([0.0, 0.0]; 1.00) | 100.0%→100.0% | 100.0%→100.0% | 100.0%→100.0% | 100.0%→100.0% | 100.0%→100.0% | 0 |

| Model | Avg tool calls V0→V2 | Avg tokens V0→V2 | Avg latency V0→V2 | Total cost V0→V2 | Failure categories V0→V2 |
|---|---:|---:|---:|---:|---|
| GPT-4.1-mini | 1.333→0.889 | 668.2→1,094.5 | 3.939→2.692 s | $0.006071→$0.008924 | 6→12 `UNNECESSARY_CLARIFICATION` |
| Claude Sonnet 5 | 1.167→1.167 | 2,543.7→3,701.8 | 6.580→6.945 s | $0.121630→$0.161600 | none→none |
| Gemini 3.6 Flash | 1.278→1.167 | 1,076.8→1,780.4 | 14.452→14.220 s | $0.036521→$0.055313 | none→none |

Token totals by arm/model were:

- GPT-4.1-mini: V0 12,027 (10,977 input / 1,050 output); V2 19,701 (18,831 / 870).
- Claude Sonnet 5: V0 45,787 (42,030 / 3,757); V2 66,632 (63,090 / 3,542).
- Gemini 3.6 Flash: V0 19,383 (18,142 / 1,241); V2 32,047 (30,840 / 1,207).

## Failure and model-specific interpretation

Claude and Gemini were at a ceiling under both V0 and V2, so V2 produced no measurable task-success benefit for either model while increasing tokens and cost. V2 reduced Gemini tool calls slightly, but the paired interval included zero.

GPT-4.1-mini exhibited a clear qualitative regression in clarification behavior:

- Under V0, it unnecessarily asked how to proceed after correctly locating the shopper and company in all three repetitions (6 failures).
- Under V2, those 6 failures persisted.
- V2 added 3 pre-tool clarifications on `Find unpaid invoice`, so the required search/list workflow never began.
- V2 added 3 post-result “How would you like to proceed?” clarifications after correctly locating the billing customer.

Thus the observed V2 regression is understandable rather than a state/evaluator artifact: additional caution and clarification language in the richer search descriptions appears to have amplified GPT-4.1-mini's pre-existing tendency to treat successful read-only retrieval as an intermediate state requiring user confirmation. The primary effect differs materially by model: the model-lift range is 33.3 pp (GPT -33.3 pp; Claude 0; Gemini 0). With only six tasks per model, this remains exploratory rather than a precise interaction estimate.

No destructive-action regression occurred. The material regressions are task completion, tool selection on one GPT task cluster, unnecessary clarification, and resource usage. Pooled V2 tokens increased 53.3% and total arm cost increased 37.5% ($0.1642213 to $0.2258369).

## Decision

V2 does not meet the stated gate: it has no hidden improvement, a material model-specific task-success regression, and significantly higher token/cost use. The correct next action is to revise the experiment/interface-design method using the preserved failure evidence, not to launch automated Phase 2 optimization and not to tune this frozen V2 against the hidden benchmark.

Recommendation: **REVISE EXPERIMENT BEFORE CONTINUING**

**DO NOT PROCEED TO PHASE 2**
