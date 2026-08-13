"""Recalculate stored Phase 1.5 costs from persisted provider token usage."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from agentseo.config import get_settings
from agentseo.database import SessionLocal
from agentseo.experiments import _write_manifest, analyze_experiment, create_manifest
from agentseo.models import BenchmarkTask, Experiment, InterfaceVersion, TaskRun
from agentseo.pricing import estimate_usage_cost, pricing_manifest
from agentseo.reporting import generate_report
from agentseo.research_export import export_experiment_dataset
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]


def source_hash(relative_path: str) -> str:
    return hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_id")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    with SessionLocal() as session:
        experiment = session.get(Experiment, args.experiment_id)
        if experiment is None:
            raise RuntimeError(f"Experiment not found: {args.experiment_id}")
        task_runs = list(
            session.scalars(select(TaskRun).where(TaskRun.experiment_id == experiment.id))
        )
        for task_run in task_runs:
            task_run.cost_estimate = estimate_usage_cost(
                task_run.model_identifier,
                int(task_run.token_usage.get("input", 0)),
                int(task_run.token_usage.get("output", 0)),
            )
        experiment.actual_cost = sum(task_run.cost_estimate for task_run in task_runs)
        configuration = dict(experiment.configuration)
        configuration["provider_request_configuration"] = {
            "openai:gpt-4.1-mini": {
                "api": "Responses API",
                "temperature": 0.0,
            },
            "anthropic:claude-sonnet-5": {
                "api": "Messages API",
                "temperature": "omitted (unsupported non-default sampling parameters)",
                "adaptive_thinking": "provider default",
            },
            "google:gemini-3.6-flash": {
                "api": "GenerateContent API",
                "temperature": 0.0,
            },
        }
        configuration["pricing"] = pricing_manifest(experiment.models)
        experiment.configuration = configuration
        tasks = list(
            session.scalars(
                select(BenchmarkTask).where(
                    BenchmarkTask.project_id.in_(
                        select(BenchmarkTask.project_id)
                        .where(BenchmarkTask.id.in_([task_run.task_id for task_run in task_runs]))
                        .distinct()
                    )
                )
            )
        )
        interfaces = list(
            session.scalars(
                select(InterfaceVersion).where(
                    InterfaceVersion.id.in_(experiment.interface_versions)
                )
            )
        )
        previous_manifest = dict(experiment.manifest)
        manifest = create_manifest(experiment, tasks, interfaces)
        for key in (
            "completed_at",
            "failed_cells",
            "resumed_after_interruption",
            "completed_cells_preserved",
            "interrupted_cells_restarted",
        ):
            if key in previous_manifest:
                manifest[key] = previous_manifest[key]
        manifest["actual_cost_usd"] = experiment.actual_cost
        manifest["provider_request_configuration"] = configuration["provider_request_configuration"]
        manifest["pricing"] = configuration["pricing"]
        manifest["source_sha256"] = {
            "providers.py": source_hash("apps/backend/src/agentseo/providers.py"),
            "runner.py": source_hash("apps/backend/src/agentseo/runner.py"),
            "pricing.py": source_hash("apps/backend/src/agentseo/pricing.py"),
            "run_phase15_smoke.py": source_hash("scripts/run_phase15_smoke.py"),
        }
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
                    "experiment_id": experiment.id,
                    "task_runs": len(task_runs),
                    "actual_estimated_cost_usd": experiment.actual_cost,
                    "pricing": configuration["pricing"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
