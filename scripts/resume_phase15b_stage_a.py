"""Resume the frozen Phase 1.5B Stage A matrix without repeating completed cells."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from agentseo.config import get_settings
from agentseo.database import SessionLocal
from agentseo.experiments import (
    ExperimentCell,
    Phase15Configuration,
    _execute_cells,
    analyze_experiment,
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
from agentseo.reporting import generate_report
from agentseo.research_export import export_experiment_dataset
from sqlalchemy import func, select


def cell_key(run: BenchmarkRun) -> tuple[str, str | None, str, int]:
    return (
        run.project_id,
        run.interface_version_id,
        f"{run.provider}:{run.model}",
        run.trial_number,
    )


async def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_id")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    models, unavailable = resolve_models(["openai", "anthropic", "google"], settings)
    if unavailable:
        raise RuntimeError(f"Frozen providers unavailable: {unavailable}")

    with SessionLocal() as session:
        experiment = session.get(Experiment, args.experiment_id)
        if experiment is None:
            raise RuntimeError(f"Experiment not found: {args.experiment_id}")
        if experiment.models != models:
            raise RuntimeError(f"Model mismatch: frozen={experiment.models}, configured={models}")
        configuration = Phase15Configuration(
            models=models,
            variants=["baseline"],
            repetitions=2,
            split_seed=experiment.task_split_seed,
            temperature=float(experiment.configuration["temperature"]),
            max_cost_usd=min(settings.phase15_max_cost_usd, 5.0),
            max_concurrency=settings.phase15_max_concurrency,
            bootstrap_samples=settings.phase15_bootstrap_samples,
        )
        interfaces = list(
            session.scalars(
                select(InterfaceVersion).where(
                    InterfaceVersion.id.in_(experiment.interface_versions)
                )
            )
        )
        projects = list(
            session.scalars(
                select(Project)
                .where(Project.id.in_({item.project_id for item in interfaces}))
                .order_by(Project.sandbox_domain)
            )
        )
        development_tasks = list(
            session.scalars(
                select(BenchmarkTask).where(BenchmarkTask.phase15_split == "development")
            )
        )
        interrupted = list(
            session.scalars(
                select(BenchmarkRun).where(
                    BenchmarkRun.experiment_id == experiment.id,
                    BenchmarkRun.status != "COMPLETED",
                )
            )
        )
        for run in interrupted:
            session.delete(run)
        session.commit()
        completed = {
            cell_key(run)
            for run in session.scalars(
                select(BenchmarkRun).where(
                    BenchmarkRun.experiment_id == experiment.id,
                    BenchmarkRun.status == "COMPLETED",
                )
            )
        }
        by_project = {item.project_id: item for item in interfaces}
        expected: list[ExperimentCell] = []
        for project in projects:
            selected = [task for task in development_tasks if task.project_id == project.id]
            interface = by_project[project.id]
            for model in models:
                for trial in (1, 2):
                    expected.append(
                        ExperimentCell(
                            project_id=project.id,
                            interface_id=interface.id,
                            model=model,
                            task_ids=[task.id for task in selected],
                            split="development",
                            trial=trial,
                            label=f"{project.sandbox_domain}/{model}/baseline/development/{trial}",
                        )
                    )
        remaining = [
            cell
            for cell in expected
            if (cell.project_id, cell.interface_id, cell.model, cell.trial) not in completed
        ]
        print(
            json.dumps(
                {
                    "event": "RESUME",
                    "completed_cells_preserved": len(completed),
                    "interrupted_cells_removed": len(interrupted),
                    "remaining_cells": len(remaining),
                }
            )
        )
        failures: list[str] = []
        for index, cell in enumerate(remaining, start=1):
            cell_failures: list[str] = []
            for attempt in range(1, 4):
                cell_failures = await _execute_cells(
                    session, experiment, [cell], configuration, settings
                )
                if not cell_failures:
                    break
                runs = list(
                    session.scalars(
                        select(BenchmarkRun).where(
                            BenchmarkRun.experiment_id == experiment.id,
                            BenchmarkRun.project_id == cell.project_id,
                            BenchmarkRun.interface_version_id == cell.interface_id,
                            BenchmarkRun.provider == cell.model.partition(":")[0],
                            BenchmarkRun.model == cell.model.partition(":")[2],
                            BenchmarkRun.trial_number == cell.trial,
                        )
                    )
                )
                for run in runs:
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
                await asyncio.sleep(0)
            failures.extend(cell_failures)
            task_runs = int(
                session.scalar(
                    select(func.count(TaskRun.id)).where(TaskRun.experiment_id == experiment.id)
                )
                or 0
            )
            cost = float(
                session.scalar(
                    select(func.coalesce(func.sum(TaskRun.cost_estimate), 0)).where(
                        TaskRun.experiment_id == experiment.id
                    )
                )
                or 0
            )
            print(
                json.dumps(
                    {
                        "event": "PROGRESS",
                        "remaining_cells": f"{index}/{len(remaining)}",
                        "task_runs": task_runs,
                        "expected_task_runs": 480,
                        "actual_cost_usd": round(cost, 6),
                    }
                )
            )
            if cost > configuration.max_cost_usd:
                failures.append("Actual cost cap exceeded; remaining cells not launched")
                break

        task_run_count = int(
            session.scalar(
                select(func.count(TaskRun.id)).where(TaskRun.experiment_id == experiment.id)
            )
            or 0
        )
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
            if not failures and task_run_count == 480
            else ExperimentStatus.FAILED.value
        )
        experiment.notes = "\n".join(failures)
        manifest = dict(experiment.manifest or {})
        manifest.update(
            {
                "resumed": True,
                "completed_cells_preserved": len(completed),
                "interrupted_cells_removed": len(interrupted),
                "task_runs": task_run_count,
                "actual_cost_usd": experiment.actual_cost,
                "failed_cells": failures,
                "completed_at": experiment.completed_at.isoformat(),
            }
        )
        experiment.manifest = manifest
        session.commit()
        (output_root / "experiment_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        analysis = analyze_experiment(
            session, experiment, bootstrap_samples=settings.phase15_bootstrap_samples
        )
        export_experiment_dataset(session, experiment, output_root / "data")
        generate_report(experiment, analysis, output_root / "report")
        summary = {
            "event": "STAGE_A_RESUME_COMPLETE",
            "experiment_id": experiment.id,
            "status": experiment.status,
            "task_runs": task_run_count,
            "actual_cost_usd": experiment.actual_cost,
            "failed_cells": failures,
            "holdout_task_runs": int(
                session.scalar(
                    select(func.count(TaskRun.id)).where(
                        TaskRun.experiment_id == experiment.id,
                        TaskRun.task_split == "holdout",
                    )
                )
                or 0
            ),
        }
        (output_root / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(summary))


if __name__ == "__main__":
    asyncio.run(main())
