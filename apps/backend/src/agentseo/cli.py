from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer
from sqlalchemy import select

from .config import get_settings
from .database import SessionLocal, create_schema
from .experiments import (
    ATTRIBUTION_VARIANTS,
    DEFAULT_VARIANTS,
    Phase15Configuration,
    analyze_experiment,
    estimate_experiment_cost,
    finalize_experiment_artifacts,
    resolve_models,
    run_phase15_sync,
)
from .models import BenchmarkTask, Experiment, InterfaceVersion, Project, ToolDefinition
from .openapi_parser import NormalizedTool, parse_openapi
from .runner import run_benchmark
from .task_generation import generate_template_tasks

app = typer.Typer(help="AgentSEO API compatibility benchmark CLI")
experiment_app = typer.Typer(help="Reproducible controlled interface experiments")
app.add_typer(experiment_app, name="experiment")
ROOT = Path(__file__).resolve().parents[4]


def load_spec(path: Path) -> tuple[dict[str, Any], list[NormalizedTool]]:
    return parse_openapi(path.read_bytes())


@app.command()
def inspect(spec: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    document, tools = load_spec(spec)
    info = document.get("info")
    title = info.get("title", spec.name) if isinstance(info, dict) else spec.name
    typer.echo(f"{title} — {len(tools)} tools")
    for tool in tools:
        marker = " [DESTRUCTIVE]" if tool.is_destructive else ""
        typer.echo(f"{tool.http_method:6} {tool.path:35} {tool.name}{marker}")


@app.command("generate-tasks")
def generate_tasks(
    spec: Annotated[Path, typer.Argument(exists=True, dir_okay=False)], domain: str = "generic"
) -> None:
    _, tools = load_spec(spec)
    typer.echo(
        json.dumps([task.to_dict() for task in generate_template_tasks(tools, domain)], indent=2)
    )


@app.command()
def benchmark(
    spec: Annotated[Path, typer.Option("--spec", exists=True, dir_okay=False)],
    models: Annotated[list[str] | None, typer.Option("--models")] = None,
    domain: str = "billing",
) -> None:
    models = models or ["mock:reliable"]
    document, tools = load_spec(spec)
    create_schema()
    with SessionLocal() as session:
        project = Project(
            name=document.get("info", {}).get("title", spec.stem), sandbox_domain=domain
        )
        session.add(project)
        session.flush()
        session.add_all([ToolDefinition(project_id=project.id, **tool.to_dict()) for tool in tools])
        session.add(
            InterfaceVersion(
                project_id=project.id,
                tool_definitions_snapshot=[tool.to_dict() for tool in tools],
                name="V0 — Canonical baseline",
                variant_key="baseline",
                frozen=True,
            )
        )
        tasks = [
            BenchmarkTask(project_id=project.id, **task.to_dict())
            for task in generate_template_tasks(tools, domain)
        ]
        session.add_all(tasks)
        session.commit()
        for identifier in models:
            run = asyncio.run(
                run_benchmark(session, project, identifier, tasks, {}, get_settings())
            )
            label = "Synthetic Demo Results" if run.synthetic else "Provider Results"
            typer.echo(
                f"{label}: {run.provider}:{run.model} — "
                f"{run.aggregate_metrics['compatibility_score']}/100"
            )


def _ensure_phase15_project(domain: str) -> Project:
    if domain not in {"billing", "ecommerce", "crm"}:
        raise typer.BadParameter(f"Unknown sandbox domain: {domain}")
    spec = ROOT / "examples" / domain / "openapi.yaml"
    _, tools = load_spec(spec)
    project_name = f"Phase 1.5 {domain.title()} — dataset 1.5"
    with SessionLocal() as session:
        project = session.scalar(
            select(Project)
            .where(
                Project.sandbox_domain == domain,
                Project.name == project_name,
            )
            .order_by(Project.created_at.asc())
        )
        if not project:
            project = Project(
                name=project_name,
                description="Reproducible Phase 1.5 experimental sandbox",
                sandbox_domain=domain,
            )
            session.add(project)
            session.flush()
        if not session.scalar(
            select(ToolDefinition.id).where(ToolDefinition.project_id == project.id)
        ):
            session.add_all(
                [ToolDefinition(project_id=project.id, **tool.to_dict()) for tool in tools]
            )
        if not session.scalar(
            select(InterfaceVersion.id).where(
                InterfaceVersion.project_id == project.id,
                InterfaceVersion.variant_key == "baseline",
            )
        ):
            session.add(
                InterfaceVersion(
                    project_id=project.id,
                    tool_definitions_snapshot=[tool.to_dict() for tool in tools],
                    name="V0 — Canonical baseline",
                    variant_key="baseline",
                    frozen=True,
                )
            )
        if not session.scalar(
            select(BenchmarkTask.id).where(BenchmarkTask.project_id == project.id)
        ):
            session.add_all(
                [
                    BenchmarkTask(project_id=project.id, **task.to_dict())
                    for task in generate_template_tasks(tools, domain)
                ]
            )
        session.commit()
        return project


@experiment_app.command("phase15")
def phase15(
    projects: Annotated[list[str] | None, typer.Option("--project")] = None,
    models: Annotated[list[str] | None, typer.Option("--models")] = None,
    variants: Annotated[list[str] | None, typer.Option("--variants")] = None,
    repetitions: Annotated[int | None, typer.Option("--repetitions", min=1, max=20)] = None,
    max_cost_usd: Annotated[float | None, typer.Option("--max-cost-usd", min=0)] = None,
    include_attribution: bool = typer.Option(False, "--include-attribution"),
) -> None:
    """Run Phase 1.5; providers without configured keys are explicitly skipped."""

    settings = get_settings()
    create_schema()
    domains = projects or ["billing", "ecommerce", "crm"]
    selected_projects = [_ensure_phase15_project(domain) for domain in domains]
    resolved_models, unavailable = resolve_models(models, settings)
    if not resolved_models:
        resolved_models = ["mock:reliable"]
        typer.echo("No real provider keys found; running MockAgent system validation only.")
    selected_variants = variants or list(DEFAULT_VARIANTS)
    if include_attribution:
        selected_variants.extend(ATTRIBUTION_VARIANTS)
    selected_variants = list(dict.fromkeys(selected_variants))
    configuration = Phase15Configuration(
        models=resolved_models,
        variants=selected_variants,
        repetitions=repetitions or settings.phase15_repetitions,
        split_seed=settings.phase15_task_split_seed,
        temperature=settings.phase15_temperature,
        max_cost_usd=(settings.phase15_max_cost_usd if max_cost_usd is None else max_cost_usd),
        max_concurrency=settings.phase15_max_concurrency,
        bootstrap_samples=settings.phase15_bootstrap_samples,
        unavailable_providers=unavailable,
    )
    with SessionLocal() as session:
        concrete_projects = [
            project
            for project in (session.get(Project, item.id) for item in selected_projects)
            if project is not None
        ]
        task_count = len(
            list(
                session.scalars(
                    select(BenchmarkTask.id).where(
                        BenchmarkTask.project_id.in_([item.id for item in concrete_projects]),
                        BenchmarkTask.enabled.is_(True),
                    )
                )
            )
        )
        estimate = estimate_experiment_cost(task_count, configuration)
        typer.echo("Experiment ready.")
        typer.echo(
            f"Estimated model cost (with 25% guard): ${estimate['guarded_estimate_usd']:.4f}"
        )
        typer.echo(f"Models: {', '.join(resolved_models)}")
        typer.echo(f"Tasks: {task_count}")
        typer.echo(f"Variants: {', '.join(selected_variants)}")
        typer.echo(f"Repetitions: {configuration.repetitions}")
        experiment, artifacts = run_phase15_sync(
            session, concrete_projects, configuration, settings
        )
        if experiment.status == "BLOCKED_COST":
            typer.echo(experiment.notes)
            typer.echo(
                "Run command: agentseo experiment phase15 "
                f"--max-cost-usd {experiment.estimated_cost:.2f}"
            )
            raise typer.Exit(2)
        typer.echo(f"Experiment ID: {experiment.id}")
        typer.echo(f"Actual recorded cost: ${experiment.actual_cost:.6f}")
        typer.echo(f"Report: {artifacts['report_markdown']}")
        typer.echo(f"Decision: {artifacts['analysis']['decision']}")


@experiment_app.command("analyze")
def experiment_analyze(experiment_id: str) -> None:
    create_schema()
    with SessionLocal() as session:
        experiment = session.get(Experiment, experiment_id)
        if not experiment:
            raise typer.BadParameter("Experiment not found")
        analysis = analyze_experiment(
            session, experiment, bootstrap_samples=get_settings().phase15_bootstrap_samples
        )
        typer.echo(json.dumps(analysis, indent=2, default=str))


@experiment_app.command("report")
def experiment_report(experiment_id: str) -> None:
    create_schema()
    with SessionLocal() as session:
        experiment = session.get(Experiment, experiment_id)
        if not experiment:
            raise typer.BadParameter("Experiment not found")
        artifacts = finalize_experiment_artifacts(
            session, experiment, bootstrap_samples=get_settings().phase15_bootstrap_samples
        )
        typer.echo(artifacts["report_markdown"])


if __name__ == "__main__":
    app()
