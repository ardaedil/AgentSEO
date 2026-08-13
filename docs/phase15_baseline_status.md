# Phase 1 baseline status

Recorded before Phase 1.5 source changes on branch `codex/phase-1-5-validation`.

| Check | Baseline result |
|---|---|
| Backend tests | 22 passed; one upstream Starlette/httpx deprecation warning |
| Strict mypy | Passed across 14 source files |
| Frontend typecheck | Passed |
| Frontend ESLint | Passed |
| Frontend production build | Passed |
| Ruff lint | Two pre-existing import-order findings in Alembic files |
| Ruff format | Two pre-existing Alembic formatting findings |

The Alembic-only Ruff findings were repaired while adding revision 0002. No Phase 1 behavioral failure was present.

## Architecture observed

- SQLAlchemy models represented projects, OpenAPI specs, canonical tools, interface snapshots, benchmark tasks/runs, task runs, and trace events.
- The runner reset a domain sandbox per task, bounded execution, stored traces, applied deterministic assertions, classified failures, and aggregated metrics.
- Provider adapters existed for OpenAI, Anthropic, Gemini, and a synthetic MockAgent.
- The three sandboxes covered billing, ecommerce, and CRM.
- The checked-in manifest claimed 53 tasks, while executable templates generated 51 and many generic instructions directly named the required operation.

