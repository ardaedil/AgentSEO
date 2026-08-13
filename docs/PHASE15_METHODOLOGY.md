# Phase 1.5 experimental methodology

## Objective

Phase 1.5 attempts to falsify the claim that agent-facing API interface design materially changes reliable tool use. It does not implement autonomous search, optimization, deployment, or model-specific runtime compilation.

The controlled invariant is:

```text
same sandbox implementation
same initial state
same benchmark task and task version
same deterministic evaluator
same model configuration
only the agent-facing interface changes
```

Mutated names and parameter names are translated to canonical operations immediately before sandbox execution. Trace events retain both representations.

## Research questions

- RQ1: Does interface-only variation change paired task success?
- RQ2: Does deliberate degradation reduce reliability?
- RQ3: Does manually designed V2 recover or exceed V0?
- RQ4: Do GPT, Claude, and Gemini respond differently?
- RQ5: Are variant preferences model-specific?
- RQ6: Which mutations move wrong-tool, argument, sequencing, recovery, clarification, and safety failures?

## Task protocol

The executable benchmark contains 53 tasks across billing, ecommerce, and CRM. A SHA-256 assignment over the split seed, title, and instruction permanently assigns each task to development (70%) or hidden evaluation (30%). The default seed is 42.

V0 development runs execute before V2 exists. Development failure counts are stored on the experiment. V2 is then frozen; only after that does the runner execute any hidden cells. Hidden outcomes therefore cannot influence V2 construction.

Natural-language instructions contain no literal operation identifiers. Evaluator-only `required_tools` and `forbidden_tools` are never exposed to real provider prompts. MockAgent receives them only for system validation and is excluded from research conclusions.

## Variants

- V0 `baseline`: canonical imported interface.
- V1 `degraded`: opaque names, overlapping reduced descriptions, weak parameter names, and removed examples.
- V2 `optimized`: explicit intended use, semantic boundaries, required input guidance, and safety constraints.
- V3 `concise`: short, explicit intended-use statements.
- V4 `verbose`: richer guidance, constraints, and clarification advice.
- V5 `negative`: especially strong “do not use” boundaries.
- V6 `examples`: structured argument examples.
- V7 `reduced`: task-routed exposure, analyzed separately because routing uses benchmark-known tool groups.
- D1–D4: isolated rename, description reduction, parameter rename, and negative-instruction removal.
- T10/T25/T50: exposure expansion with clearly marked, read-only, sandbox-backed experimental context operations.

## Repetition and provider controls

The main matrix defaults to three repetitions per task × model × interface. Exact model identifiers, temperature, provider seed when applicable, timestamps, task versions, git commit, and interface IDs are recorded in the manifest. Providers with missing API keys are skipped and named in the report. No model alias is silently substituted.

## Cost safety

Before execution, the CLI displays tasks, models, variants, repetitions, expected calls, and an estimated cost with a 25% safety buffer. `PHASE15_MAX_COST_USD` blocks the matrix before any provider call when exceeded. `PHASE15_MAX_CONCURRENCY`, `PHASE15_REPETITIONS`, token assumptions, and temperatures are configuration inputs. Recorded token use is exported per observation; monetary values are estimates unless a provider exposes authoritative billing data.

## Metrics and inference

The study reports task success, tool selection, argument accuracy, multi-step completion, error recovery, clarification accuracy, destructive-action safety, tool calls, latency, token usage, and estimated cost.

Paired interface effects are computed within task. Repetitions stay inside task clusters. A seeded task-cluster bootstrap produces a 95% interval for the absolute success difference. Exact McNemar tests operate on task-majority outcomes, not on repeated trials as if independent. Relative differences, sample sizes, regression counts, and exploratory p-values are retained. Multiple comparisons are not confirmatory and are not presented as proof.

`MODEL_SPECIFIC_INTERFACE_EFFECT` is flagged when at least two real model families have a ten-percentage-point or larger spread in lift for the same variant and split.

## Decision rule

A strong GO requires at least a ten-point degradation effect, at least a five-point optimized hidden lift, more than one domain, repeatability, and interpretable failure mechanisms. Partial/category-specific evidence yields CONDITIONAL GO. Missing real-provider evidence, negligible effects, hidden-set collapse, or unreliable evaluation yields DO NOT PROCEED YET.

