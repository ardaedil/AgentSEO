from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FailureCategory(StrEnum):
    WRONG_TOOL = "WRONG_TOOL"
    WRONG_ARGUMENT = "WRONG_ARGUMENT"
    MISSING_ARGUMENT = "MISSING_ARGUMENT"
    HALLUCINATED_TOOL = "HALLUCINATED_TOOL"
    UNNECESSARY_TOOL = "UNNECESSARY_TOOL"
    TOOL_SEQUENCE_ERROR = "TOOL_SEQUENCE_ERROR"
    ERROR_RECOVERY_FAILURE = "ERROR_RECOVERY_FAILURE"
    FAILED_TO_CLARIFY = "FAILED_TO_CLARIFY"
    UNNECESSARY_CLARIFICATION = "UNNECESSARY_CLARIFICATION"
    DESTRUCTIVE_ACTION_ERROR = "DESTRUCTIVE_ACTION_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    MODEL_REFUSAL = "MODEL_REFUSAL"
    FINAL_STATE_MISMATCH = "FINAL_STATE_MISMATCH"
    UNKNOWN = "UNKNOWN"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    sandbox_domain: Mapped[str] = mapped_column(String(50), default="generic")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    specs: Mapped[list[APISpec]] = relationship(cascade="all, delete-orphan")
    tools: Mapped[list[ToolDefinition]] = relationship(cascade="all, delete-orphan")
    tasks: Mapped[list[BenchmarkTask]] = relationship(cascade="all, delete-orphan")
    runs: Mapped[list[BenchmarkRun]] = relationship(cascade="all, delete-orphan")


class APISpec(Base):
    __tablename__ = "api_specs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    raw_specification: Mapped[dict[str, Any]] = mapped_column(JSON)
    openapi_version: Mapped[str] = mapped_column(String(30))
    parsed_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ToolDefinition(Base):
    __tablename__ = "tool_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    operation_id: Mapped[str] = mapped_column(String(200))
    http_method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    parameters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    request_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_destructive: Mapped[bool] = mapped_column(Boolean, default=False)
    inferred_destructive: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_authentication: Mapped[bool] = mapped_column(Boolean, default=False)
    tool_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class InterfaceVersion(Base):
    __tablename__ = "interface_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    tool_definitions_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("interface_versions.id"))
    change_description: Mapped[str] = mapped_column(Text, default="Initial imported interface")


class BenchmarkTask(Base):
    __tablename__ = "benchmark_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(250))
    natural_language_instruction: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str] = mapped_column(String(80), default="single_tool")
    required_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    forbidden_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    initial_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expected_final_state: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    expected_invariants: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    requires_clarification: Mapped[bool] = mapped_column(Boolean, default=False)
    safety_level: Mapped[str] = mapped_column(String(30), default="normal")
    generated_or_manual: Mapped[str] = mapped_column(String(20), default="generated")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    interface_version_id: Mapped[str | None] = mapped_column(ForeignKey("interface_versions.id"))
    model: Mapped[str] = mapped_column(String(150))
    provider: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default=RunStatus.PENDING.value)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    aggregate_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)

    task_runs: Mapped[list[TaskRun]] = relationship(cascade="all, delete-orphan")


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("benchmark_tasks.id"))
    benchmark_run_id: Mapped[str] = mapped_column(
        ForeignKey("benchmark_runs.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(30), default=RunStatus.PENDING.value)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    failure_category: Mapped[str | None] = mapped_column(String(60))
    failure_explanation: Mapped[str | None] = mapped_column(Text)
    evaluator_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    trace_events: Mapped[list[TraceEvent]] = relationship(
        cascade="all, delete-orphan", order_by="TraceEvent.sequence"
    )


class TraceEvent(Base):
    __tablename__ = "trace_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_run_id: Mapped[str] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(50))
    sequence: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
