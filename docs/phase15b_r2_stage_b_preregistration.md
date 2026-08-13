# Phase 1.5B R2 sealed-holdout preregistration

Status: preregistered before holdout access. No provider call is authorized by this document.

## Frozen matrix

- 36 sealed tasks from 12 unseen families.
- Models: `openai:gpt-4.1-mini`, `anthropic:claude-sonnet-5`, `google:gemini-3.6-flash`.
- Interfaces: V0, V2-General, V2-GPT, V2-Claude, V2-Gemini.
- Three repetitions at temperature 0, no provider seed, max 16 iterations, max 12 tool calls.
- 1,620 task runs total: 540 per model and 108 per model/interface cell.
- No task, evaluator, interface, sandbox, model, or request-setting changes after unsealing.

## Preregistered comparisons

Primary comparisons:

1. V2-General versus V0 separately for GPT, Claude, and Gemini.
2. V2-GPT versus V0 on GPT.
3. V2-Claude versus V0 on Claude.
4. V2-Gemini versus V0 on Gemini.

Cross-transfer comparisons:

- V2-GPT on Claude and Gemini.
- V2-Claude on GPT and Gemini.
- V2-Gemini on GPT and Claude.

The primary outcome is hidden task success. Secondary outcomes are tool selection, semantic and schema argument accuracy, clarification behavior, error recovery, safety, multi-step completion, regression count, tool calls, latency, tokens, and cost. Pooled results accompany model-specific results but do not replace them.

## Statistical analysis

- Pair observations within model, task, and trial against contemporaneous V0.
- Report absolute V0→variant success lift and 95% task-cluster bootstrap intervals, preserving repetitions within task clusters.
- Use the existing exact McNemar test on task-majority paired outcomes.
- Report regression count and baseline-only/treatment-only discordant pairs.
- Treat task-family-cluster bootstrap as a sensitivity analysis because each held-out family has three phrasings.
- Report Wilson intervals for individual rates.
- Report all preregistered comparisons; do not select only favorable model/interface pairs.
- P-values are exploratory because several interfaces, models, and secondary outcomes are compared.

No interface tuning, task replacement, evaluator revision, or benchmark reinterpretation is permitted after holdout access. A failed interface remains a result.

## Integrity bindings

- Benchmark SHA-256: `4568fc82c24d096d8e5fc0d147e17a4f4c9b56a59beb437167d5341c9e963247`.
- Holdout manifest SHA-256: `2ad4a55afd04926fe0eaae4e5ee53d5859756102fce2ef79fe9b3b18da6d69ba`.
- Interface freeze SHA-256: `b905b769f25f56c7a8f8057d085494d9d7b2d2285c2084485bfa93fc50847a34`.
- Holdout task runs at preregistration: 0.

## Cost gate

Calibration-based estimates include frozen-interface description-token deltas:

| Model | Task runs | Expected requests | Estimated tokens | Estimated cost | 25% guarded |
|---|---:|---:|---:|---:|---:|
| GPT-4.1-mini | 540 | 1,639 | 0.846M | $0.41 | $0.51 |
| Claude Sonnet 5 | 540 | 1,781 | 2.823M | $8.62 | $10.77 |
| Gemini 3.6 Flash | 540 | 2,006 | 1.507M | $2.78 | $3.47 |
| **Total** | **1,620** | **5,426** | **5.176M** | **$11.81** | **$14.76** |

The conservative four-request allowance is 6,480 model requests. The full guarded estimate exceeds `PHASE15_MAX_COST_USD=5.00`; automatic launch is prohibited. Explicit approval and a cap-compliant execution plan are required before unsealing.
