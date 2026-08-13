# Phase 1.5B R2 hard-benchmark audit

Status: frozen benchmark; sealed holdout unopened.

## Construction

R2 contains 120 manually specified tasks in 40 first-class task families. Each family contains three natural-language phrasings of one workflow structure. There are 12 tasks in each of ten diagnostic categories: clarification required, clarification unnecessary, multi-step execution, error recovery, safety/destructive behavior, tool overlap, identifier routing, constraint preservation, unsupported semantics, and post-success termination.

Difficulty distribution is 33 difficulty-6, 51 difficulty-7, and 36 difficulty-8 tasks. Domain distribution is Billing 57, E-commerce 33, and CRM 30. The domain imbalance is a documented limitation caused by Billing exposing the broadest related set of state-changing objects; final analysis must report domains separately as well as pooled.

## Leakage audit

The automated leakage test checks all instructions against exposed operation IDs, high-information schema parameter names, and meta phrases such as “call the tool” or “API.” All 120 tasks pass. Manual review confirms ordinary product language rather than tool-description copying. Resource identifiers such as `cus_`, `ord_`, and `inv_` appear only where a realistic user possesses a system reference and identifier routing is the behavior under test.

## Family-level split

Twenty-eight complete families form the 84-task development split. Twelve complete families that were excluded from every calibration form the 36-task sealed holdout. There is zero family overlap and no sibling phrasing crosses the split.

The sealed holdout covers every required category:

| Category | Tasks |
|---|---:|
| Clarification required | 3 |
| Clarification unnecessary | 3 |
| Multi-step execution | 6 |
| Error recovery | 6 |
| Safety/destructive | 3 |
| Tool overlap | 3 |
| Identifier routing | 3 |
| Constraint preservation | 3 |
| Unsupported semantics | 3 |
| Post-success termination | 3 |

No holdout instruction, expected state, or family name is disclosed in this document.

## Frozen integrity

- Evaluator: `phase15b-r2-deterministic-v2`.
- Benchmark SHA-256: `4568fc82c24d096d8e5fc0d147e17a4f4c9b56a59beb437167d5341c9e963247`.
- Holdout manifest SHA-256: `2ad4a55afd04926fe0eaae4e5ee53d5859756102fce2ef79fe9b3b18da6d69ba`.
- Development families/tasks: 28 / 84.
- Holdout families/tasks: 12 / 36.
- Holdout task runs at freeze: 0.

The immutable local manifest contains only task IDs, versions, family hashes, and definition hashes—not task text.
