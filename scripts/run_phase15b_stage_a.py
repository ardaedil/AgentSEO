"""Run the cost-gated V0-only Phase 1.5B development baseline."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
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
from agentseo.reporting import generate_report
from agentseo.research_export import export_experiment_dataset
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _manifest_hash() -> str:
    manifest = json.loads(
        (ROOT / "artifacts" / "phase15b" / "holdout_manifest.json").read_text(encoding="utf-8")
    )
    expected = json.loads(
        (ROOT / "artifacts" / "phase15b" / "protocol_manifest.json").read_text(encoding="utf-8")
    )["holdout_manifest_sha256"]
    actual = _canonical_hash(manifest)
    if actual != expected:
        raise RuntimeError("Sealed holdout manifest hash mismatch")
    return actual


def _cell_run_query(cell: ExperimentCell, experiment_id: str) -> Any:
    provider, _, model = cell.model.partition(":")
    return select(BenchmarkRun).where(
        BenchmarkRun.experiment_id == experiment_id,
        BenchmarkRun.project_id == cell.project_id,
        BenchmarkRun.interface_version_id == cell.interface_id,
        BenchmarkRun.provider == provider,
        BenchmarkRun.model == model,
        BenchmarkRun.task_split == cell.split,
        BenchmarkRun.trial_number == cell.trial,
    )


async def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    models, unavailable = resolve_models(["openai", "anthropic", "google"], settings)
    expected_models = [
        "openai:gpt-4.1-mini",
        "anthropic:claude-sonnet-5",
        "google:gemini-3.6-flash",
    ]
    if unavailable or models != expected_models:
        raise RuntimeError(f"Frozen model configuration unavailable or changed: {models}")
    configuration = Phase15Configuration(
        models=models,
        variants=["baseline"],
        repetitions=2,
        split_seed=1502,
        temperature=0.0,
        max_cost_usd=min(settings.phase15_max_cost_usd, 5.0),
        max_concurrency=settings.phase15_max_concurrency,
        bootstrap_samples=settings.phase15_bootstrap_samples,
    )
    estimate = estimate_experiment_cost(80, configuration)
    print(json.dumps({"event": "PREFLIGHT", "estimate": estimate}, sort_keys=True))
    if float(estimate["guarded_estimate_usd"]) > configuration.max_cost_usd:
        raise RuntimeError("Stage A estimate exceeds PHASE15_MAX_COST_USD")
    holdout_hash = _manifest_hash()

    with SessionLocal() as session:
        projects = list(session.scalars(select(Project).order_by(Project.sandbox_domain)))
        tasks = list(session.scalars(select(BenchmarkTask)))
        development_tasks = [task for task in tasks if task.phase15_split == "development"]
        if len(projects) != 3 or len(tasks) != 120 or len(development_tasks) != 80:
            raise RuntimeError("Phase 1.5B database does not match the frozen 120/80/40 protocol")
        interfaces = list(
            session.scalars(
                select(InterfaceVersion).where(InterfaceVersion.variant_key == "baseline")
            )
        )
        by_project = {interface.project_id: interface for interface in interfaces}
        experiment = Experiment(
            project_id=projects[0].id,
            name="Phase 1.5B Stage A — fresh V0 development baseline",
            hypothesis=(
                "The expanded development benchmark reveals stable, model-specific interface "
                "failure profiles without consulting the sealed holdout."
            ),
            status=ExperimentStatus.RUNNING.value,
            task_split_seed=1502,
            configuration={
                "stage": "A",
                "variants": ["baseline"],
                "temperature": 0.0,
                "provider_seed": None,
                "max_concurrency": configuration.max_concurrency,
                "max_iterations": settings.max_iterations,
                "max_tool_calls": settings.max_tool_calls,
                "timeout_seconds": settings.run_timeout_seconds,
                "cost_cap_usd": configuration.max_cost_usd,
                "cost_estimate": estimate,
                "holdout_manifest_sha256": holdout_hash,
                "holdout_access": "sealed; no holdout tasks executed",
            },
            models=models,
            repetitions=2,
            estimated_cost=float(estimate["guarded_estimate_usd"]),
            started_at=now(),
            interface_versions=[interface.id for interface in interfaces],
        )
        session.add(experiment)
        session.commit()
        cells: list[ExperimentCell] = []
        for project in projects:
            selected = [task for task in development_tasks if task.project_id == project.id]
            interface = by_project[project.id]
            for model in models:
                for trial in (1, 2):
                    cells.append(
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

        failures: list[str] = []
        for index, cell in enumerate(cells, start=1):
            cell_failures: list[str] = []
            for attempt in range(1, 4):
                cell_failures = await _execute_cells(
                    session, experiment, [cell], configuration, settings
                )
                if not cell_failures:
                    break
                runs = list(session.scalars(_cell_run_query(cell, experiment.id)))
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
            actual_cost = float(
                session.scalar(
                    select(func.coalesce(func.sum(TaskRun.cost_estimate), 0)).where(
                        TaskRun.experiment_id == experiment.id
                    )
                )
                or 0
            )
            task_runs = int(
                session.scalar(
                    select(func.count(TaskRun.id)).where(TaskRun.experiment_id == experiment.id)
                )
                or 0
            )
            print(
                json.dumps(
                    {
                        "event": "PROGRESS",
                        "cells": f"{index}/{len(cells)}",
                        "task_runs": task_runs,
                        "expected_task_runs": 480,
                        "actual_cost_usd": round(actual_cost, 6),
                    }
                )
            )
            if actual_cost > configuration.max_cost_usd:
                failures.append("Actual cost cap exceeded; remaining cells were not launched")
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
        manifest = {
            "experiment_id": experiment.id,
            "stage": "A",
            "git_commit": _git_commit(),
            "model_ids": models,
            "request_configuration": experiment.configuration,
            "interface_ids": experiment.interface_versions,
            "development_task_ids": sorted(task.id for task in development_tasks),
            "development_task_versions": {task.id: task.version for task in development_tasks},
            "sealed_holdout_manifest_sha256": holdout_hash,
            "repetitions": 2,
            "task_runs": task_run_count,
            "actual_cost_usd": experiment.actual_cost,
            "failed_cells": failures,
        }
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
            "event": "STAGE_A_COMPLETE",
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
        print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
