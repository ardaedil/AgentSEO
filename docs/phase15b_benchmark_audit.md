# Phase 1.5B benchmark and leakage audit

## Scope

Phase 1.5B defines a fresh 120-task benchmark across SaaS Billing, E-commerce, and CRM. It does not modify, delete, overwrite, or reinterpret any Phase 1.5 task, split, interface, database, manifest, trace, dataset, report, or experiment identifier.

The benchmark contains 60 independent scenario groups with two natural-language phrasings per scenario. Both phrasings are always assigned to the same split, preventing paraphrase leakage from development into holdout.

## Distribution

| Domain | Tasks |
|---|---:|
| SaaS Billing | 40 |
| E-commerce | 40 |
| CRM | 40 |
| **Total** | **120** |

| Category | Tasks | Scenario groups |
|---|---:|---:|
| Ambiguous tool selection | 6 | 3 |
| Clarification required | 18 | 9 |
| Clarification not required | 12 | 6 |
| Multi-step execution | 12 | 6 |
| Error recovery | 18 | 9 |
| Tool overlap | 6 | 3 |
| Identifier routing | 12 | 6 |
| Constraint preservation | 6 | 3 |
| Safety confirmation | 6 | 3 |
| Safety refusal | 6 | 3 |
| Distractor tools | 6 | 3 |
| Post-success behavior | 6 | 3 |
| Unsupported semantics | 6 | 3 |

## Difficulty and diagnostic depth

The cases deliberately cover zero/multiple matches, overlapping read operations, direct resource identifiers, 2–4-step workflows, uniquely authorized destructive actions, ambiguous destructive requests, refusal-worthy concealment requests, post-success stopping, invalid states, temporary failures, stale identifiers, and replacement identifiers supplied by an error response.

Task-scoped fault injection is deterministic and reset with every task. It does not modify canonical tool behavior for tasks without a declared fault. Recovery evaluation separately records repeated identical failures, successful continuation after an error, changed arguments, and tool switching.

Semantic argument expectations are declared only where the benchmark has an unambiguous expected resource or mutation value. Schema validity remains a separate metric and is not treated as semantic correctness.

## Leakage rules

The complete instruction set is checked automatically by `test_phase15b.py`. The audit rejects:

- canonical operation names such as underscore-delimited internal tool identifiers;
- instructions telling the model to “call the tool”;
- references to operation names, parameter names, or HTTP/API methods;
- any split of the two phrasings for one scenario across development and holdout.

User-visible resource IDs such as `cus_...`, `sub_...`, `ord_...`, `inv_...`, `co_...`, and `opp_...` are intentionally retained in identifier-routing and error-recovery tasks because they are normal inputs to the evaluated workflows. Natural business terms such as customer, status, refund, owner, and invoice are not considered implementation leakage.

Automated audit result at freeze: **120/120 instructions passed**.

## Fresh sealed split

The split seed is `1502`. Allocation is performed at the 60-scenario-group level and stratified by task category:

- 40 development scenario groups = 80 tasks;
- 20 sealed holdout scenario groups = 40 tasks.

The sealed manifest contains task IDs, task versions, evaluator versions, and hashes of initial states, but no task titles or instructions. Its cryptographic hash is written to the Phase 1.5B protocol and subsequent experiment manifests.

After sealing, interface design may inspect development tasks and traces only. Holdout content and outcomes remain unavailable until every interface snapshot is frozen and hashed.

## Known limitations

- Two phrasings of each scenario improve wording robustness but are not independent semantic tasks; paired inference therefore clusters at the scenario/task level and preserves repetitions.
- The benchmark remains synthetic and uses three resettable domains. It measures controlled interface compatibility, not production business outcomes.
- Calibration targets 60–85% V0 development success as a diagnostic range, but tasks will not be altered merely to force a preferred score.
