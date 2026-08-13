# Phase 1.5B pre-holdout checkpoint

Phase 1.5B has reached its mandatory cost/approval gate. The 120-task benchmark, 80/40 grouped split, leakage audit, V0 development baseline, per-model trace audit, four human interfaces, exact snapshots, hashes, and mutation lineage are complete.

Stage A used `openai:gpt-4.1-mini`, `anthropic:claude-sonnet-5`, and `google:gemini-3.6-flash` for 480 task runs at $2.2101356 actual estimated API cost. The raw evaluator scores were 53.8%, 95.0%, and 84.4%. After auditing normalization/evaluator artifacts without overwriting raw observations, the scores were 60.0%, 98.1%, and 91.9%.

The audit identified a refusal-normalization defect and two unsupported-semantics required-call mismatches. Evaluator v2 corrects those issues before holdout evaluation. Task IDs, split membership, initial-state hashes, backend behavior, and deterministic state assertions remain unchanged.

All five interfaces are frozen. There were zero holdout task runs at freeze. The full Stage B matrix is estimated at $13.86 ($17.33 guarded), exceeding the $5 per-launch cap. The cap-compliant six-launch plan is documented in `docs/phase15b_stage_b_plan.md` and awaits explicit approval.

No holdout results, compatibility matrix, lift estimates, statistical tests, final research exports, or Phase 2 recommendation exist yet. Producing them before the approved holdout run would be scientifically invalid.
