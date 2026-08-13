# Phase 1.5 checked-in study data

This directory contains the reproducibility manifest and observation-level export for experiment `f67c4e98-9d5b-4046-bed3-2ed5889a5bbb`.

- 53 tasks across billing, ecommerce, and CRM
- fixed seed 42 split: 38 development, 15 hidden
- 15 interfaces per domain, including V0–V7, four isolated mutations, and 10/25/50-tool exposure
- 3 repetitions
- 2,385 observations
- exact runnable model: `mock:reliable`
- skipped: OpenAI, Anthropic, and Google/Gemini because their API keys were unavailable
- recorded provider cost: $0.00
- decision: `DO NOT PROCEED YET`

The MockAgent data validates the experiment machinery only. It must not be used as evidence that interface changes do or do not affect real models. The manifest points to the exact code commit used to produce the dataset.

`experiment_results.jsonl` contains nested interface features suitable for research. The CSV is a compact tabular projection.
