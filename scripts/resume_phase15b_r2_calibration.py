"""Resume only missing cells from a cost-gated Phase 1.5B R2 calibration."""

from __future__ import annotations

import argparse
import asyncio
import json
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
from agentseo.phase15b_r2_benchmark import R2_UNCALIBRATED_FAMILIES
from agentseo.research_export import export_experiment_dataset
from sqlalchemy import func, select


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


async def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_id")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        experiment = session.get(Experiment, args.experiment_id)
        if experiment is None:
            raise RuntimeError("Calibration experiment not found")
        task_ids = list(experiment.manifest.get("selected_task_ids", []))
        if task_ids:
            tasks = list(
                session.scalars(select(BenchmarkTask).where(BenchmarkTask.id.in_(task_ids)))
            )
        elif experiment.configuration.get("stage") == "CALIBRATION_B":
            tasks = list(
                session.scalars(
                    select(BenchmarkTask).where(
                        BenchmarkTask.task_family.not_in(R2_UNCALIBRATED_FAMILIES)
                    )
                )
            )
            task_ids = [task.id for task in tasks]
        else:
            raise RuntimeError("Interrupted experiment has no recoverable selected-task manifest")
        projects = list(session.scalars(select(Project).order_by(Project.sandbox_domain)))
        interfaces = list(
            session.scalars(
                select(InterfaceVersion).where(InterfaceVersion.variant_key == "baseline")
            )
        )
        by_project = {interface.project_id: interface for interface in interfaces}
        split_label = str(experiment.configuration["stage"]).lower()
        configuration = Phase15Configuration(
            models=experiment.models,
            variants=["baseline"],
            repetitions=1,
            split_seed=experiment.task_split_seed,
            temperature=float(experiment.configuration["temperature"]),
            max_cost_usd=min(settings.phase15_max_cost_usd, 5.0),
            max_concurrency=settings.phase15_max_concurrency,
            bootstrap_samples=settings.phase15_bootstrap_samples,
        )
        cells: list[ExperimentCell] = []
        for project in projects:
            project_tasks = [task for task in tasks if task.project_id == project.id]
            for model in experiment.models:
                provider, _, exact_model = model.partition(":")
                existing = session.scalar(
                    select(BenchmarkRun).where(
                        BenchmarkRun.experiment_id == experiment.id,
                        BenchmarkRun.project_id == project.id,
                        BenchmarkRun.provider == provider,
                        BenchmarkRun.model == exact_model,
                        BenchmarkRun.task_split == split_label,
                        BenchmarkRun.status == "COMPLETED",
                    )
                )
                if existing is None:
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
        print(
            json.dumps(
                {"event": "R2_CALIBRATION_RESUME", "missing_cells": [cell.label for cell in cells]}
            )
        )
        failures: list[str] = []
        experiment.status = ExperimentStatus.RUNNING.value
        session.commit()
        for cell in cells:
            cell_failures: list[str] = []
            for attempt in range(1, 4):
                cell_failures = await _execute_cells(
                    session, experiment, [cell], configuration, settings
                )
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
                print(
                    json.dumps(
                        {
                            "event": "CELL_RETRY",
                            "cell": cell.label,
                            "attempt": attempt,
                            "errors": cell_failures,
                        }
                    )
                )
            failures.extend(cell_failures)
        task_run_count = int(
            session.scalar(
                select(func.count(TaskRun.id)).where(TaskRun.experiment_id == experiment.id)
            )
            or 0
        )
        expected_runs = len(task_ids) * len(experiment.models)
        experiment.actual_cost = float(
            session.scalar(
                select(func.coalesce(func.sum(TaskRun.cost_estimate), 0)).where(
                    TaskRun.experiment_id == experiment.id
                )
            )
            or 0
        )
        experiment.completed_at = now()
        experiment.status = (
            ExperimentStatus.COMPLETED.value
            if not failures and task_run_count == expected_runs
            else ExperimentStatus.FAILED.value
        )
        experiment.notes = "\n".join(failures)
        summary = {
            **experiment.manifest,
            "protocol": experiment.configuration.get("protocol"),
            "stage": experiment.configuration.get("stage"),
            "experiment_id": experiment.id,
            "model_ids": experiment.models,
            "selected_task_ids": sorted(task_ids),
            "selected_task_families": sorted({task.task_family for task in tasks}),
            "uncalibrated_family_count": len(R2_UNCALIBRATED_FAMILIES),
            "status": experiment.status,
            "task_runs": task_run_count,
            "actual_cost_usd": experiment.actual_cost,
            "failed_cells": failures,
            "results": _summary_rows(session, experiment.id),
            "resumed": True,
        }
        experiment.manifest = summary
        session.commit()
        export_experiment_dataset(session, experiment, output_root / "data")
        analysis = analyze_experiment(
            session, experiment, bootstrap_samples=settings.phase15_bootstrap_samples
        )
        (output_root / "analysis.json").write_text(
            json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8"
        )
        (output_root / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
