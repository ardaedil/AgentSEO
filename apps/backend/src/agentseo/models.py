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
    POST_SUCCESS_CLARIFICATION = "POST_SUCCESS_CLARIFICATION"
    FAILED_TO_REFUSE = "FAILED_TO_REFUSE"
    DESTRUCTIVE_ACTION_ERROR = "DESTRUCTIVE_ACTION_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    MODEL_REFUSAL = "MODEL_REFUSAL"
    FINAL_STATE_MISMATCH = "FINAL_STATE_MISMATCH"
    UNKNOWN = "UNKNOWN"


class ExperimentStatus(StrEnum):
    PLANNED = "PLANNED"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED_COST = "BLOCKED_COST"
    FAILED = "FAILED"


class CompatibilityVerdict(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class AgenticCompatibilityClass(StrEnum):
    AGENT_COMPATIBLE = "AGENT_COMPATIBLE"
    AGENT_WARNING = "AGENT_WARNING"
    AGENT_BREAKING = "AGENT_BREAKING"


class CompatibilityRegressionType(StrEnum):
    RELIABILITY_REGRESSION = "RELIABILITY_REGRESSION"
    TOOL_SELECTION_REGRESSION = "TOOL_SELECTION_REGRESSION"
    ARGUMENT_REGRESSION = "ARGUMENT_REGRESSION"
    CLARIFICATION_REGRESSION = "CLARIFICATION_REGRESSION"
    ERROR_RECOVERY_REGRESSION = "ERROR_RECOVERY_REGRESSION"
    SAFETY_REGRESSION = "SAFETY_REGRESSION"
    COST_REGRESSION = "COST_REGRESSION"
    LATENCY_REGRESSION = "LATENCY_REGRESSION"
    TOOL_CALL_INFLATION = "TOOL_CALL_INFLATION"
    NEW_FAILURE_MODE = "NEW_FAILURE_MODE"
    RESOLVED_FAILURE = "RESOLVED_FAILURE"


class MutationGeneratedBy(StrEnum):
    HUMAN = "HUMAN"
    SYSTEMATIC_EXPERIMENT = "SYSTEMATIC_EXPERIMENT"
    AGENTSEO_OPTIMIZER = "AGENTSEO_OPTIMIZER"


class MutationType(StrEnum):
    TOOL_RENAME = "TOOL_RENAME"
    DESCRIPTION_REDUCTION = "DESCRIPTION_REDUCTION"
    DESCRIPTION_OVERLAP = "DESCRIPTION_OVERLAP"
    NEGATIVE_INSTRUCTION_REMOVAL = "NEGATIVE_INSTRUCTION_REMOVAL"
    PARAMETER_RENAME = "PARAMETER_RENAME"
    PARAMETER_DESCRIPTION_REMOVAL = "PARAMETER_DESCRIPTION_REMOVAL"
    EXAMPLE_REMOVAL = "EXAMPLE_REMOVAL"
    EXAMPLE_ADDITION = "EXAMPLE_ADDITION"
    TOOLSET_EXPANSION = "TOOLSET_EXPANSION"
    TOOL_OVERLAP = "TOOL_OVERLAP"
    DESCRIPTION_ENRICHMENT = "DESCRIPTION_ENRICHMENT"
    TOOLSET_REDUCTION = "TOOLSET_REDUCTION"


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
    experiments: Mapped[list[Experiment]] = relationship(cascade="all, delete-orphan")


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
    name: Mapped[str] = mapped_column(String(200), default="Canonical baseline")
    variant_key: Mapped[str] = mapped_column(String(80), default="baseline")
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)


class InterfaceMutation(Base):
    __tablename__ = "interface_mutations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    interface_version_id: Mapped[str] = mapped_column(
        ForeignKey("interface_versions.id", ondelete="CASCADE")
    )
    parent_interface_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("interface_versions.id")
    )
    mutation_type: Mapped[str] = mapped_column(String(80))
    target_tool_id: Mapped[str | None] = mapped_column(String(200))
    target_field: Mapped[str] = mapped_column(String(200), default="")
    before_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    after_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    generated_by: Mapped[str] = mapped_column(
        String(40), default=MutationGeneratedBy.SYSTEMATIC_EXPERIMENT.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.id"))


class BenchmarkTask(Base):
    __tablename__ = "benchmark_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(250))
    natural_language_instruction: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str] = mapped_column(String(80), default="single_tool")
    task_family: Mapped[str] = mapped_column(String(120), default="unassigned", index=True)
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
    phase15_split: Mapped[str | None] = mapped_column(String(20))


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
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.id"))
    trial_number: Mapped[int] = mapped_column(Integer, default=1)
    task_split: Mapped[str | None] = mapped_column(String(20))

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
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.id"))
    interface_version_id: Mapped[str | None] = mapped_column(ForeignKey("interface_versions.id"))
    model_identifier: Mapped[str] = mapped_column(String(200), default="")
    task_version: Mapped[int] = mapped_column(Integer, default=1)
    trial_number: Mapped[int] = mapped_column(Integer, default=1)
    task_split: Mapped[str | None] = mapped_column(String(20))
    temperature: Mapped[float | None] = mapped_column(Float)
    provider_seed: Mapped[int | None] = mapped_column(Integer)

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


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(250))
    hypothesis: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default=ExperimentStatus.PLANNED.value)
    task_split_seed: Mapped[int] = mapped_column(Integer, default=42)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    models: Mapped[list[str]] = mapped_column(JSON, default=list)
    interface_versions: Mapped[list[str]] = mapped_column(JSON, default=list)
    repetitions: Mapped[int] = mapped_column(Integer, default=3)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    results: Mapped[list[ExperimentResult]] = relationship(cascade="all, delete-orphan")


class ExperimentResult(Base):
    __tablename__ = "experiment_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    result_type: Mapped[str] = mapped_column(String(80), default="AGGREGATE")
    model: Mapped[str | None] = mapped_column(String(200))
    interface_version_id: Mapped[str | None] = mapped_column(ForeignKey("interface_versions.id"))
    task_split: Mapped[str | None] = mapped_column(String(20))
    metric_name: Mapped[str] = mapped_column(String(100))
    metric_value: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    confidence_low: Mapped[float | None] = mapped_column(Float)
    confidence_high: Mapped[float | None] = mapped_column(Float)
    p_value: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CompatibilityRun(Base):
    __tablename__ = "compatibility_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    repository: Mapped[str] = mapped_column(String(300), default="local")
    base_ref: Mapped[str] = mapped_column(String(250), default="baseline")
    candidate_ref: Mapped[str] = mapped_column(String(250), default="candidate")
    base_commit: Mapped[str | None] = mapped_column(String(80))
    candidate_commit: Mapped[str | None] = mapped_column(String(80))
    baseline_interface_version_id: Mapped[str] = mapped_column(ForeignKey("interface_versions.id"))
    candidate_interface_version_id: Mapped[str] = mapped_column(ForeignKey("interface_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default=RunStatus.PENDING.value)
    models: Mapped[list[str]] = mapped_column(JSON, default=list)
    task_suite_id: Mapped[str] = mapped_column(String(300))
    test_selection_strategy: Mapped[str] = mapped_column(String(40), default="FULL_SUITE")
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str | None] = mapped_column(String(30))
    release_classification: Mapped[str | None] = mapped_column(String(40))
    run_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    results: Mapped[list[CompatibilityResult]] = relationship(cascade="all, delete-orphan")


class CompatibilityResult(Base):
    __tablename__ = "compatibility_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    compatibility_run_id: Mapped[str] = mapped_column(
        ForeignKey("compatibility_runs.id", ondelete="CASCADE"), index=True
    )
    model: Mapped[str] = mapped_column(String(200))
    task_id: Mapped[str] = mapped_column(String(36))
    baseline_task_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"))
    candidate_task_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"))
    baseline_success: Mapped[bool] = mapped_column(Boolean)
    candidate_success: Mapped[bool] = mapped_column(Boolean)
    baseline_failure: Mapped[str | None] = mapped_column(String(80))
    candidate_failure: Mapped[str | None] = mapped_column(String(80))
    baseline_tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    candidate_tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    baseline_tokens: Mapped[int] = mapped_column(Integer, default=0)
    candidate_tokens: Mapped[int] = mapped_column(Integer, default=0)
    baseline_latency: Mapped[float] = mapped_column(Float, default=0.0)
    candidate_latency: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_cost: Mapped[float] = mapped_column(Float, default=0.0)
    candidate_cost: Mapped[float] = mapped_column(Float, default=0.0)
    safety_baseline: Mapped[bool] = mapped_column(Boolean, default=True)
    safety_candidate: Mapped[bool] = mapped_column(Boolean, default=True)
    regression_type: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
