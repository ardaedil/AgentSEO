# Phase 1.5 benchmark audit

## Findings

The pre-study audit identified four material threats to validity:

1. Executable templates generated 51 tasks while the checked-in manifest claimed 53.
2. Generic instructions said “using `operation_name`,” directly leaking the evaluator label to the model.
3. Many generic tasks had no state assertions and could pass after a rejected sandbox call merely because the required tool name appeared.
4. Billing account termination, invoice refund, and CRM contact listing were not fully executable in the resettable sandbox.

These defects would suppress interface sensitivity and confound failure attribution.

## Corrections applied before the study

- Replaced operation-name prompts with domain-realistic requests that express user intent without literal operation identifiers.
- Added two deterministic ambiguity/safety tasks, bringing executable and exported counts to exactly 53.
- Added final-state assertions and invariants for state-changing templates.
- Made recovery tasks require an observed rejected call followed by a successful retry.
- Changed non-rejecting search/list duplicates from fake recovery tasks to semantic-boundary selection tasks.
- Completed canonical sandbox behavior for account termination, paid-invoice refund, contact listing, and order filtering.
- Regenerated `examples/benchmark_dataset.json` from executable templates to prevent drift.

The corrections apply identically to every interface variant. They do not expose hidden outcomes and were not selected to favor V2.

## Post-correction checks

- 53 executable tasks across 23 operations and 3 domains.
- Zero literal operation identifiers in natural-language instructions.
- Difficulty levels include 1, 5, and 7 in every domain.
- Destructive requests include explicit authorization or are clarification/safety tasks.
- Evaluator-only canonical labels remain stored for deterministic scoring and translation, never in real-provider prompts.

