# Behavioral Compatibility CI

AgentSEO tests whether real agents can still operate an API after its agent-facing interface changes.
It loads the baseline specification from the target branch, the candidate from the pull request, runs
the same contracts/model/provider settings against resettable sandboxes, and compares deterministic
outcomes. Backend behavior, initial state, evaluator, task, and model are invariant within a pair.

## Commands

```bash
agentseo diff --baseline openapi-main.yaml --candidate openapi-pr.yaml
agentseo compare --baseline openapi-main.yaml --candidate openapi-pr.yaml \
  --tasks contracts --models openai:gpt-4.1-mini --max-cost 1.00 \
  --report compatibility.md
agentseo compatibility-report RUN_ID
```

Use `--save-baseline baseline.json` to persist the candidate fingerprint and metrics as an artifact.
On a later run, `--baseline-metadata baseline.json` checks model, task-suite, and evaluator hashes and
emits `MODEL_CHANGED`, `TASK_SUITE_CHANGED`, or `EVALUATOR_CHANGED` warnings instead of silently
comparing incompatible evidence. Every `CompatibilityRun` also provides the database baseline.

Exact single-provider commands for the demo are:

```bash
agentseo compare --baseline examples/compatibility-ci-demo/baseline/openapi.yaml --candidate examples/compatibility-ci-demo/candidate-breaking/openapi.yaml --tasks examples/compatibility-ci-demo/contracts --models openai:gpt-4.1-mini --max-cost 1.00 --fail-on-warning
agentseo compare --baseline examples/compatibility-ci-demo/baseline/openapi.yaml --candidate examples/compatibility-ci-demo/candidate-breaking/openapi.yaml --tasks examples/compatibility-ci-demo/contracts --models anthropic:claude-sonnet-5 --max-cost 1.00 --fail-on-warning
agentseo compare --baseline examples/compatibility-ci-demo/baseline/openapi.yaml --candidate examples/compatibility-ci-demo/candidate-breaking/openapi.yaml --tasks examples/compatibility-ci-demo/contracts --models google:gemini-3.6-flash --max-cost 1.00 --fail-on-warning
```

Exit codes are `0` for PASS (and WARNING by default), `1` for FAIL or configured warning failure,
and `2` for configuration/infrastructure failure. `FULL_SUITE` is the default selection strategy.
`AFFECTED_ONLY` intersects contract tools/capabilities with semantic diff impact and remains
experimental—not statistically validated.

## Isolation and reproducibility

Every pair records commits, interface hashes, task-suite and contract hashes, exact model IDs,
provider configuration, software/Python version, trial configuration, timestamps, traces, cost, and
the normalized semantic diff. Each task constructs and resets its own sandbox. Filesystem baselines
and database runs retain their configuration fingerprints; `MODEL_CHANGED`, `TASK_SUITE_CHANGED`,
and `EVALUATOR_CHANGED` are surfaced rather than silently compared.

MockAgent validates plumbing only and is labeled `MOCK VALIDATION`. Only configured provider runs
are labeled `REAL AGENT COMPATIBILITY`.
