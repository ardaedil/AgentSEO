"""Regenerate the checked-in benchmark manifest from executable task templates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agentseo.openapi_parser import parse_openapi
from agentseo.task_generation import generate_template_tasks

ROOT = Path(__file__).resolve().parents[1]
SPLIT_SEED = 42


def phase15_split(title: str, instruction: str) -> str:
    identity = f"{SPLIT_SEED}:{title}:{instruction}".encode()
    return (
        "development" if int(hashlib.sha256(identity).hexdigest()[:8], 16) % 100 < 70 else "hidden"
    )


def main() -> None:
    tasks = []
    operation_count = 0
    for domain in ("billing", "ecommerce", "crm"):
        _, tools = parse_openapi((ROOT / "examples" / domain / "openapi.yaml").read_bytes())
        operation_count += len(tools)
        for task in generate_template_tasks(tools, domain):
            tasks.append(
                {
                    "id": f"task_{len(tasks) + 1:03d}",
                    "domain": domain,
                    "title": task.title,
                    "natural_language_instruction": task.natural_language_instruction,
                    "difficulty": task.difficulty,
                    "category": task.category,
                    "required_tools": task.required_tools,
                    "forbidden_tools": task.forbidden_tools,
                    "expected_final_state": task.expected_final_state,
                    "expected_invariants": task.expected_invariants,
                    "requires_clarification": task.requires_clarification,
                    "safety_level": task.safety_level,
                    "phase15_split": phase15_split(task.title, task.natural_language_instruction),
                }
            )
    document = {
        "schema_version": "1.5",
        "description": (
            "Deterministic AgentSEO benchmark. Natural-language instructions do not reveal "
            "operation identifiers; required/forbidden tools are evaluator-only labels."
        ),
        "api_count": 3,
        "operation_count": operation_count,
        "task_count": len(tasks),
        "phase15_split_seed": SPLIT_SEED,
        "tasks": tasks,
    }
    (ROOT / "examples" / "benchmark_dataset.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
