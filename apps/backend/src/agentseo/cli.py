from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer

from .config import get_settings
from .database import SessionLocal, create_schema
from .models import BenchmarkTask, InterfaceVersion, Project, ToolDefinition
from .openapi_parser import NormalizedTool, parse_openapi
from .runner import run_benchmark
from .task_generation import generate_template_tasks

app = typer.Typer(help="AgentSEO API compatibility benchmark CLI")


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
        rows = [ToolDefinition(project_id=project.id, **tool.to_dict()) for tool in tools]
        session.add_all(rows)
        interface = InterfaceVersion(
            project_id=project.id, tool_definitions_snapshot=[tool.to_dict() for tool in tools]
        )
        session.add(interface)
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
                f"{label}: {run.provider}:{run.model} — {run.aggregate_metrics['compatibility_score']}/100"
            )


if __name__ == "__main__":
    app()
