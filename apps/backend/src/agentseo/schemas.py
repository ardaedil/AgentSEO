from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    sandbox_domain: str = "generic"


class ProjectRead(ORMModel):
    id: str
    name: str
    description: str
    sandbox_domain: str
    created_at: datetime
    updated_at: datetime


class ToolRead(ORMModel):
    id: str
    project_id: str
    name: str
    operation_id: str
    http_method: str
    path: str
    description: str
    parameters: list[Any]
    request_schema: dict[str, Any]
    response_schema: dict[str, Any]
    tags: list[str]
    is_destructive: bool
    inferred_destructive: bool
    requires_authentication: bool
    tool_metadata: dict[str, Any]


class TaskWrite(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    natural_language_instruction: str = Field(min_length=1)
    difficulty: int = Field(default=1, ge=1, le=7)
    category: str = "single_tool"
    required_tools: list[str] = []
    forbidden_tools: list[str] = []
    initial_state: dict[str, Any] = {}
    expected_final_state: list[dict[str, Any]] = []
    expected_invariants: list[dict[str, Any]] = []
    requires_clarification: bool = False
    safety_level: str = "normal"
    generated_or_manual: str = "manual"
    enabled: bool = True


class TaskRead(TaskWrite, ORMModel):
    id: str
    project_id: str
    version: int


class BenchmarkRequest(BaseModel):
    models: list[str] = ["mock:reliable"]
    task_ids: list[str] | None = None
    max_iterations: int = Field(default=12, ge=1, le=50)
    max_tool_calls: int = Field(default=10, ge=1, le=30)
    timeout_seconds: int = Field(default=60, ge=1, le=600)


class BenchmarkRunRead(ORMModel):
    id: str
    project_id: str
    interface_version_id: str | None
    model: str
    provider: str
    started_at: datetime | None
    completed_at: datetime | None
    status: str
    configuration: dict[str, Any]
    aggregate_metrics: dict[str, Any]
    synthetic: bool


class TraceRead(ORMModel):
    id: str
    event_type: str
    sequence: int
    timestamp: datetime
    payload: dict[str, Any]


class TaskRunRead(ORMModel):
    id: str
    task_id: str
    benchmark_run_id: str
    status: str
    success: bool
    duration: float
    token_usage: dict[str, Any]
    cost_estimate: float
    failure_category: str | None
    failure_explanation: str | None
    evaluator_result: dict[str, Any]
    trace_events: list[TraceRead] = []
