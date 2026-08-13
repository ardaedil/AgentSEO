# AgentSEO Design-Partner Demo

This is a repeatable 10-minute walkthrough of the accepted Phase 2A product. The default path replays
the checked-in real-agent result and makes no provider calls. Use the optional live command only when
the audience asks to see a fresh provider run and the operator has approved the cost.

## Before the call

From the repository root, install the CLI and confirm the demo files are present:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e 'apps/backend[dev]'
pytest -q apps/backend/tests/test_compatibility.py::test_breaking_demo_remains_structurally_schema_compatible
```

The final command should pass. It proves that the baseline and breaking candidate retain identical
paths, methods, required fields, request schemas, and response schemas.

## 0:00-1:00 — Frame the problem

Say:

> AgentSEO is behavioral compatibility CI for agent-facing APIs and MCP servers. Normal API checks
> validate the wire contract; AgentSEO checks whether real agents still operate it reliably and safely.

Open these interfaces side by side:

```bash
git diff --no-index \
  examples/compatibility-ci-demo/baseline/openapi.yaml \
  examples/compatibility-ci-demo/candidate-breaking/openapi.yaml || true
```

Point out that the candidate is a plausible OpenAPI-only change: its agent-facing operation names and
descriptions changed, but its HTTP paths and schemas did not.

## 1:00-2:30 — Show the semantic interface diff

```bash
agentseo diff \
  --baseline examples/compatibility-ci-demo/baseline/openapi.yaml \
  --candidate examples/compatibility-ci-demo/candidate-breaking/openapi.yaml
```

Expected summary: 10 normalized semantic changes—four tool renames, four description changes, and
two parameter-description changes—with HIGH maximum risk. Emphasize that this is a normalized
OpenAPI semantic diff, not a textual Git diff.

## 2:30-4:00 — Explain and validate the behavioral contract

```bash
cat examples/design-partner-demo/sample-agentic-contract.yaml
```

The contract says what must happen, what must remain unchanged, what actions are forbidden, whether
clarification is allowed, and how many tool calls may be used. It is model-independent.

Optionally validate the paired pipeline without keys or cost:

```bash
agentseo compare \
  --baseline examples/compatibility-ci-demo/baseline/openapi.yaml \
  --candidate examples/compatibility-ci-demo/candidate-breaking/openapi.yaml \
  --tasks examples/compatibility-ci-demo/contracts \
  --models mock:reliable \
  --max-cost 0
```

Call this **keyless infrastructure validation**, not behavioral compatibility evidence.

## 4:00-6:00 — Replay the accepted real-agent result

```bash
cat examples/design-partner-demo/breaking-pr-report.md
```

Walk down the report in this order:

1. Protocol compatibility: PASS.
2. Schema compatibility: PASS.
3. Claude Sonnet 5 and Gemini 3.6 Flash each regress on the critical cancellation contract.
4. The trace-selected tools cross the changed refund/cancellation semantic boundary.
5. The deterministic evaluator records `HALLUCINATED_TOOL` and contract failure.
6. The policy fires `CRITICAL_CONTRACT_REGRESSION` and classifies the change `AGENT_BREAKING`.

The result emerged from real provider behavior. The evaluator checks the same required action,
forbidden actions, and final state for both interface versions; it does not contain a candidate-specific
failure.

## 6:00-7:00 — Explain the PR block

The compatibility command returns:

- exit 0 for PASS;
- exit 1 for FAIL, or for WARNING when `--fail-on-warning` is enabled;
- exit 2 for configuration or infrastructure failure.

The breaking example returns exit 1 because two critical paired contracts regressed. The composite
GitHub Action propagates that code to branch protection and upserts the Markdown report on the PR.

```bash
cat examples/design-partner-demo/sample-github-action.yml
```

## 7:00-8:00 — Show the safe comparison

```bash
cat examples/design-partner-demo/safe-pr-report.md
```

The safe candidate clarifies semantic boundaries and is materially better than the breaking change:
Claude and Gemini remain at 100%; GPT produces one unnecessary post-success clarification, so the
small one-trial demo honestly reports `AGENT_WARNING` rather than claiming a clean pass. Teams can
choose whether warnings block with `fail_on_warning`.

## 8:00-9:00 — Cost controls and reproducibility

Before execution, AgentSEO prints a guarded estimate and refuses to start if it exceeds `--max-cost`.
It also tracks actual tokens and estimated cost during the run. The accepted three-provider breaking
comparison had a guarded estimate of $0.0822 and a persisted actual estimate of $0.0430.

The report records exact model IDs, baseline and candidate interface hashes, task-suite hash, commits,
run ID, tokens, latency, and cost. Baseline metadata validation explicitly warns on model, task-suite,
or evaluator changes so incompatible runs are not compared silently.

## 9:00-10:00 — Ask for the prospect's workflow

Use `docs/DESIGN_PARTNER_QUESTIONS.md`. Start with how external agents use their API or MCP server,
then ask how interface changes are tested today and what evidence would justify blocking a release.

## Optional fresh real-provider run

Do this only with configured credentials, explicit cost approval, and no other paid demo process
running. The $0.25 command cap is fail-closed and above the current guarded estimate.

```bash
agentseo compare \
  --baseline examples/compatibility-ci-demo/baseline/openapi.yaml \
  --candidate examples/compatibility-ci-demo/candidate-breaking/openapi.yaml \
  --tasks examples/compatibility-ci-demo/contracts \
  --models openai:gpt-4.1-mini,anthropic:claude-sonnet-5,google:gemini-3.6-flash \
  --max-cost 0.25 \
  --fail-on-warning \
  --report agentseo-compatibility.md
```

An exit code of 1 is the expected product outcome when the breaking regression reproduces. Provider
behavior is stochastic, so use the accepted checked-in report as the stable demonstration artifact and
describe a fresh run as an additional observation, not a replacement for it. Never print or commit
provider credentials.

## Demo guardrails

- Do not present mock results as real-agent evidence.
- Do not claim that one two-contract run estimates general model quality.
- Do not claim automated optimization, model-specific compilation, or an industry standard.
- Do not edit the contract or interface after seeing a fresh run.
- Do not run paid providers when replaying the accepted result is sufficient.
