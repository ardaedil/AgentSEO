"""Run staged V0-only calibration on the unsplit R2 hard benchmark."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from agentseo.config import get_settings
from agentseo.database import SessionLocal
from agentseo.experiments import (
    ExperimentCell,
    Phase15Configuration,
    _execute_cells,
    analyze_experiment,
    estimate_experiment_cost,
    resolve_models,
)
from agentseo.models import (
    BenchmarkRun,
    BenchmarkTask,
    Experiment,
    ExperimentStatus,
    InterfaceVersion,
    Project,
    TaskRun,
    now,
)
from agentseo.phase15b_r2_benchmark import (
    PHASE15B_R2_EVALUATOR_VERSION,
    PHASE15B_R2_PROTOCOL,
    PHASE15B_R2_SPLIT_SEED,
    R2_UNCALIBRATED_FAMILIES,
)
from agentseo.research_export import export_experiment_dataset
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MODELS = [
    "openai:gpt-4.1-mini",
    "anthropic:claude-sonnet-5",
    "google:gemini-3.6-flash",
]


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _hash_score(value: str) -> str:
    return hashlib.sha256(f"{PHASE15B_R2_SPLIT_SEED}:{value}".encode()).hexdigest()


def _calibration_a_tasks(tasks: list[BenchmarkTask]) -> list[BenchmarkTask]:
    by_family: dict[str, list[BenchmarkTask]] = defaultdict(list)
    for task in tasks:
        if task.task_family not in R2_UNCALIBRATED_FAMILIES:
            by_family[task.task_family].append(task)
    by_category: dict[str, list[str]] = defaultdict(list)
    for family, rows in by_family.items():
        by_category[rows[0].category].append(family)
    selected_families: list[str] = []
    for category in sorted(by_category):
        selected_families.extend(sorted(by_category[category], key=_hash_score)[:2])
    remaining = sorted(set(by_family) - set(selected_families), key=_hash_score)
    selected_families.extend(remaining[: 24 - len(selected_families)])
    selected = [sorted(by_family[family], key=lambda task: task.id)[0] for family in selected_families]
    if len(selected) != 24 or len({task.task_family for task in selected}) != 24:
        raise RuntimeError("Calibration A must select 24 distinct eligible task families")
    return selected


def _calibration_b_tasks(tasks: list[BenchmarkTask]) -> list[BenchmarkTask]:
    selected = [task for task in tasks if task.task_family not in R2_UNCALIBRATED_FAMILIES]
    if len(selected) != 84 or len({task.task_family for task in selected}) != 28:
        raise RuntimeError("Calibration B must contain 84 tasks from 28 development families")
    return selected


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
                category: sum(task_run.success for task_run, task in items if task.category == category)
                / sum(1 for _, task in items if task.category == category)
                for category in sorted({task.category for _, task in items})
            },
        }
        for model, items in sorted(grouped.items())
    ]


async def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("A", "B"), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    models, unavailable = resolve_models(["openai", "anthropic", "google"], settings)
    if unavailable or models != EXPECTED_MODELS:
        raise RuntimeError(f"R2 frozen model configuration unavailable or changed: {models}")

    with SessionLocal() as session:
        projects = list(session.scalars(select(Project).order_by(Project.sandbox_domain)))
        all_tasks = list(session.scalars(select(BenchmarkTask)))
        if len(projects) != 3 or len(all_tasks) != 120 or any(task.phase15_split for task in all_tasks):
            raise RuntimeError("R2 candidate database must contain 120 unsplit tasks")
        selected_tasks = _calibration_a_tasks(all_tasks) if args.stage == "A" else _calibration_b_tasks(all_tasks)
        configuration = Phase15Configuration(
            models=models,
            variants=["baseline"],
            repetitions=1,
            split_seed=PHASE15B_R2_SPLIT_SEED,
            temperature=0.0,
            max_cost_usd=min(settings.phase15_max_cost_usd, 5.0),
            max_concurrency=settings.phase15_max_concurrency,
            bootstrap_samples=settings.phase15_bootstrap_samples,
        )
        estimate = estimate_experiment_cost(len(selected_tasks), configuration)
        print(json.dumps({"event": f"R2_CALIBRATION_{args.stage}_PREFLIGHT", "estimate": estimate}, sort_keys=True))
        if float(estimate["guarded_estimate_usd"]) > configuration.max_cost_usd:
            raise RuntimeError("R2 calibration estimate exceeds PHASE15_MAX_COST_USD")
        interfaces = list(session.scalars(select(InterfaceVersion).where(InterfaceVersion.variant_key == "baseline")))
        by_project = {interface.project_id: interface for interface in interfaces}
        experiment = Experiment(
            project_id=projects[0].id,
            name=f"Phase 1.5B R2 Calibration {args.stage} — V0 hard benchmark",
            hypothesis="The R2 candidate pool provides measurable V0 headroom for all three models.",
            status=ExperimentStatus.RUNNING.value,
            task_split_seed=PHASE15B_R2_SPLIT_SEED,
            configuration={
                "protocol": PHASE15B_R2_PROTOCOL,
                "stage": f"CALIBRATION_{args.stage}",
                "evaluator_version": PHASE15B_R2_EVALUATOR_VERSION,
                "temperature": 0.0,
                "provider_seed": None,
                "max_iterations": settings.max_iterations,
                "max_tool_calls": settings.max_tool_calls,
                "timeout_seconds": settings.run_timeout_seconds,
                "cost_cap_usd": configuration.max_cost_usd,
                "cost_estimate": estimate,
                "final_holdout_status": "not created",
            },
            models=models,
            repetitions=1,
            estimated_cost=float(estimate["guarded_estimate_usd"]),
            started_at=now(),
            interface_versions=[interface.id for interface in interfaces],
        )
        session.add(experiment)
        session.commit()
        cells: list[ExperimentCell] = []
        split_label = f"calibration_{args.stage.lower()}"
        for project in projects:
            project_tasks = [task for task in selected_tasks if task.project_id == project.id]
            for model in models:
                cells.append(
                    ExperimentCell(
                        project_id=project.id,
                        interface_id=by_project[project.id].id,
                        model=model,
                        task_ids=[task.id for task in project_tasks],
                        split=split_label,
                        trial=1,
                        label=f"{project.sandbox_domain}/{model}/baseline/{split_label}/1",
                    )
                )
        failures: list[str] = []
        for index, cell in enumerate(cells, start=1):
            cell_failures: list[str] = []
            for attempt in range(1, 4):
                cell_failures = await _execute_cells(session, experiment, [cell], configuration, settings)
                if not cell_failures:
                    break
                for run in session.scalars(
                    select(BenchmarkRun).where(
                        BenchmarkRun.experiment_id == experiment.id,
                        BenchmarkRun.project_id == cell.project_id,
                        BenchmarkRun.model == cell.model.partition(":")[2],
                        BenchmarkRun.task_split == split_label,
                    )
                ):
                    if run.status != "COMPLETED":
                        session.delete(run)
                session.commit()
                print(json.dumps({"event": "CELL_RETRY", "cell": cell.label, "attempt": attempt, "errors": cell_failures}))
            failures.extend(cell_failures)
            actual_cost = float(session.scalar(select(func.coalesce(func.sum(TaskRun.cost_estimate), 0)).where(TaskRun.experiment_id == experiment.id)) or 0)
            print(json.dumps({"event": "PROGRESS", "cells": f"{index}/{len(cells)}", "actual_cost_usd": round(actual_cost, 6)}))
            if actual_cost > configuration.max_cost_usd:
                failures.append("Actual cost cap exceeded; remaining cells were not launched")
                break
        task_run_count = int(session.scalar(select(func.count(TaskRun.id)).where(TaskRun.experiment_id == experiment.id)) or 0)
        expected_runs = len(selected_tasks) * len(models)
        experiment.actual_cost = float(session.scalar(select(func.coalesce(func.sum(TaskRun.cost_estimate), 0)).where(TaskRun.experiment_id == experiment.id)) or 0)
        experiment.completed_at = now()
        experiment.status = ExperimentStatus.COMPLETED.value if not failures and task_run_count == expected_runs else ExperimentStatus.FAILED.value
        experiment.notes = "\n".join(failures)
        summary = {
            "protocol": PHASE15B_R2_PROTOCOL,
            "stage": f"CALIBRATION_{args.stage}",
            "experiment_id": experiment.id,
            "git_commit": _git_commit(),
            "status": experiment.status,
            "model_ids": models,
            "selected_task_ids": sorted(task.id for task in selected_tasks),
            "selected_task_families": sorted({task.task_family for task in selected_tasks}),
            "uncalibrated_family_count": len(R2_UNCALIBRATED_FAMILIES),
            "task_runs": task_run_count,
            "actual_cost_usd": experiment.actual_cost,
            "failed_cells": failures,
            "results": _summary_rows(session, experiment.id),
        }
        experiment.manifest = summary
        session.commit()
        export_experiment_dataset(session, experiment, output_root / "data")
        analysis = analyze_experiment(session, experiment, bootstrap_samples=settings.phase15_bootstrap_samples)
        (output_root / "analysis.json").write_text(json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8")
        (output_root / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
