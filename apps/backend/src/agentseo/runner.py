from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .evaluation import calculate_metrics, classify_failure, evaluate_task
from .interfaces import tools_for_task, translate_tool_call
from .models import (
    BenchmarkRun,
    BenchmarkTask,
    InterfaceVersion,
    Project,
    RunStatus,
    TaskRun,
    ToolDefinition,
    TraceEvent,
    now,
)
from .openapi_parser import NormalizedTool
from .providers import AgentProvider, create_provider
from .sandboxes import SandboxError, create_sandbox

log = structlog.get_logger()


def _tool(model: ToolDefinition) -> NormalizedTool:
    return NormalizedTool(
        name=model.name,
        operation_id=model.operation_id,
        http_method=model.http_method,
        path=model.path,
        description=model.description,
        parameters=model.parameters,
        request_schema=model.request_schema,
        response_schema=model.response_schema,
        tags=model.tags,
        is_destructive=model.is_destructive,
        inferred_destructive=model.inferred_destructive,
        requires_authentication=model.requires_authentication,
        tool_metadata=model.tool_metadata,
    )


def _trace(
    session: Session, task_run: TaskRun, sequence: int, event_type: str, payload: dict[str, Any]
) -> None:
    session.add(
        TraceEvent(
            task_run_id=task_run.id, sequence=sequence, event_type=event_type, payload=payload
        )
    )


async def execute_task(
    session: Session,
    benchmark_run: BenchmarkRun,
    task: BenchmarkTask,
    tools: list[NormalizedTool],
    provider: AgentProvider,
    settings: Settings,
    interface: InterfaceVersion | None = None,
) -> dict[str, Any]:
    task_run = TaskRun(
        task_id=task.id,
        benchmark_run_id=benchmark_run.id,
        status=RunStatus.RUNNING.value,
        experiment_id=benchmark_run.experiment_id,
        interface_version_id=benchmark_run.interface_version_id,
        model_identifier=f"{benchmark_run.provider}:{benchmark_run.model}",
        task_version=task.version,
        trial_number=benchmark_run.trial_number,
        task_split=benchmark_run.task_split or task.phase15_split,
        temperature=benchmark_run.configuration.get("temperature"),
        provider_seed=benchmark_run.configuration.get("provider_seed"),
    )
    session.add(task_run)
    session.flush()
    sequence = 0
    _trace(
        session,
        task_run,
        sequence,
        "MODEL_MESSAGE",
        {"role": "user", "content": task.natural_language_instruction},
    )
    sandbox = create_sandbox(session.get(Project, benchmark_run.project_id).sandbox_domain)  # type: ignore[union-attr]
    before = sandbox.reset(task.initial_state or None)
    history: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    clarified = False
    max_iterations_hit = False
    model_refused = False
    total_tokens = {"input": 0, "output": 0}
    started = time.perf_counter()
    max_iterations = int(benchmark_run.configuration.get("max_iterations", settings.max_iterations))
    max_tool_calls = int(benchmark_run.configuration.get("max_tool_calls", settings.max_tool_calls))
    log.info("task_started", run_id=benchmark_run.id, task_id=task.id, model=benchmark_run.model)

    async def loop() -> None:
        nonlocal sequence, clarified, max_iterations_hit, model_refused
        for _iteration in range(max_iterations):
            context = {
                "required_tools": task.required_tools,
                "forbidden_tools": task.forbidden_tools,
                "requires_clarification": task.requires_clarification,
                "difficulty": task.difficulty,
                "category": task.category,
                "temperature": benchmark_run.configuration.get("temperature"),
                "seed": benchmark_run.configuration.get("provider_seed"),
            }
            action = await provider.next_action(
                task.natural_language_instruction, tools, history, context
            )
            for key, value in (action.token_usage or {}).items():
                total_tokens[key] = total_tokens.get(key, 0) + value
            sequence += 1
            if action.kind == "clarification":
                clarified = True
                _trace(session, task_run, sequence, "CLARIFICATION", {"content": action.content})
                return
            if action.kind == "final":
                model_refused = any(
                    term in action.content.lower()
                    for term in ("cannot help", "can't help", "refuse")
                )
                _trace(session, task_run, sequence, "FINAL_RESPONSE", {"content": action.content})
                return
            if action.kind != "tool_call" or not action.tool:
                _trace(session, task_run, sequence, "ERROR", {"message": "Invalid provider action"})
                return
            if len(calls) >= max_tool_calls:
                max_iterations_hit = True
                _trace(
                    session, task_run, sequence, "ERROR", {"message": "Maximum tool calls reached"}
                )
                return
            agent_tool = action.tool
            agent_arguments = action.arguments or {}
            canonical_tool, arguments = (
                translate_tool_call(interface, agent_tool, agent_arguments)
                if interface
                else (agent_tool, agent_arguments)
            )
            _trace(
                session,
                task_run,
                sequence,
                "TOOL_SELECTED",
                {"agent_tool": agent_tool, "canonical_tool": canonical_tool},
            )
            sequence += 1
            _trace(
                session,
                task_run,
                sequence,
                "TOOL_CALLED",
                {
                    "agent_tool": agent_tool,
                    "canonical_tool": canonical_tool,
                    "agent_arguments": agent_arguments,
                    "canonical_arguments": arguments,
                },
            )
            call_record: dict[str, Any] = {
                "tool": canonical_tool,
                "agent_tool": agent_tool,
                "arguments": arguments,
                "agent_arguments": agent_arguments,
            }
            try:
                result = sandbox.execute(canonical_tool, arguments)
                call_record["result"] = result
                history.append(
                    {
                        "type": "tool_result",
                        "tool": agent_tool,
                        "canonical_tool": canonical_tool,
                        "arguments": arguments,
                        "result": result,
                    }
                )
                sequence += 1
                _trace(
                    session,
                    task_run,
                    sequence,
                    "TOOL_RESULT",
                    {"tool": agent_tool, "canonical_tool": canonical_tool, "result": result},
                )
                log.info("tool_call", run_id=benchmark_run.id, task_id=task.id, tool=canonical_tool)
            except SandboxError as exc:
                call_record["error_code"] = exc.code
                call_record["error"] = str(exc)
                history.append(
                    {
                        "type": "tool_result",
                        "tool": agent_tool,
                        "canonical_tool": canonical_tool,
                        "error_code": exc.code,
                        "error": str(exc),
                    }
                )
                sequence += 1
                _trace(
                    session,
                    task_run,
                    sequence,
                    "ERROR",
                    {
                        "tool": agent_tool,
                        "canonical_tool": canonical_tool,
                        "code": exc.code,
                        "message": str(exc),
                    },
                )
            calls.append(call_record)
        max_iterations_hit = True

    try:
        timeout = float(
            benchmark_run.configuration.get("timeout_seconds", settings.run_timeout_seconds)
        )
        await asyncio.wait_for(loop(), timeout=timeout)
    except TimeoutError:
        max_iterations_hit = True
        sequence += 1
        _trace(session, task_run, sequence, "ERROR", {"message": "Task execution timed out"})

    after = sandbox.snapshot()
    evaluation = evaluate_task(
        before,
        after,
        task.expected_final_state,
        task.expected_invariants,
        task.requires_clarification,
        clarified,
    )
    selected = [call["tool"] for call in calls]
    required_ok = all(tool in selected for tool in task.required_tools)
    forbidden_ok = all(tool not in selected for tool in task.forbidden_tools)
    if task.requires_clarification:
        required_ok = clarified
    evaluation["tool_requirements_passed"] = required_ok
    evaluation["forbidden_tools_avoided"] = forbidden_ok
    recovered = True
    if task.category == "error_recovery":
        error_positions = [index for index, call in enumerate(calls) if call.get("error_code")]
        recovered = bool(error_positions) and any(
            index > error_positions[0] and "result" in call for index, call in enumerate(calls)
        )
        evaluation["error_recovery_passed"] = recovered
    evaluation["passed"] = evaluation["passed"] and required_ok and forbidden_ok
    evaluation["passed"] = evaluation["passed"] and recovered
    known_tools = {tool.name for tool in tools}
    failure_category, failure_explanation = classify_failure(
        evaluator_result=evaluation,
        required_tools=task.required_tools,
        forbidden_tools=task.forbidden_tools,
        calls=calls,
        known_tools=known_tools,
        max_iterations_hit=max_iterations_hit,
        model_refused=model_refused,
    )
    duration = time.perf_counter() - started
    estimated_cost = (
        0.0
        if provider.name == "mock"
        else (total_tokens.get("input", 0) * 0.0000005)
        + (total_tokens.get("output", 0) * 0.0000015)
    )
    task_run.status = RunStatus.COMPLETED.value
    task_run.success = bool(evaluation["passed"])
    task_run.duration = duration
    task_run.token_usage = total_tokens
    task_run.cost_estimate = estimated_cost
    task_run.failure_category = failure_category
    task_run.failure_explanation = failure_explanation
    task_run.evaluator_result = evaluation
    session.flush()
    log.info(
        "task_result",
        run_id=benchmark_run.id,
        task_id=task.id,
        success=task_run.success,
        failure_category=failure_category,
    )
    return {
        "success": task_run.success,
        "difficulty": task.difficulty,
        "category": task.category,
        "tool_selection_correct": required_ok and forbidden_ok,
        "argument_correct": recovered
        if task.category == "error_recovery"
        else not any(call.get("error_code") == "VALIDATION_ERROR" for call in calls),
        "tool_calls": len(calls),
        "duration": duration,
        "cost_estimate": estimated_cost,
        "token_usage": total_tokens,
        "failure_category": failure_category,
    }


async def run_benchmark(
    session: Session,
    project: Project,
    model_identifier: str,
    tasks: list[BenchmarkTask],
    configuration: dict[str, Any],
    settings: Settings,
    interface_version: InterfaceVersion | None = None,
    experiment_id: str | None = None,
    trial_number: int = 1,
    task_split: str | None = None,
) -> BenchmarkRun:
    provider = create_provider(model_identifier, settings)
    interface = interface_version or session.scalar(
        select(InterfaceVersion)
        .where(
            InterfaceVersion.project_id == project.id,
            InterfaceVersion.variant_key == "baseline",
        )
        .order_by(InterfaceVersion.version.asc())
    )
    run = BenchmarkRun(
        project_id=project.id,
        interface_version_id=interface.id if interface else None,
        model=provider.model,
        provider=provider.name,
        status=RunStatus.RUNNING.value,
        started_at=now(),
        configuration={**configuration, "task_versions": {task.id: task.version for task in tasks}},
        synthetic=provider.name == "mock",
        experiment_id=experiment_id,
        trial_number=trial_number,
        task_split=task_split,
    )
    session.add(run)
    session.flush()
    log.info(
        "run_started",
        run_id=run.id,
        project_id=project.id,
        model=model_identifier,
        task_count=len(tasks),
    )
    canonical_tools = [
        _tool(tool)
        for tool in session.scalars(
            select(ToolDefinition).where(ToolDefinition.project_id == project.id)
        ).all()
    ]
    results: list[dict[str, Any]] = []
    try:
        for task in tasks:
            task_tools = (
                tools_for_task(interface, task.required_tools, task.forbidden_tools)
                if interface
                else canonical_tools
            )
            results.append(
                await execute_task(
                    session, run, task, task_tools, provider, settings, interface=interface
                )
            )
        run.aggregate_metrics = calculate_metrics(results)
        run.status = RunStatus.COMPLETED.value
    except Exception:
        run.status = RunStatus.FAILED.value
        log.exception("run_failed", run_id=run.id)
        raise
    finally:
        run.completed_at = now()
        session.commit()
    log.info("run_completed", run_id=run.id, score=run.aggregate_metrics.get("compatibility_score"))
    return run
