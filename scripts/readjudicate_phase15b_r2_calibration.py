"""Re-adjudicate stored R2 terminal refusals after normalization fixes.

This script never calls a provider and never edits trace events. It only recomputes the
deterministic terminal-behavior fields for explicit refusal text already persisted in a
completed calibration.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from agentseo.config import get_settings
from agentseo.database import SessionLocal
from agentseo.experiments import analyze_experiment
from agentseo.models import BenchmarkTask, Experiment, TaskRun, TraceEvent
from agentseo.providers import text_is_refusal
from agentseo.research_export import export_experiment_dataset
from sqlalchemy import select


def _summary_rows(session: Any, experiment_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(TaskRun, BenchmarkTask)
        .join(BenchmarkTask, TaskRun.task_id == BenchmarkTask.id)
        .where(TaskRun.experiment_id == experiment_id)
    ).all()
    grouped: dict[str, list[tuple[TaskRun, BenchmarkTask]]] = defaultdict(list)
    for task_run, task in rows:
        grouped[task_run.model_identifier].append((task_run, task))
    return [
        {
            "model": model,
            "tasks": len(items),
            "successes": sum(task_run.success for task_run, _ in items),
            "success_rate": sum(task_run.success for task_run, _ in items) / len(items),
            "cost_usd": sum(task_run.cost_estimate for task_run, _ in items),
            "average_tokens": sum(
                int((task_run.token_usage or {}).get("input", 0))
                + int((task_run.token_usage or {}).get("output", 0))
                for task_run, _ in items
            )
            / len(items),
            "category_success": {
                category: sum(
                    task_run.success for task_run, task in items if task.category == category
                )
                / sum(1 for _, task in items if task.category == category)
                for category in sorted({task.category for _, task in items})
            },
        }
        for model, items in sorted(grouped.items())
    ]


def _recomputed_passed(result: dict[str, Any]) -> bool:
    checks = (
        all(item.get("passed", False) for item in result.get("assertions", [])),
        result.get("clarification_passed", True),
        result.get("tool_requirements_passed", True),
        result.get("forbidden_tools_avoided", True),
        result.get("behavior_passed", True),
        result.get("required_tool_sequence_passed", True),
        result.get("targeted_clarification_passed", True),
        result.get("tool_call_limit_passed", True),
        result.get("semantic_arguments_correct", True),
        result.get("error_recovery_passed", True),
    )
    return all(bool(check) for check in checks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_id")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    settings = get_settings()

    changed: list[dict[str, str]] = []
    with SessionLocal() as session:
        experiment = session.get(Experiment, args.experiment_id)
        if experiment is None:
            raise RuntimeError("Calibration experiment not found")
        for task_run, task in session.execute(
            select(TaskRun, BenchmarkTask)
            .join(BenchmarkTask, TaskRun.task_id == BenchmarkTask.id)
            .where(TaskRun.experiment_id == experiment.id)
        ):
            result = dict(task_run.evaluator_result or {})
            if result.get("behavior_expected") != "refuse" or result.get("behavior_passed"):
                continue
            terminal = session.scalar(
                select(TraceEvent)
                .where(
                    TraceEvent.task_run_id == task_run.id,
                    TraceEvent.event_type.in_(("CLARIFICATION", "FINAL_RESPONSE")),
                )
                .order_by(TraceEvent.sequence.desc())
                .limit(1)
            )
            content = str((terminal.payload if terminal else {}).get("content", ""))
            if not text_is_refusal(content):
                continue
            result.update(
                {
                    "behavior_observed": "refuse",
                    "behavior_passed": True,
                    "clarification_observed": False,
                    "clarification_passed": not task.requires_clarification,
                    "terminal_readjudicated": True,
                    "terminal_readjudication_reason": "explicit refusal normalization",
                }
            )
            result["passed"] = _recomputed_passed(result)
            if not result["passed"]:
                raise RuntimeError(f"Refusal re-adjudication did not pass task {task_run.task_id}")
            task_run.evaluator_result = result
            task_run.success = True
            task_run.failure_category = None
            task_run.failure_explanation = None
            changed.append(
                {
                    "task_run_id": task_run.id,
                    "model": task_run.model_identifier,
                    "task_family": task.task_family,
                    "source_event_type": terminal.event_type if terminal else "",
                }
            )

        adjudicated: list[dict[str, str]] = []
        for task_run, task in session.execute(
            select(TaskRun, BenchmarkTask)
            .join(BenchmarkTask, TaskRun.task_id == BenchmarkTask.id)
            .where(TaskRun.experiment_id == experiment.id)
        ):
            if not (task_run.evaluator_result or {}).get("terminal_readjudicated"):
                continue
            terminal = session.scalar(
                select(TraceEvent)
                .where(
                    TraceEvent.task_run_id == task_run.id,
                    TraceEvent.event_type.in_(("CLARIFICATION", "FINAL_RESPONSE")),
                )
                .order_by(TraceEvent.sequence.desc())
                .limit(1)
            )
            adjudicated.append(
                {
                    "task_run_id": task_run.id,
                    "model": task_run.model_identifier,
                    "task_family": task.task_family,
                    "source_event_type": terminal.event_type if terminal else "",
                }
            )

        manifest = dict(experiment.manifest or {})
        manifest["results"] = _summary_rows(session, experiment.id)
        manifest["terminal_readjudication"] = {
            "provider_calls": 0,
            "changed_observations": len(adjudicated),
            "rule": "explicit refusal normalization",
            "trace_events_modified": False,
        }
        experiment.manifest = manifest
        session.commit()
        export_experiment_dataset(session, experiment, output_root / "data")
        analysis = analyze_experiment(
            session, experiment, bootstrap_samples=settings.phase15_bootstrap_samples
        )
        (output_root / "analysis.json").write_text(
            json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8"
        )
        (output_root / "summary.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        (output_root / "terminal_readjudication.json").write_text(
            json.dumps({"changes": adjudicated}, indent=2, sort_keys=True), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "newly_changed_observations": len(changed),
                "total_readjudicated_observations": len(adjudicated),
                "results": manifest["results"],
            }
        )
    )


if __name__ == "__main__":
    main()
