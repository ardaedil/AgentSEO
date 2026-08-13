from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .interfaces import interface_features
from .models import (
    BenchmarkRun,
    BenchmarkTask,
    Experiment,
    InterfaceMutation,
    InterfaceVersion,
    Project,
    TaskRun,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def experiment_observations(session: Session, experiment: Experiment) -> list[dict[str, Any]]:
    rows = session.execute(
        select(TaskRun, BenchmarkRun, BenchmarkTask, InterfaceVersion, Project)
        .join(BenchmarkRun, TaskRun.benchmark_run_id == BenchmarkRun.id)
        .join(BenchmarkTask, TaskRun.task_id == BenchmarkTask.id)
        .join(InterfaceVersion, TaskRun.interface_version_id == InterfaceVersion.id)
        .join(Project, BenchmarkRun.project_id == Project.id)
        .where(TaskRun.experiment_id == experiment.id)
        .options(selectinload(TaskRun.trace_events))
    ).all()
    mutation_map: dict[str, list[str]] = {}
    for interface_id in experiment.interface_versions:
        mutation_map[interface_id] = sorted(
            {
                item
                for item in session.scalars(
                    select(InterfaceMutation.mutation_type).where(
                        InterfaceMutation.interface_version_id == interface_id
                    )
                )
            }
        )
    feature_cache: dict[str, dict[str, Any]] = {}
    observations = []
    for task_run, run, task, interface, project in rows:
        features = feature_cache.setdefault(
            interface.id, interface_features(interface.tool_definitions_snapshot)
        )
        tool_calls = [event for event in task_run.trace_events if event.event_type == "TOOL_CALLED"]
        validation_errors = [
            event
            for event in task_run.trace_events
            if event.event_type == "ERROR" and event.payload.get("code") == "VALIDATION_ERROR"
        ]
        tokens = task_run.token_usage or {}
        observations.append(
            {
                "experiment_id": experiment.id,
                "api_domain": project.sandbox_domain,
                "interface_version": interface.variant_key,
                "interface_version_id": interface.id,
                "mutation_types": mutation_map.get(interface.id, []),
                "tool_features": features,
                "model": task_run.model_identifier,
                "synthetic": run.synthetic,
                "task_id": task.id,
                "task_version": task_run.task_version,
                "task_split": task_run.task_split,
                "trial_number": task_run.trial_number,
                "task_category": task.category,
                "difficulty": task.difficulty,
                "success": task_run.success,
                "failure_category": task_run.failure_category,
                "tool_selection_correct": bool(
                    task_run.evaluator_result.get("tool_requirements_passed", False)
                    and task_run.evaluator_result.get("forbidden_tools_avoided", False)
                ),
                "arguments_correct": not validation_errors,
                "tool_calls": len(tool_calls),
                "latency": task_run.duration,
                "tokens": {
                    "input": int(tokens.get("input", 0)),
                    "output": int(tokens.get("output", 0)),
                    "total": int(tokens.get("input", 0)) + int(tokens.get("output", 0)),
                },
                "cost": task_run.cost_estimate,
                "temperature": task_run.temperature,
                "seed": task_run.provider_seed,
            }
        )
    return observations


def export_experiment_dataset(
    session: Session, experiment: Experiment, output_dir: Path | None = None
) -> tuple[Path, Path]:
    output_dir = output_dir or _repo_root() / "data" / "phase15"
    output_dir.mkdir(parents=True, exist_ok=True)
    observations = experiment_observations(session, experiment)
    jsonl_path = output_dir / "experiment_results.jsonl"
    csv_path = output_dir / "experiment_results.csv"
    jsonl_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in observations),
        encoding="utf-8",
    )
    scalar_fields = [
        "experiment_id",
        "api_domain",
        "interface_version",
        "interface_version_id",
        "model",
        "synthetic",
        "task_id",
        "task_version",
        "task_split",
        "trial_number",
        "task_category",
        "difficulty",
        "success",
        "failure_category",
        "tool_selection_correct",
        "arguments_correct",
        "tool_calls",
        "latency",
        "cost",
        "temperature",
        "seed",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "mutation_types",
        "number_of_tools",
        "mean_semantic_overlap_jaccard",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=scalar_fields)
        writer.writeheader()
        for row in observations:
            writer.writerow(
                {
                    **{field: row.get(field) for field in scalar_fields},
                    "input_tokens": row["tokens"]["input"],
                    "output_tokens": row["tokens"]["output"],
                    "total_tokens": row["tokens"]["total"],
                    "mutation_types": "|".join(row["mutation_types"]),
                    "number_of_tools": row["tool_features"]["number_of_tools"],
                    "mean_semantic_overlap_jaccard": row["tool_features"][
                        "mean_semantic_overlap_jaccard"
                    ],
                }
            )
    return jsonl_path, csv_path
