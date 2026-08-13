# AgentSEO Phase 1.5B R2 sealed-holdout results

The complete preregistered 1,620-observation matrix was analyzed only after execution finished. No interface, task, evaluator, model, repetition, or statistical method changed after unsealing.

## Hidden-success matrix

| Interface | GPT | Claude | Gemini |
|---|---:|---:|---:|
| V0 | 52.8% | 78.7% | 69.4% |
| V2-General | 54.6% | 79.6% | 65.7% |
| V2-GPT | 51.9% | 76.9% | 66.7% |
| V2-Claude | 53.7% | 73.1% | 63.0% |
| V2-Gemini | 52.8% | 75.9% | 64.8% |

## Complete cell metrics

| Model | Interface | Success (95% task-cluster CI) | Tool selection | Semantic args | Multi-step | Clarification | Recovery | Safety | Calls | Tokens | Latency | Cost |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT | V0 | 52.8% [37.0%, 67.6%] | 77.8% | 70.4% | 27.8% | 94.4% | 66.7% | 44.4% | 1.88 | 1024 | 5.70s | $0.0581 |
| GPT | V2-General | 54.6% [38.9%, 69.4%] | 81.5% | 87.0% | 44.4% | 94.4% | 88.9% | 33.3% | 1.89 | 1946 | 6.06s | $0.0980 |
| GPT | V2-GPT | 51.9% [38.0%, 65.7%] | 78.7% | 81.5% | 38.9% | 88.9% | 55.6% | 33.3% | 1.94 | 1912 | 6.74s | $0.0960 |
| GPT | V2-Claude | 53.7% [38.0%, 69.4%] | 75.9% | 77.8% | 33.3% | 100.0% | 83.3% | 33.3% | 1.80 | 1873 | 5.82s | $0.0940 |
| GPT | V2-Gemini | 52.8% [38.0%, 67.6%] | 79.6% | 85.2% | 33.3% | 100.0% | 83.3% | 22.2% | 1.73 | 1763 | 4.98s | $0.0889 |
| Claude | V0 | 78.7% [65.7%, 89.8%] | 92.6% | 79.6% | 22.2% | 100.0% | 100.0% | 100.0% | 2.11 | 4176 | 12.40s | $1.4231 |
| Claude | V2-General | 79.6% [66.7%, 90.7%] | 91.7% | 77.8% | 38.9% | 100.0% | 100.0% | 77.8% | 2.03 | 5678 | 9.88s | $1.6195 |
| Claude | V2-GPT | 76.9% [63.0%, 88.9%] | 88.0% | 77.8% | 38.9% | 100.0% | 100.0% | 77.8% | 2.00 | 5487 | 11.32s | $1.5717 |
| Claude | V2-Claude | 73.1% [59.3%, 86.1%] | 84.3% | 77.8% | 11.1% | 100.0% | 100.0% | 77.8% | 1.89 | 5446 | 8.60s | $1.5783 |
| Claude | V2-Gemini | 75.9% [63.0%, 88.0%] | 86.1% | 77.8% | 27.8% | 100.0% | 100.0% | 88.9% | 1.95 | 5430 | 12.53s | $1.5813 |
| Gemini | V0 | 69.4% [55.6%, 82.4%] | 93.5% | 83.3% | 33.3% | 100.0% | 77.8% | 100.0% | 2.74 | 2239 | 13.62s | $0.4607 |
| Gemini | V2-General | 65.7% [50.9%, 79.6%] | 89.8% | 83.3% | 27.8% | 100.0% | 100.0% | 44.4% | 2.31 | 3073 | 14.59s | $0.5875 |
| Gemini | V2-GPT | 66.7% [50.9%, 81.5%] | 88.9% | 83.3% | 22.2% | 100.0% | 100.0% | 55.6% | 2.24 | 2911 | 11.84s | $0.5608 |
| Gemini | V2-Claude | 63.0% [47.2%, 77.8%] | 86.1% | 83.3% | 16.7% | 100.0% | 94.4% | 44.4% | 2.24 | 3015 | 10.85s | $0.5742 |
| Gemini | V2-Gemini | 64.8% [49.1%, 79.6%] | 88.9% | 83.3% | 16.7% | 100.0% | 100.0% | 55.6% | 2.21 | 2889 | 10.90s | $0.5535 |

## Preregistered paired comparisons

| Model | Comparison | Effect | 95% task CI | 95% family sensitivity CI | Exact p | Gained | Regressed | Unchanged | Δ tokens | Δ latency | Δ cost/obs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPT | V2-General − V0 | +1.9 pp | [-13.9 pp, +17.6 pp] | [-18.5 pp, +22.2 pp] | 1.0000 | 6 | 7 | 23 | +922 | +0.36s | $+0.00037 |
| GPT | V2-GPT − V0 | -0.9 pp | [-14.8 pp, +13.0 pp] | [-15.7 pp, +15.7 pp] | 1.0000 | 7 | 9 | 20 | +887 | +1.05s | $+0.00035 |
| GPT | V2-Claude − V0 | +0.9 pp | [-13.0 pp, +14.8 pp] | [-16.7 pp, +18.5 pp] | 1.0000 | 7 | 6 | 23 | +849 | +0.12s | $+0.00033 |
| GPT | V2-Gemini − V0 | +0.0 pp | [-13.9 pp, +14.8 pp] | [-15.7 pp, +17.6 pp] | 1.0000 | 7 | 8 | 21 | +739 | -0.71s | $+0.00029 |
| Claude | V2-General − V0 | +0.9 pp | [-9.3 pp, +10.2 pp] | [-10.2 pp, +12.0 pp] | 0.6250 | 7 | 5 | 24 | +1503 | -2.52s | $+0.00182 |
| Claude | V2-GPT − V0 | -1.9 pp | [-13.9 pp, +10.2 pp] | [-20.4 pp, +13.9 pp] | 0.6875 | 6 | 5 | 25 | +1311 | -1.08s | $+0.00138 |
| Claude | V2-Claude − V0 | -5.6 pp | [-16.7 pp, +5.6 pp] | [-21.3 pp, +8.3 pp] | 0.2188 | 4 | 6 | 26 | +1270 | -3.80s | $+0.00144 |
| Claude | V2-Gemini − V0 | -2.8 pp | [-13.9 pp, +8.3 pp] | [-18.5 pp, +8.3 pp] | 0.3750 | 6 | 7 | 23 | +1254 | +0.13s | $+0.00147 |
| Gemini | V2-General − V0 | -3.7 pp | [-15.7 pp, +7.4 pp] | [-17.6 pp, +9.3 pp] | 0.3750 | 6 | 6 | 24 | +834 | +0.97s | $+0.00117 |
| Gemini | V2-GPT − V0 | -2.8 pp | [-14.8 pp, +8.3 pp] | [-16.7 pp, +10.2 pp] | 0.6250 | 6 | 6 | 24 | +671 | -1.77s | $+0.00093 |
| Gemini | V2-Claude − V0 | -6.5 pp | [-18.5 pp, +5.6 pp] | [-20.4 pp, +6.5 pp] | 0.3750 | 4 | 6 | 26 | +775 | -2.77s | $+0.00105 |
| Gemini | V2-Gemini − V0 | -4.6 pp | [-16.7 pp, +7.4 pp] | [-18.5 pp, +9.3 pp] | 0.6250 | 5 | 6 | 25 | +649 | -2.72s | $+0.00086 |
| GPT | V2-GPT − V2-General | -2.8 pp | [-13.9 pp, +7.4 pp] | [-16.7 pp, +8.3 pp] | 0.7266 | 4 | 6 | 26 | -35 | +0.68s | $-0.00002 |
| Claude | V2-Claude − V2-General | -6.5 pp | [-13.9 pp, +0.0 pp] | [-17.6 pp, +1.9 pp] | 0.5000 | 1 | 5 | 30 | -232 | -1.28s | $-0.00038 |
| Gemini | V2-Gemini − V2-General | -0.9 pp | [-5.6 pp, +3.7 pp] | [-5.6 pp, +2.8 pp] | 1.0000 | 1 | 3 | 32 | -184 | -3.69s | $-0.00031 |

## Model-specific advantage

- GPT: V2-GPT − V2-General = -2.8 pp.
- Claude: V2-Claude − V2-General = -6.5 pp.
- Gemini: V2-Gemini − V0 = -4.6 pp.

## Cross-model transfer

- V2-GPT on Claude: -1.9 pp versus V0; 6 tasks gained, 5 regressed.
- V2-GPT on Gemini: -2.8 pp versus V0; 6 tasks gained, 6 regressed.
- V2-Claude on GPT: +0.9 pp versus V0; 7 tasks gained, 6 regressed.
- V2-Claude on Gemini: -6.5 pp versus V0; 4 tasks gained, 6 regressed.
- V2-Gemini on GPT: +0.0 pp versus V0; 7 tasks gained, 8 regressed.
- V2-Gemini on Claude: -2.8 pp versus V0; 6 tasks gained, 7 regressed.

## Pareto-efficient interfaces

- GPT: V0, V2-General, V2-Claude, V2-Gemini.
- Claude: V0, V2-General, V2-GPT, V2-Claude.
- Gemini: V0, V2-GPT, V2-Claude, V2-Gemini.

## Explicit answers

- Did V2-General outperform V0 on unseen task families? Effects were +1.9 pp, +0.9 pp, -3.7 pp for GPT, Claude, and Gemini.
- Did V2-GPT outperform V0 for GPT? Effect: -0.9 pp.
- Did V2-Claude outperform V0 for Claude? Effect: -5.6 pp.
- Did V2-Gemini outperform V0 for Gemini? Effect: -4.6 pp.
- Did each model-specific interface outperform V2-General for its intended model? GPT -2.8 pp, Claude -6.5 pp, Gemini -0.9 pp.
- How well did model-specific interfaces transfer? Cross-transfer effects ranged from -6.5 pp to +0.9 pp; the detailed table reports gains and regressions for every non-intended model.
- Is there credible evidence of different interface optima by model family? Best hidden interfaces were GPT=V2-General, Claude=V2-General, Gemini=V0.
- Were reliability improvements worth token/cost/latency changes? Reliability, token, latency, and cost deltas are reported pairwise; non-dominated choices are listed as Pareto-efficient rather than collapsed into a composite score.
- Did optimized interfaces introduce safety regressions? 12 model/interface cells had lower safety success than V0.

## Conclusion

NO-GO — MORE VALIDATION REQUIRED
