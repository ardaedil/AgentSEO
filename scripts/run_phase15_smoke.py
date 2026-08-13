"""Run the bounded five-task, real-provider Phase 1.5 connectivity smoke test."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
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
SMOKE_TASKS = {
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

SCIENTIFIC_TASKS = {
    "billing": {
        "Cancel John's subscription safely",
        "Find unpaid invoice",
        "Ambiguous subscription cancellation",
        "Locate a billing customer by email",
        "Retrieve one billing customer by identifier",
        "Schedule a subscription cancellation",
        "Recover from an invalid identifier: delete a confirmed billing customer",
    },
    "ecommerce": {
        "Refund only the failed shipment",
        "Ambiguous refund request",
        "Locate a shopper by email",
        "Retrieve one shopper by identifier",
        "Recover from an invalid identifier: retrieve one shopper by identifier",
        "Refund one confirmed purchase",
        "List failed deliveries",
    },
    "crm": {
        "Assign high-value Acme opportunities",
        "Ambiguous opportunity deletion",
        "Locate a company by name",
        "Respect semantic boundaries: locate a company by name",
        "Assign one sales opportunity",
        "Recover from an invalid identifier: retrieve one company by identifier",
    },
}


def seed_projects(selected_tasks: dict[str, set[str]], task_set: str) -> list[Project]:
    projects: list[Project] = []
    with SessionLocal() as session:
        for domain, titles in selected_tasks.items():
            _, tools = parse_openapi((ROOT / "examples" / domain / "openapi.yaml").read_bytes())
            project = Project(
                name=f"Phase 1.5 {task_set} real-provider run — {domain}",
                description=(
                    "Five-task V0 connectivity smoke test; not scientific evidence"
                    if task_set == "smoke"
                    else "Frozen 20-task V0 versus V1 real-provider experiment"
                ),
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
                raise RuntimeError(f"Missing {task_set} tasks for {domain}: {sorted(missing)}")
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
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--task-set", choices=("smoke", "scientific"), default="smoke")
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=("openai", "anthropic", "google"),
        default=["openai", "anthropic", "google"],
    )
    args = parser.parse_args()
    selected_tasks = SMOKE_TASKS if args.task_set == "smoke" else SCIENTIFIC_TASKS
    task_count = sum(len(titles) for titles in selected_tasks.values())
    variants = ["baseline"] if args.task_set == "smoke" else ["baseline", "degraded"]
    repetitions = 1 if args.task_set == "smoke" else 3
    output_root = args.output_root or ROOT / "artifacts" / f"phase15_{args.task_set}"
    settings = get_settings()
    models, unavailable = resolve_models(args.providers, settings)
    if unavailable or len(models) != len(args.providers):
        raise RuntimeError(f"Requested real providers are not configured: {unavailable}")
    configuration = Phase15Configuration(
        models=models,
        variants=variants,
        repetitions=repetitions,
        split_seed=settings.phase15_task_split_seed,
        temperature=settings.phase15_temperature,
        max_cost_usd=settings.phase15_max_cost_usd,
        max_concurrency=settings.phase15_max_concurrency,
        bootstrap_samples=settings.phase15_bootstrap_samples,
    )
    estimate = estimate_experiment_cost(task_count, configuration)
    if float(estimate["guarded_estimate_usd"]) > settings.phase15_max_cost_usd:
        raise RuntimeError("Smoke estimate exceeds PHASE15_MAX_COST_USD")
    create_schema()
    seeded = seed_projects(selected_tasks, args.task_set)
    with SessionLocal() as session:
        projects = [session.get(Project, item.id) for item in seeded]
        experiment = await run_phase15_experiment(
            session,
            [project for project in projects if project is not None],
            configuration,
            settings,
            name=(
                "Phase 1.5 five-task real-provider V0 smoke test"
                if args.task_set == "smoke"
                else "Phase 1.5 frozen 20-task real-provider V0 versus V1 experiment"
            ),
            manifest_path=output_root / "data" / "experiment_manifest.json",
        )
        analysis = analyze_experiment(
            session, experiment, bootstrap_samples=settings.phase15_bootstrap_samples
        )
        export_experiment_dataset(session, experiment, output_root / "data")
        generate_report(experiment, analysis, output_root / "report")
        result = summarize(experiment.id)
        result["status"] = experiment.status
        result["infrastructure_errors"] = experiment.notes.splitlines() if experiment.notes else []
        result["models"] = models
        result["task_titles"] = sorted(
            title for titles in selected_tasks.values() for title in titles
        )
        result["task_set"] = args.task_set
        result["estimate"] = estimate
        result["artifacts"] = str(output_root)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
