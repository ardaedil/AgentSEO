# Phase 1.5B R2 hard-benchmark audit

Status: unsplit calibration candidate pool. No R2 holdout exists yet.

## Construction

R2 contains 120 manually specified tasks in 40 first-class task families. Each family contains three natural-language phrasings of one workflow structure. There are four families and 12 tasks in each of ten diagnostic categories: clarification required, clarification unnecessary, multi-step execution, error recovery, safety/destructive behavior, tool overlap, identifier routing, constraint preservation, unsupported semantics, and post-success termination.

The pool contains 33 difficulty-6, 51 difficulty-7, and 36 difficulty-8 tasks. Billing currently contributes 57 tasks, e-commerce 33, and CRM 30. This domain imbalance is a documented limitation caused by the billing API exposing the broadest set of related state-changing operations; final analysis must report domains separately rather than treating the pooled rate as domain-balanced.

## Structural leakage control

Twelve complete families are excluded from Calibration A and Calibration B. If calibration succeeds, those families become the core of a 36-task family-level holdout; the remaining 28 families form an 84-task development set. Thus no wording or sibling task from a held-out family is sent to a provider before sealing.

The automated leakage test checks every instruction against all exposed operation IDs, high-information schema parameter names, and meta phrases such as “call the tool” or “API.” It currently passes all 120 tasks.

Manual review also checked for overly literal description copying. The instructions use ordinary product language such as “end at renewal,” “return payment,” “account owner,” and “failed delivery.” They do not reproduce operation names or parameter labels. Resource identifiers such as `cus_`, `ord_`, and `inv_` are retained only where a realistic user already possesses a system reference; routing those identifiers is an intended benchmark behavior.

## Difficulty mechanisms

- Multi-step families require ordered 3–5 operation workflows, with later arguments determined from earlier results.
- Ambiguity families add duplicate plausible entities and require a targeted clarification term, not merely any question.
- Conditional execution requires inspection of invoice, shipment, or opportunity state before mutation.
- Error-recovery families distinguish replacement identifiers, one retry for a temporary error, and terminal invalid-state errors.
- Safety families include execute, clarify/confirm, and refuse outcomes with unchanged-state invariants.
- Post-success families impose justified tool-call limits and reject post-success clarification.
- Semantic argument expectations are separate from schema validity.

## Evaluator audit before calibration

The R2 evaluator adds ordered-sequence assertions, targeted-clarification checks, justified tool-call limits, and explicit recovery modes. Refusal normalization gives refusal language precedence over incidental questions. Unsupported-semantics tasks no longer require an invalid destructive call when explanation-and-stop is correct. Tests cover refusal wording, post-success clarification, targeted clarification, sequence errors, excess calls, fault replacement, temporary retry, and leakage.

No benchmark is frozen and no holdout manifest is generated until real-model calibration demonstrates adequate headroom.
