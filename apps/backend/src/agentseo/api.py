from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from .config import Settings, get_settings
from .database import get_session
from .models import (
    APISpec,
    BenchmarkRun,
    BenchmarkTask,
    InterfaceVersion,
    Project,
    TaskRun,
    ToolDefinition,
)
from .openapi_parser import NormalizedTool, OpenAPIError, parse_openapi
from .runner import run_benchmark
from .schemas import (
    BenchmarkRequest,
    BenchmarkRunRead,
    ProjectCreate,
    ProjectRead,
    TaskRead,
    TaskRunRead,
    TaskWrite,
    ToolRead,
)
from .task_generation import generate_template_tasks

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def require_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def normalized(tool: ToolDefinition) -> NormalizedTool:
    return NormalizedTool(
        name=tool.name,
        operation_id=tool.operation_id,
        http_method=tool.http_method,
        path=tool.path,
        description=tool.description,
        parameters=tool.parameters,
        request_schema=tool.request_schema,
        response_schema=tool.response_schema,
        tags=tool.tags,
        is_destructive=tool.is_destructive,
        inferred_destructive=tool.inferred_destructive,
        requires_authentication=tool.requires_authentication,
        tool_metadata=tool.tool_metadata,
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "agentseo"}


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(session: SessionDep) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.created_at.desc())))


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, session: SessionDep) -> Project:
    project = Project(**payload.model_dump())
    session.add(project)
    session.commit()
    return project


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, session: SessionDep) -> Project:
    return require_project(session, project_id)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, session: SessionDep) -> None:
    project = require_project(session, project_id)
    session.delete(project)
    session.commit()


@router.post("/projects/{project_id}/specs", response_model=list[ToolRead])
async def upload_spec(
    project_id: str,
    session: SessionDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
) -> list[ToolDefinition]:
    project = require_project(session, project_id)
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, f"Specification exceeds {settings.max_upload_bytes} bytes")
    try:
        document, parsed_tools = parse_openapi(content)
    except OpenAPIError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.add(
        APISpec(
            project_id=project.id,
            raw_specification=document,
            openapi_version=document["openapi"],
            parsed_metadata={
                "title": document.get("info", {}).get("title"),
                "operation_count": len(parsed_tools),
                "filename": file.filename,
            },
        )
    )
    session.execute(delete(ToolDefinition).where(ToolDefinition.project_id == project.id))
    rows = [ToolDefinition(project_id=project.id, **tool.to_dict()) for tool in parsed_tools]
    session.add_all(rows)
    previous = session.scalar(
        select(InterfaceVersion)
        .where(InterfaceVersion.project_id == project.id)
        .order_by(InterfaceVersion.version.desc())
    )
    session.add(
        InterfaceVersion(
            project_id=project.id,
            version=(previous.version + 1 if previous else 1),
            parent_version_id=previous.id if previous else None,
            tool_definitions_snapshot=[tool.to_dict() for tool in parsed_tools],
            change_description=f"Imported {file.filename or 'OpenAPI specification'}",
        )
    )
    title = str(document.get("info", {}).get("title", "")).lower()
    if project.sandbox_domain == "generic":
        project.sandbox_domain = next(
            (domain for domain in ("billing", "ecommerce", "crm") if domain in title), "generic"
        )
    session.commit()
    return rows


@router.get("/projects/{project_id}/tools", response_model=list[ToolRead])
def list_tools(project_id: str, session: SessionDep) -> list[ToolDefinition]:
    require_project(session, project_id)
    return list(
        session.scalars(
            select(ToolDefinition)
            .where(ToolDefinition.project_id == project_id)
            .order_by(ToolDefinition.tags, ToolDefinition.name)
        )
    )


@router.patch("/tools/{tool_id}", response_model=ToolRead)
def update_tool(tool_id: str, session: SessionDep, is_destructive: bool) -> ToolDefinition:
    tool = session.get(ToolDefinition, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")
    tool.is_destructive = is_destructive
    session.commit()
    return tool


@router.post("/projects/{project_id}/tasks/generate", response_model=list[TaskRead])
def generate_tasks(
    project_id: str, session: SessionDep, replace: bool = Query(True)
) -> list[BenchmarkTask]:
    project = require_project(session, project_id)
    tools = list(
        session.scalars(select(ToolDefinition).where(ToolDefinition.project_id == project_id))
    )
    if not tools:
        raise HTTPException(409, "Upload an OpenAPI specification before generating tasks")
    if replace:
        session.execute(delete(BenchmarkTask).where(BenchmarkTask.project_id == project_id))
    tasks = [
        BenchmarkTask(project_id=project_id, **item.to_dict())
        for item in generate_template_tasks(
            [normalized(tool) for tool in tools], project.sandbox_domain
        )
    ]
    session.add_all(tasks)
    session.commit()
    return tasks


@router.get("/projects/{project_id}/tasks", response_model=list[TaskRead])
def list_tasks(project_id: str, session: SessionDep) -> list[BenchmarkTask]:
    require_project(session, project_id)
    return list(
        session.scalars(
            select(BenchmarkTask)
            .where(BenchmarkTask.project_id == project_id)
            .order_by(BenchmarkTask.difficulty, BenchmarkTask.title)
        )
    )


@router.post("/projects/{project_id}/tasks", response_model=TaskRead, status_code=201)
def add_task(project_id: str, payload: TaskWrite, session: SessionDep) -> BenchmarkTask:
    require_project(session, project_id)
    task = BenchmarkTask(project_id=project_id, **payload.model_dump())
    session.add(task)
    session.commit()
    return task


@router.put("/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: str, payload: TaskWrite, session: SessionDep) -> BenchmarkTask:
    task = session.get(BenchmarkTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    for key, value in payload.model_dump().items():
        setattr(task, key, value)
    task.version += 1
    session.commit()
    return task


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, session: SessionDep) -> None:
    task = session.get(BenchmarkTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    session.delete(task)
    session.commit()


@router.post("/projects/{project_id}/benchmark-runs", response_model=list[BenchmarkRunRead])
async def create_runs(
    project_id: str, payload: BenchmarkRequest, session: SessionDep, settings: SettingsDep
) -> list[BenchmarkRun]:
    project = require_project(session, project_id)
    query = select(BenchmarkTask).where(
        BenchmarkTask.project_id == project_id, BenchmarkTask.enabled.is_(True)
    )
    if payload.task_ids:
        query = query.where(BenchmarkTask.id.in_(payload.task_ids))
    tasks = list(session.scalars(query))
    if not tasks:
        raise HTTPException(409, "No enabled tasks selected")
    if len(tasks) > settings.max_tasks_per_run:
        raise HTTPException(422, f"Run exceeds the {settings.max_tasks_per_run}-task safety limit")
    if len(payload.models) * len(tasks) > 100:
        raise HTTPException(422, "Large runs require reducing the model or task selection")
    configuration = payload.model_dump(exclude={"models", "task_ids"})
    runs: list[BenchmarkRun] = []
    for identifier in payload.models:
        try:
            runs.append(
                await run_benchmark(session, project, identifier, tasks, configuration, settings)
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return runs


@router.get("/projects/{project_id}/benchmark-runs", response_model=list[BenchmarkRunRead])
def list_runs(project_id: str, session: SessionDep) -> list[BenchmarkRun]:
    require_project(session, project_id)
    return list(
        session.scalars(
            select(BenchmarkRun)
            .where(BenchmarkRun.project_id == project_id)
            .order_by(BenchmarkRun.started_at.desc())
        )
    )


@router.get("/benchmark-runs/{run_id}", response_model=BenchmarkRunRead)
def get_run(run_id: str, session: SessionDep) -> BenchmarkRun:
    run = session.get(BenchmarkRun, run_id)
    if not run:
        raise HTTPException(404, "Benchmark run not found")
    return run


@router.get("/benchmark-runs/{run_id}/task-runs", response_model=list[TaskRunRead])
def list_task_runs(run_id: str, session: SessionDep) -> list[TaskRun]:
    if not session.get(BenchmarkRun, run_id):
        raise HTTPException(404, "Benchmark run not found")
    return list(
        session.scalars(
            select(TaskRun)
            .where(TaskRun.benchmark_run_id == run_id)
            .options(selectinload(TaskRun.trace_events))
        )
    )


@router.get("/task-runs/{task_run_id}", response_model=TaskRunRead)
def get_task_run(task_run_id: str, session: SessionDep) -> TaskRun:
    task_run = session.scalar(
        select(TaskRun).where(TaskRun.id == task_run_id).options(selectinload(TaskRun.trace_events))
    )
    if not task_run:
        raise HTTPException(404, "Task run not found")
    return task_run


@router.get("/projects/{project_id}/report")
def project_report(project_id: str, session: SessionDep) -> dict[str, Any]:
    project = require_project(session, project_id)
    runs = list(
        session.scalars(
            select(BenchmarkRun)
            .where(BenchmarkRun.project_id == project_id, BenchmarkRun.status == "COMPLETED")
            .order_by(BenchmarkRun.started_at.desc())
        )
    )
    comparison = [
        {
            "run_id": run.id,
            "provider": run.provider,
            "model": run.model,
            "synthetic": run.synthetic,
            **run.aggregate_metrics,
        }
        for run in runs
    ]
    return {
        "project": ProjectRead.model_validate(project).model_dump(mode="json"),
        "comparison": comparison,
        "experimental_metric": True,
        "notice": "Synthetic Demo Results"
        if comparison and all(row["synthetic"] for row in comparison)
        else None,
    }


@router.get("/projects/{project_id}/suggestions")
def suggestions(project_id: str, session: SessionDep) -> dict[str, Any]:
    require_project(session, project_id)
    runs = list(session.scalars(select(BenchmarkRun).where(BenchmarkRun.project_id == project_id)))
    categories: defaultdict[str, int] = defaultdict(int)
    for run in runs:
        for category, count in run.aggregate_metrics.get("failure_categories", {}).items():
            categories[category] += count
    items = []
    if categories.get("WRONG_TOOL"):
        items.append(
            {
                "type": "RENAME_TOOL",
                "message": "Models frequently select the wrong tool. Use action- and identifier-specific names, and separate overlapping descriptions.",
            }
        )
    if categories.get("MISSING_ARGUMENT") or categories.get("WRONG_ARGUMENT"):
        items.append(
            {
                "type": "CLARIFY_PARAMETER",
                "message": "Clarify required parameter semantics and add a concrete valid example.",
            }
        )
    if categories.get("DESTRUCTIVE_ACTION_ERROR"):
        items.append(
            {
                "type": "SEPARATE_DESTRUCTIVE_OPERATION",
                "message": "Separate destructive operations and add explicit negative safety instructions.",
            }
        )
    return {"label": "Experimental", "suggestions": items, "applied": False}
