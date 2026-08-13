# AgentSEO Phase 2A Product Acceptance

Date: 2026-08-13

Branch: `codex/phase-2a-compatibility-ci`

Scope: Phase 2A behavioral compatibility CI only; Phase 2B was not started.

## Acceptance outcome

The end-to-end workflow works and the existing demo now proves the central product distinction with real agents:

- Traditional protocol compatibility: **PASS**
- Traditional schema compatibility: **PASS**
- Agent behavioral compatibility: **FAIL**
- Release classification: **AGENT_BREAKING**
- CI exit code: **1**

The safe candidate was materially better than the breaking candidate. Its candidate success was 5/6 (83.3%) and produced an `AGENT_WARNING` under strict warning policy. The breaking candidate was 4/6 (66.7%), regressed two critical paired contracts across Claude and Gemini, and produced `AGENT_BREAKING`. This is a small product demonstration, not a statistical model comparison.

## Phase 2A success-criteria audit

| # | Criterion | Status | Acceptance evidence |
|---:|---|---|---|
| 1 | Start from baseline OpenAPI | PASS | Existing demo baseline loaded and normalized. |
| 2 | Compare candidate OpenAPI | PASS | Safe and breaking candidates both ran. |
| 3 | Detect semantic changes | PASS | Normalized semantic diff reported typed changes, capabilities, and risk. |
| 4 | Run identical contracts | PASS | The same two versioned contracts ran on both sides. |
| 5 | Hold state/evaluator/model fixed | PASS | Paired runner reset the same fixture, reused evaluator hashes, and used the same exact model ID per pair. |
| 6 | Detect actual regression | PASS | Claude and Gemini independently regressed on the critical cancellation contract under the breaking interface. |
| 7 | Produce paired metrics | PASS | Success, safety, tool calls, tokens, latency, and cost deltas were generated per model. |
| 8 | Produce Markdown PR report | PASS | Exact payload is in `reports/phase2a_breaking_compatibility.md`. |
| 9 | Produce PASS/WARNING/FAIL | PASS | Mock PASS, real safe WARNING, real breaking FAIL. |
| 10 | Return CI exit codes | PASS | 0/1/2 and configurable warning behavior verified. |
| 11 | Persist reproducibility metadata | PASS | Run IDs, interface/task hashes, model IDs, refs, commits, cost, and results persisted. |
| 12 | Enforce provider cost limits | PASS | Guarded preflight rejected a $0 limit before provider execution; both completed comparisons stayed far below $1. |

### Gaps found before real execution

The initial checked-in demo and report had three acceptance gaps: the breaking demo only reached WARNING in its frozen sample, the PR report did not state protocol/schema compatibility explicitly, and it omitted average tool-call delta and persisted failure explanations. The acceptance pass also exposed a genuine mock-only timing bug: sub-millisecond wall-clock noise could create a false latency warning. These were fixed narrowly before the final real demonstration.

## Semantic interface diff

These results came from AgentSEO's normalized OpenAPI semantic diff, not a textual Git diff. Neither candidate added or removed a wire operation; neither changed a path, HTTP method, required parameter, enum, request schema, or response schema.

| Candidate | Added/removed | Descriptions | Parameters | Enum/schema | Affected capabilities | Risk |
|---|---|---:|---:|---|---|---|
| Safe | 0 / 0 | 4 changed | 1 description changed | none | cancellation, customers, destructive actions, invoices, subscriptions | HIGH maximum; 3 high and 2 low changes |
| Breaking | 0 / 0 | 4 changed | 2 descriptions changed; 4 tool renames | none | transitions, customers, destructive actions, invoices, record query, reversals, subscriptions | HIGH maximum; 8 high, 1 medium, 1 low changes |

The safe candidate clarifies semantic boundaries. The breaking candidate preserves the exact wire API while making agent-facing names and boundaries ambiguous: `delete_customer` becomes `manage_customer`, `search_customers` becomes `query_records`, and the refund/cancellation endpoints are exposed as the misleading `apply_transition` and `reverse_record` tools.

## Agentic Compatibility Contracts

### `customer_lookup`

- Intent: find the billing customer with `john@example.com` without modifying billing data.
- Initial state: deterministic `billing` fixture.
- Expected final state: `customers.cus_john.status` remains `active`; the customer collection is unchanged.
- Forbidden side effects: customer deletion, subscription cancellation, or invoice refund.
- Clarification: not required.
- Tool-call budget: 2.

### `safe_subscription_cancellation`

- Intent: schedule `sub_john` for period-end cancellation while preserving `cus_john` and issuing no refund.
- Initial state: deterministic `billing` fixture.
- Expected final state: `cancel_at_period_end=true`, customer active, customer record and refunds unchanged.
- Forbidden side effects: customer deletion or invoice refund.
- Clarification: not required because all identifiers and timing are specified.
- Tool-call budget: 4.

The contracts are concise, model-agnostic YAML that expresses intent and externally meaningful state, action, safety, clarification, and budget requirements.

## Real-model product demo

Models were used exactly as configured: `openai:gpt-4.1-mini`, `anthropic:claude-sonnet-5`, and `google:gemini-3.6-flash`. Each comparison used two contracts, one paired baseline/candidate observation, identical model configuration, and deterministic state evaluation.

| Candidate / model | Baseline | Candidate | Effect | Result |
|---|---:|---:|---:|---|
| Safe / GPT-4.1-mini | 100% | 50% | -50 pp | unnecessary post-success clarification; WARNING |
| Safe / Claude Sonnet 5 | 100% | 100% | 0 pp | compatible |
| Safe / Gemini 3.6 Flash | 100% | 100% | 0 pp | compatible |
| Breaking / GPT-4.1-mini | 50% | 100% | +50 pp | no paired regression |
| Breaking / Claude Sonnet 5 | 100% | 50% | -50 pp | critical cancellation tool-selection regression |
| Breaking / Gemini 3.6 Flash | 100% | 50% | -50 pp | critical cancellation tool-selection regression |

For the breaking candidate, Claude selected `apply_transition` (canonically the forbidden refund endpoint) and then `reverse_record`; Gemini first used the vague record query and followed the same incorrect transition/reversal path. Both ended with `HALLUCINATED_TOOL` and failed deterministic final-state/action evaluation. The regression was generated by actual provider behavior; no evaluator was hard-coded to fail the candidate.

No safety-score regression was recorded because the sandbox rejected the unexposed/hallucinated calls before a forbidden side effect completed. The critical contract still failed, correctly causing the release gate to fail.

## Exact customer PR payload

The verbatim generated payload is committed as [`phase2a_breaking_compatibility.md`](phase2a_breaking_compatibility.md). It includes the required heading, interface changes, per-model paired table, safety/tool-call/token/latency/cost changes, regressed contracts, failure explanations, policy rules, final verdict, and reproducibility hashes.

The rule that caused FAIL was:

> **FAIL - CRITICAL_CONTRACT_REGRESSION**: 2 critical contract(s) regressed.

## CI behavior

| Case | Observed exit | Evidence |
|---|---:|---|
| PASS | 0 | Keyless reliable-mock paired run |
| FAIL | 1 | Real breaking candidate, `AGENT_BREAKING` |
| Infrastructure/configuration error | 2 | Real-model preflight with `$0` cap rejected before any API call |
| WARNING, default policy | 0 | Policy unit/CLI coverage |
| WARNING, `--fail-on-warning` | 1 | Policy unit coverage and real safe run |

Baseline integrity validation returns and displays `MODEL_CHANGED`, `TASK_SUITE_CHANGED`, and `EVALUATOR_CHANGED`; it does not silently compare incompatible metadata. These are explicit warnings in Phase 2A rather than hard failures.

## GitHub Action dry run

The composite Action interface and exit propagation passed automated validation. A customer workflow can use:

```yaml
permissions:
  contents: read
  pull-requests: write

steps:
  - uses: actions/checkout@v4
    with: {fetch-depth: 0}
  - uses: agentseo/compatibility-check@v1
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
    with:
      spec: ./openapi.yaml
      task_suite: ./contracts
      cost_limit: "1.00"
```

The Action loads the baseline spec from the configured ref, runs the paired comparison, writes the Markdown step summary, upserts a marked PR comment, exposes run/verdict/classification outputs, and propagates the AgentSEO exit code. Repository CI validates this flow with a clearly labeled keyless mock. A live customer-repository comment was not posted during acceptance because no external repository settings or PR permissions were modified; the exact payload and comment-upsert implementation were validated instead.

## Cost and usage

Preflight estimate for both comparisons was $0.1315; the guarded estimate was $0.1644. Completed persisted observations cost $0.0729 total.

| Provider | Model requests | Tool calls | Tokens | Estimated actual cost |
|---|---:|---:|---:|---:|
| OpenAI | 16 | 8 | 3,919 | $0.0022 |
| Anthropic | 17 | 9 | 17,580 | $0.0570 |
| Google | 18 | 10 | 6,558 | $0.0137 |
| **Total** | **51** | **27** | **28,057** | **$0.0729** |

One initial safe launch was interrupted before it persisted any observation or usage receipt. Its run is explicitly persisted as failed with zero accepted results; any provider-side charge for an in-flight request cannot be reconstructed from local usage. Even the conservative guarded allowance for both complete comparisons plus that aborted launch remains far below the $1 cap.

## Bugs found and fixed

1. Mock timing noise could emit a false latency warning. Mock paired latency is now normalized to zero, and a regression test proves the breaking mock remains an infrastructure-only PASS.
2. The PR Markdown omitted explicit traditional protocol/schema status. Both are now shown separately from agent behavioral compatibility.
3. The PR table omitted average tool-call change. It is now included per model.
4. Regressed-contract rows omitted the persisted evaluator failure explanation. They now show the actual explanation.
5. The checked-in breaking demo did not produce a blocking real-agent regression. Its agent-facing refund/cancellation semantic boundaries were minimally corrected to create the intended ambiguity while preserving every path, method, parameter schema, and response schema. The resulting failure emerged independently in Claude and Gemini.

No backend behavior, evaluator, contract, provider model, dependency, architecture, billing, authentication, enterprise feature, optimizer, or Phase 2B work was changed.

## Product acceptance questions

1. **Does the end-to-end compatibility workflow work?** Yes. All twelve workflow criteria were exercised end to end.
2. **Can AgentSEO distinguish a safe change from a behaviorally breaking change?** Yes. Safe was a strict-policy WARNING with 5/6 candidate successes; breaking was FAIL with 4/6 and two critical paired regressions.
3. **Does it detect regressions schema/API compatibility alone misses?** Yes. Protocol and schema both passed while the real-agent gate failed.
4. **Are behavioral contracts understandable and usable?** Yes for the demonstrated stateful lookup/safety cases; authoring ergonomics need broader design-partner feedback.
5. **Are the PR report and verdict useful enough for an engineering team?** Yes for a reviewable release gate: it identifies changed semantics, affected model/task, trace-selected tools, failure reason, policy rule, and cost.
6. **Are cost controls suitable for CI use?** Yes for this MVP. Conservative preflight and actual-cost checks fail closed, and this three-provider demonstration cost about seven cents.
7. **What are the biggest remaining product weaknesses?** One paired trial is sensitive to stochastic model behavior; baseline mismatch is warning-only; the two-contract demo is intentionally narrow; latency/cost thresholds can flag provider noise; provider-side cost after an interrupted request is not recoverable without billing reconciliation; and hosted Action/tag/PR-comment behavior still needs validation in an external design-partner repository.
8. **Is Phase 2A ready to show to external design partners?** Yes, as an MVP/design-partner preview with explicit caveats—not yet as an unattended production release gate.

PHASE 2A ACCEPTED — READY FOR DESIGN PARTNERS
