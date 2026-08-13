"""Freeze the calibrated R2 benchmark and seal its family-level holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from agentseo.database import SessionLocal
from agentseo.models import BenchmarkTask, Experiment, Project, TaskRun
from agentseo.phase15b_r2_benchmark import (
    PHASE15B_R2_EVALUATOR_VERSION,
    PHASE15B_R2_PROTOCOL,
    PHASE15B_R2_SPLIT_SEED,
    R2_UNCALIBRATED_FAMILIES,
)
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "artifacts" / "phase15b_r2" / "frozen_benchmark"
EVALUATOR_FILES = (
    ROOT / "apps" / "backend" / "src" / "agentseo" / "evaluation.py",
    ROOT / "apps" / "backend" / "src" / "agentseo" / "providers.py",
    ROOT / "apps" / "backend" / "src" / "agentseo" / "runner.py",
    ROOT / "apps" / "backend" / "src" / "agentseo" / "sandboxes.py",
    ROOT / "apps" / "backend" / "src" / "agentseo" / "phase15b_r2_benchmark.py",
)


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _task_payload(task: BenchmarkTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "version": task.version,
        "title": task.title,
        "natural_language_instruction": task.natural_language_instruction,
        "difficulty": task.difficulty,
        "category": task.category,
        "task_family": task.task_family,
        "required_tools": task.required_tools,
        "forbidden_tools": task.forbidden_tools,
        "initial_state": task.initial_state,
        "expected_final_state": task.expected_final_state,
        "expected_invariants": task.expected_invariants,
        "requires_clarification": task.requires_clarification,
        "safety_level": task.safety_level,
        "generated_or_manual": task.generated_or_manual,
    }


def _distribution(tasks: list[BenchmarkTask], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(getattr(task, field)) for task in tasks).items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("calibration_experiment_id")
    args = parser.parse_args()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as session:
        experiment = session.get(Experiment, args.calibration_experiment_id)
        if experiment is None or experiment.status != "COMPLETED":
            raise RuntimeError("A completed Calibration B experiment is required")
        if experiment.configuration.get("stage") != "CALIBRATION_B":
            raise RuntimeError("The supplied experiment is not Calibration B")
        result_by_model = {
            row["model"]: float(row["success_rate"])
            for row in experiment.manifest.get("results", [])
        }
        # The requested bands are approximate experimental targets, not quotas. The
        # hard gate is meaningful headroom with no model above the instructed 90%
        # ceiling-review threshold.
        targets = {
            "openai:gpt-4.1-mini": (0.50, 0.90),
            "anthropic:claude-sonnet-5": (0.60, 0.90),
            "google:gemini-3.6-flash": (0.60, 0.90),
        }
        if set(result_by_model) != set(targets) or any(
            not lower <= result_by_model[model] <= upper
            for model, (lower, upper) in targets.items()
        ):
            raise RuntimeError("Calibration B does not provide the required all-model headroom")

        tasks = list(session.scalars(select(BenchmarkTask).order_by(BenchmarkTask.id)))
        projects = {row.id: row for row in session.scalars(select(Project))}
        if len(tasks) != 120 or len({task.task_family for task in tasks}) != 40:
            raise RuntimeError("R2 freeze requires exactly 120 tasks in 40 families")
        if int(
            session.scalar(select(func.count(TaskRun.id)).where(TaskRun.task_split == "holdout"))
            or 0
        ):
            raise RuntimeError("Holdout observations already exist; refusing to seal after opening")

        for task in tasks:
            task.phase15_split = (
                "holdout" if task.task_family in R2_UNCALIBRATED_FAMILIES else "development"
            )
        session.commit()
        development = [task for task in tasks if task.phase15_split == "development"]
        holdout = [task for task in tasks if task.phase15_split == "holdout"]
        if (len(development), len(holdout)) != (84, 36):
            raise RuntimeError("R2 family split must be exactly 84 development / 36 holdout")
        if {task.task_family for task in development} & {task.task_family for task in holdout}:
            raise RuntimeError("Task-family leakage detected")
        required_categories = {
            "clarification_required",
            "clarification_not_required",
            "multi_step",
            "error_recovery",
            "safety_destructive",
            "tool_overlap",
            "identifier_routing",
            "constraint_preservation",
            "unsupported_semantics",
            "post_success",
        }
        if {task.category for task in holdout} != required_categories:
            raise RuntimeError("Sealed holdout does not cover every required category")

        evaluator_files = {
            str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in EVALUATOR_FILES
        }
        evaluator_bundle_hash = _hash(
            {"version": PHASE15B_R2_EVALUATOR_VERSION, "files": evaluator_files}
        )
        task_hashes = {task.id: _hash(_task_payload(task)) for task in tasks}
        family_hashes = {
            family: hashlib.sha256(f"{PHASE15B_R2_SPLIT_SEED}:{family}".encode()).hexdigest()
            for family in {task.task_family for task in tasks}
        }
        benchmark_hash = _hash(
            {
                "evaluator_bundle_sha256": evaluator_bundle_hash,
                "task_definition_sha256": task_hashes,
                "split": {task.id: task.phase15_split for task in tasks},
            }
        )
        holdout_manifest = {
            "protocol": PHASE15B_R2_PROTOCOL,
            "state": "SEALED_UNOPENED",
            "immutable": True,
            "task_count": len(holdout),
            "task_family_count": len({task.task_family for task in holdout}),
            "evaluator_version": PHASE15B_R2_EVALUATOR_VERSION,
            "evaluator_bundle_sha256": evaluator_bundle_hash,
            "benchmark_sha256": benchmark_hash,
            "tasks": [
                {
                    "task_id": task.id,
                    "task_version": task.version,
                    "task_definition_sha256": task_hashes[task.id],
                    "task_family_sha256": family_hashes[task.task_family],
                }
                for task in holdout
            ],
        }
        holdout_manifest["holdout_manifest_sha256"] = _hash(holdout_manifest)
        protocol_manifest = {
            "protocol": PHASE15B_R2_PROTOCOL,
            "state": "FROZEN_PRE_HOLDOUT",
            "source_git_commit": _git_commit(),
            "split_seed": PHASE15B_R2_SPLIT_SEED,
            "split_method": "twelve complete uncalibrated families held out; no task-level overlap",
            "benchmark_sha256": benchmark_hash,
            "evaluator_version": PHASE15B_R2_EVALUATOR_VERSION,
            "evaluator_bundle_sha256": evaluator_bundle_hash,
            "evaluator_files": evaluator_files,
            "total_tasks": len(tasks),
            "total_task_families": len({task.task_family for task in tasks}),
            "development_tasks": len(development),
            "development_task_families": len({task.task_family for task in development}),
            "holdout_tasks": len(holdout),
            "holdout_task_families": len({task.task_family for task in holdout}),
            "family_overlap_count": 0,
            "category_distribution": _distribution(tasks, "category"),
            "difficulty_distribution": _distribution(tasks, "difficulty"),
            "domain_distribution": dict(
                sorted(Counter(projects[task.project_id].sandbox_domain for task in tasks).items())
            ),
            "development_category_distribution": _distribution(development, "category"),
            "holdout_category_distribution": _distribution(holdout, "category"),
            "calibration_experiment_id": experiment.id,
            "calibration_results": experiment.manifest.get("results", []),
            "holdout_manifest_sha256": holdout_manifest["holdout_manifest_sha256"],
            "holdout_task_runs_at_freeze": 0,
        }
        protocol_manifest["protocol_manifest_sha256"] = _hash(protocol_manifest)
        (OUTPUT_ROOT / "holdout_manifest.json").write_text(
            json.dumps(holdout_manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        (OUTPUT_ROOT / "protocol_manifest.json").write_text(
            json.dumps(protocol_manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "development_tasks": len(development),
                    "development_families": len({task.task_family for task in development}),
                    "holdout_tasks": len(holdout),
                    "holdout_families": len({task.task_family for task in holdout}),
                    "holdout_category_distribution": _distribution(holdout, "category"),
                    "benchmark_sha256": benchmark_hash,
                    "holdout_manifest_sha256": holdout_manifest["holdout_manifest_sha256"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
