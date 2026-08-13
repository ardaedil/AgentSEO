# Phase 1.5B Stage B sealed-holdout execution plan

## Full requested matrix

- 40 sealed holdout tasks
- 5 frozen interfaces: V0, V2-General, V2-GPT, V2-Claude, V2-Gemini
- 3 models
- 3 repetitions
- 1,800 task runs
- approximately 7,200 provider requests (four-call planning allowance)
- estimated 2.70M input and 0.54M output tokens in aggregate

Conservative provider estimates:

| Provider / exact model | Task runs | Estimated cost | 25% guarded estimate |
|---|---:|---:|---:|
| OpenAI / `gpt-4.1-mini` | 600 | $4.86 | $6.08 |
| Anthropic / `claude-sonnet-5` | 600 | $7.20 | $9.00 |
| Google / `gemini-3.6-flash` | 600 | $1.80 | $2.25 |
| **Total** | **1,800** | **$13.86** | **$17.33** |

The complete launch exceeds `PHASE15_MAX_COST_USD=5.00`, so no holdout provider call has been made.

## Proposed cap-compliant staged launches

Every launch contains all five interfaces and complete 40-task holdout blocks; no outcomes are inspected or used to modify interfaces between launches.

| Launch | Provider | Repetitions | Task runs | Estimated cost | Guarded estimate |
|---|---|---:|---:|---:|---:|
| 1 | Gemini | 3 | 600 | $1.80 | $2.25 |
| 2 | GPT | 2 | 400 | $3.24 | $4.05 |
| 3 | GPT | 1 | 200 | $1.62 | $2.03 |
| 4 | Claude | 1 | 200 | $2.40 | $3.00 |
| 5 | Claude | 1 | 200 | $2.40 | $3.00 |
| 6 | Claude | 1 | 200 | $2.40 | $3.00 |

Trials retain global trial numbers 1–3 when combined. Each launch must verify the frozen manifest hash, evaluator version, task split, model ID, and zero prior mutation of interface snapshots. The combined analysis must cluster repeated trials by task and compare all variants against contemporaneous V0 observations.

Approval is required before Launch 1 because the requested full matrix exceeds the per-launch cap even though each proposed stage is below it.
