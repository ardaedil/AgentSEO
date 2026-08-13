"""Resume an interrupted Phase 1.5 experiment without repeating completed cells."""

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
    _write_manifest,
    analyze_experiment,
    create_manifest,
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
from sqlalchemy import select


def cell_key(run: BenchmarkRun) -> tuple[str, str | None, str, str | None, int]:
    return (
        run.project_id,
        run.interface_version_id,
        f"{run.provider}:{run.model}",
        run.task_split,
        run.trial_number,
    )


async def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_id")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    configured_models, unavailable = resolve_models(["openai", "anthropic", "google"], settings)

    with SessionLocal() as session:
        experiment = session.get(Experiment, args.experiment_id)
        if experiment is None:
            raise RuntimeError(f"Experiment not found: {args.experiment_id}")
        if unavailable or experiment.models != configured_models:
            raise RuntimeError(
                "Configured providers do not exactly match the frozen experiment models: "
                f"configured={configured_models}, frozen={experiment.models}, unavailable={unavailable}"
            )
        configuration = Phase15Configuration(
            models=experiment.models,
            variants=list(experiment.configuration["variants"]),
            repetitions=experiment.repetitions,
            split_seed=experiment.task_split_seed,
            temperature=float(experiment.configuration["temperature"]),
            max_cost_usd=settings.phase15_max_cost_usd,
            max_concurrency=int(experiment.configuration["max_concurrency"]),
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
                select(Project).where(Project.id.in_({item.project_id for item in interfaces}))
            )
        )
        tasks = list(
            session.scalars(
                select(BenchmarkTask).where(
                    BenchmarkTask.project_id.in_([project.id for project in projects]),
                    BenchmarkTask.enabled.is_(True),
                )
            )
        )
        completed = {
            cell_key(run)
            for run in session.scalars(
                select(BenchmarkRun).where(
                    BenchmarkRun.experiment_id == experiment.id,
                    BenchmarkRun.status == "COMPLETED",
                )
            )
        }
        interrupted = list(
            session.scalars(
                select(BenchmarkRun).where(
                    BenchmarkRun.experiment_id == experiment.id,
                    BenchmarkRun.status != "COMPLETED",
                )
            )
        )
        interrupted_task_runs = sum(len(run.task_runs) for run in interrupted)
        for run in interrupted:
            session.delete(run)
        session.commit()

        by_project = {
            project.id: {
                interface.variant_key: interface
                for interface in interfaces
                if interface.project_id == project.id
            }
            for project in projects
        }
        expected: list[ExperimentCell] = []
        for split_name in ("development", "hidden"):
            for project in projects:
                selected = [
                    task
                    for task in tasks
                    if task.project_id == project.id and task.phase15_split == split_name
                ]
                if not selected:
                    continue
                for variant in configuration.variants:
                    interface = by_project[project.id][variant]
                    for model in configuration.models:
                        for trial in range(1, configuration.repetitions + 1):
                            expected.append(
                                ExperimentCell(
                                    project_id=project.id,
                                    interface_id=interface.id,
                                    model=model,
                                    task_ids=[task.id for task in selected],
                                    split=split_name,
                                    trial=trial,
                                    label=(
                                        f"{project.sandbox_domain}/{model}/{variant}/"
                                        f"{split_name}/{trial}"
                                    ),
                                )
                            )
        remaining = [
            cell
            for cell in expected
            if (cell.project_id, cell.interface_id, cell.model, cell.split, cell.trial)
            not in completed
        ]
        print(
            json.dumps(
                {
                    "experiment_id": experiment.id,
                    "completed_cells_preserved": len(completed),
                    "interrupted_cells_removed": len(interrupted),
                    "partial_task_runs_removed": interrupted_task_runs,
                    "remaining_cells": len(remaining),
                    "frozen_models": experiment.models,
                    "frozen_variants": configuration.variants,
                    "frozen_tasks": len(tasks),
                    "repetitions": configuration.repetitions,
                },
                indent=2,
            )
        )
        failures = await _execute_cells(session, experiment, remaining, configuration, settings)
        task_run_count = len(
            list(session.scalars(select(TaskRun.id).where(TaskRun.experiment_id == experiment.id)))
        )
        expected_task_runs = (
            len(tasks)
            * len(configuration.variants)
            * len(configuration.models)
            * configuration.repetitions
        )
        experiment.actual_cost = sum(
            session.scalars(
                select(TaskRun.cost_estimate).where(TaskRun.experiment_id == experiment.id)
            )
        )
        experiment.completed_at = now()
        experiment.status = (
            ExperimentStatus.COMPLETED.value
            if not failures and task_run_count == expected_task_runs
            else ExperimentStatus.FAILED.value
        )
        experiment.notes = "\n".join(failures)
        manifest = create_manifest(experiment, tasks, interfaces)
        manifest["completed_at"] = experiment.completed_at.isoformat()
        manifest["actual_cost_usd"] = experiment.actual_cost
        manifest["failed_cells"] = failures
        manifest["resumed_after_interruption"] = True
        manifest["completed_cells_preserved"] = len(completed)
        manifest["interrupted_cells_restarted"] = len(interrupted)
        experiment.manifest = manifest
        session.commit()
        _write_manifest(manifest, args.output_root / "data" / "experiment_manifest.json")
        analysis = analyze_experiment(
            session, experiment, bootstrap_samples=settings.phase15_bootstrap_samples
        )
        export_experiment_dataset(session, experiment, args.output_root / "data")
        generate_report(experiment, analysis, args.output_root / "report")
        print(
            json.dumps(
                {
                    "status": experiment.status,
                    "task_runs": task_run_count,
                    "expected_task_runs": expected_task_runs,
                    "actual_cost": experiment.actual_cost,
                    "failed_cells": failures,
                    "analysis": analysis,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
