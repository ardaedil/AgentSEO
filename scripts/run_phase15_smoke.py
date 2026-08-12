"""Run the bounded five-task, real-provider Phase 1.5 connectivity smoke test."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from agentseo.config import get_settings
from agentseo.database import SessionLocal, create_schema
from agentseo.experiments import (
    Phase15Configuration,
    analyze_experiment,
    estimate_experiment_cost,
    resolve_models,
    run_phase15_experiment,
)
from agentseo.models import (
    BenchmarkTask,
    InterfaceVersion,
    Project,
    TaskRun,
    ToolDefinition,
)
from agentseo.openapi_parser import parse_openapi
from agentseo.reporting import generate_report
from agentseo.research_export import export_experiment_dataset
from agentseo.task_generation import generate_template_tasks
from sqlalchemy import select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
SELECTED_TASKS = {
    "billing": {
        "Locate a billing customer by email",
        "Find unpaid invoice",
    },
    "ecommerce": {"Refund only the failed shipment"},
    "crm": {
        "Assign high-value Acme opportunities",
        "Delete a confirmed sales opportunity",
    },
}


def seed_smoke_projects() -> list[Project]:
    projects: list[Project] = []
    with SessionLocal() as session:
        for domain, titles in SELECTED_TASKS.items():
            _, tools = parse_openapi((ROOT / "examples" / domain / "openapi.yaml").read_bytes())
            project = Project(
                name=f"Phase 1.5 real-provider smoke — {domain}",
                description="Five-task V0 connectivity smoke test; not scientific evidence",
                sandbox_domain=domain,
            )
            session.add(project)
            session.flush()
            session.add_all(
                [ToolDefinition(project_id=project.id, **tool.to_dict()) for tool in tools]
            )
            session.add(
                InterfaceVersion(
                    project_id=project.id,
                    version=1,
                    tool_definitions_snapshot=[tool.to_dict() for tool in tools],
                    name="V0 — Canonical baseline",
                    variant_key="baseline",
                    frozen=True,
                )
            )
            generated = generate_template_tasks(tools, domain)
            selected = [task for task in generated if task.title in titles]
            if {task.title for task in selected} != titles:
                missing = titles - {task.title for task in selected}
                raise RuntimeError(f"Missing smoke tasks for {domain}: {sorted(missing)}")
            session.add_all(
                [BenchmarkTask(project_id=project.id, **task.to_dict()) for task in selected]
            )
            projects.append(project)
        session.commit()
        return projects


def summarize(experiment_id: str) -> dict[str, object]:
    with SessionLocal() as session:
        rows = session.execute(
            select(TaskRun)
            .where(TaskRun.experiment_id == experiment_id)
            .options(selectinload(TaskRun.trace_events))
        ).scalars()
        grouped: dict[str, list[TaskRun]] = {}
        for row in rows:
            grouped.setdefault(row.model_identifier, []).append(row)
        providers = []
        for model, task_runs in sorted(grouped.items()):
            tool_calls = sum(
                event.event_type == "TOOL_CALLED"
                for task_run in task_runs
                for event in task_run.trace_events
            )
            providers.append(
                {
                    "model": model,
                    "tasks_attempted": len(task_runs),
                    "tasks_completed": sum(row.status == "COMPLETED" for row in task_runs),
                    "tasks_successful": sum(row.success for row in task_runs),
                    "tool_calls_recorded": tool_calls,
                    "evaluator_functioning": all(bool(row.evaluator_result) for row in task_runs),
                    "trace_persistence": all(bool(row.trace_events) for row in task_runs),
                    "input_tokens": sum(int(row.token_usage.get("input", 0)) for row in task_runs),
                    "output_tokens": sum(
                        int(row.token_usage.get("output", 0)) for row in task_runs
                    ),
                    "recorded_approximate_cost": sum(row.cost_estimate for row in task_runs),
                    "failures": [
                        {
                            "task_id": row.task_id,
                            "category": row.failure_category,
                            "explanation": row.failure_explanation,
                        }
                        for row in task_runs
                        if not row.success
                    ],
                }
            )
        return {
            "experiment_id": experiment_id,
            "providers": providers,
            "total_approximate_cost": sum(
                float(provider["recorded_approximate_cost"]) for provider in providers
            ),
        }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "phase15_smoke")
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=("openai", "anthropic", "google"),
        default=["openai", "anthropic", "google"],
    )
    args = parser.parse_args()
    settings = get_settings()
    models, unavailable = resolve_models(args.providers, settings)
    if unavailable or len(models) != len(args.providers):
        raise RuntimeError(f"Requested real providers are not configured: {unavailable}")
    configuration = Phase15Configuration(
        models=models,
        variants=["baseline"],
        repetitions=1,
        split_seed=settings.phase15_task_split_seed,
        temperature=settings.phase15_temperature,
        max_cost_usd=settings.phase15_max_cost_usd,
        max_concurrency=settings.phase15_max_concurrency,
        bootstrap_samples=settings.phase15_bootstrap_samples,
    )
    estimate = estimate_experiment_cost(5, configuration)
    if float(estimate["guarded_estimate_usd"]) > settings.phase15_max_cost_usd:
        raise RuntimeError("Smoke estimate exceeds PHASE15_MAX_COST_USD")
    create_schema()
    seeded = seed_smoke_projects()
    with SessionLocal() as session:
        projects = [session.get(Project, item.id) for item in seeded]
        experiment = await run_phase15_experiment(
            session,
            [project for project in projects if project is not None],
            configuration,
            settings,
            name="Phase 1.5 five-task real-provider V0 smoke test",
            manifest_path=args.output_root / "data" / "experiment_manifest.json",
        )
        analysis = analyze_experiment(
            session, experiment, bootstrap_samples=settings.phase15_bootstrap_samples
        )
        export_experiment_dataset(session, experiment, args.output_root / "data")
        generate_report(experiment, analysis, args.output_root / "report")
        result = summarize(experiment.id)
        result["status"] = experiment.status
        result["infrastructure_errors"] = experiment.notes.splitlines() if experiment.notes else []
        result["models"] = models
        result["task_titles"] = sorted(
            title for titles in SELECTED_TASKS.values() for title in titles
        )
        result["estimate"] = estimate
        result["artifacts"] = str(args.output_root)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
