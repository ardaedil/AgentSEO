# Compatibility CI demo

This demo isolates an agent-facing compatibility failure that ordinary schema compatibility misses.
The baseline, safe candidate, and breaking candidate expose the same four wire operations with the
same HTTP methods, paths, required fields, request schemas, and response schemas. The breaking
candidate changes only agent-facing operation identifiers, descriptions, and semantic boundaries
around cancellation, deletion, and refunds. Traditional wire/schema compatibility therefore passes.

The mutation is grounded in the real-model wrong-tool and destructive-action failures observed during
Phase 1.5 development. It is not hard-coded into an evaluator. Real agents still choose tools from the
candidate interface and deterministic final-state assertions decide whether behavior remains compatible.

```bash
agentseo diff \
  --baseline examples/compatibility-ci-demo/baseline/openapi.yaml \
  --candidate examples/compatibility-ci-demo/candidate-breaking/openapi.yaml

# Keyless infrastructure validation only; not compatibility evidence.
agentseo compare \
  --baseline examples/compatibility-ci-demo/baseline/openapi.yaml \
  --candidate examples/compatibility-ci-demo/candidate-safe/openapi.yaml \
  --tasks examples/compatibility-ci-demo/contracts \
  --models mock:reliable --max-cost 0

# Real behavioral compatibility check (uses provider keys from the environment).
agentseo compare \
  --baseline examples/compatibility-ci-demo/baseline/openapi.yaml \
  --candidate examples/compatibility-ci-demo/candidate-breaking/openapi.yaml \
  --tasks examples/compatibility-ci-demo/contracts \
  --models openai:gpt-4.1-mini,anthropic:claude-sonnet-5,google:gemini-3.6-flash \
  --max-cost 1.00 --fail-on-warning --report agentseo-compatibility.md
```

Mock output is labeled `MOCK VALIDATION` and must never be cited as real agent compatibility evidence.
The frozen sample run in `sample-real-report.md` detected a real Claude reliability regression while
all HTTP paths, methods, request schemas, and response schemas remained unchanged. Because this demo
suite has only two contracts, use `--fail-on-warning` to make that regression block CI.
