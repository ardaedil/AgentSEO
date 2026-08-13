"""Paired behavioral compatibility execution built on the research benchmark engine."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .compatibility_policy import (
    PolicyConfig,
    aggregate_pairs,
    classify_regression,
    evaluate_policy,
)
from .config import Settings
from .contracts import AgenticCompatibilityContract, contract_suite_hash
from .interface_diff import InterfaceDiff, diff_summary, semantic_diff
from .models import (
    BenchmarkTask,
    CompatibilityResult,
    CompatibilityRun,
    FailureCategory,
    InterfaceVersion,
    Project,
    RunStatus,
    TaskRun,
    ToolDefinition,
    TraceEvent,
    now,
)
from .openapi_parser import NormalizedTool, parse_openapi
from .pricing import estimate_usage_cost, pricing_manifest
from .runner import run_benchmark


class CompatibilityConfigurationError(RuntimeError):
    pass


class CompatibilityBudgetError(CompatibilityConfigurationError):
    pass


@dataclass(frozen=True, slots=True)
class CompatibilityConfiguration:
    models: tuple[str, ...]
    selection_strategy: str = "FULL_SUITE"
    max_cost_usd: float = 1.0
    max_tasks: int = 100
    max_concurrency: int = 1
    fail_on_warning: bool = False
    repository: str = "local"
    base_ref: str = "baseline"
    candidate_ref: str = "candidate"
    base_commit: str | None = None
    candidate_commit: str | None = None
    repetitions: int = 1

    def __post_init__(self) -> None:
        if self.selection_strategy not in {"FULL_SUITE", "AFFECTED_ONLY"}:
            raise ValueError("selection_strategy must be FULL_SUITE or AFFECTED_ONLY")
        if not self.models or self.max_cost_usd < 0 or self.max_tasks < 1:
            raise ValueError("models, max_cost_usd, and max_tasks must define a runnable check")
        if self.repetitions != 1:
            raise ValueError("Phase 2A compatibility CI supports exactly one paired trial")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def interface_hash(tools: list[NormalizedTool]) -> str:
    return sha256_json([tool.to_dict() for tool in sorted(tools, key=lambda item: item.name)])


def _git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def estimate_compatibility_cost(
    models: tuple[str, ...], task_count: int, repetitions: int = 1
) -> dict[str, Any]:
    # Conservative preflight assumption: 2,500 input + 350 output tokens per task/side.
    by_model = {
        model: 2
        * task_count
        * repetitions
        * estimate_usage_cost(model, input_tokens=2500, output_tokens=350)
        for model in models
        if not model.startswith("mock:")
    }
    estimate = sum(by_model.values())
    return {
        "estimated_cost_usd": estimate,
        "guarded_estimate_usd": estimate * 1.25,
        "by_model": by_model,
        "assumption": "2500 input and 350 output tokens per task/interface observation",
    }


def _candidate_snapshot(
    baseline: list[NormalizedTool], candidate: list[NormalizedTool]
) -> list[dict[str, Any]]:
    canonical_by_endpoint = {(tool.http_method, tool.path): tool.operation_id for tool in baseline}
    snapshot: list[dict[str, Any]] = []
    for tool in candidate:
        value = tool.to_dict()
        canonical = canonical_by_endpoint.get((tool.http_method, tool.path), tool.operation_id)
        metadata = dict(value.get("tool_metadata", {}))
        metadata["canonical_operation_id"] = canonical
        value["tool_metadata"] = metadata
        snapshot.append(value)
    return snapshot


def select_contracts(
    contracts: list[AgenticCompatibilityContract],
    changes: list[InterfaceDiff],
    strategy: str,
) -> list[AgenticCompatibilityContract]:
    if strategy == "FULL_SUITE":
        return contracts
    summary = diff_summary(changes)
    affected = set(summary["affected_tools"]) | set(summary["affected_capabilities"])
    selected = [
        contract
        for contract in contracts
        if affected.intersection(contract.related_tools)
        or affected.intersection(contract.capabilities)
    ]
    return selected or contracts


def _contract_task(project_id: str, contract: AgenticCompatibilityContract) -> BenchmarkTask:
    state = dict(contract.resolved_initial_state())
    state["_evaluation"] = {
        "evaluator_version": contract.evaluator_version,
        "expected_max_tool_calls": contract.budgets.max_tool_calls,
    }
    return BenchmarkTask(
        project_id=project_id,
        title=contract.name,
        natural_language_instruction=contract.intent,
        difficulty={"low": 1, "medium": 3, "high": 5, "critical": 7}[contract.risk_level],
        category=contract.categories[0],
        task_family=contract.capabilities[0],
        required_tools=contract.required_actions,
        forbidden_tools=contract.forbidden_actions,
        initial_state=state,
        expected_final_state=[item.evaluator_assertion() for item in contract.assertions],
        expected_invariants=[item.evaluator_assertion() for item in contract.invariants],
        requires_clarification=contract.behavior.clarification == "required",
        safety_level=contract.risk_level,
        generated_or_manual="contract",
        enabled=True,
        version=1,
    )


def _tool_call_count(session: Session, task_run_id: str) -> int:
    return len(
        list(
            session.scalars(
                select(TraceEvent.id).where(
                    TraceEvent.task_run_id == task_run_id,
                    TraceEvent.event_type == "TOOL_CALLED",
                )
            )
        )
    )


def _selected_tools(session: Session, task_run_id: str) -> list[str]:
    events = session.scalars(
        select(TraceEvent)
        .where(
            TraceEvent.task_run_id == task_run_id,
            TraceEvent.event_type == "TOOL_CALLED",
        )
        .order_by(TraceEvent.sequence)
    )
    selected: list[str] = []
    for event in events:
        agent = str(event.payload.get("agent_tool", "unknown"))
        canonical = str(event.payload.get("canonical_tool", agent))
        selected.append(agent if agent == canonical else f"{agent} -> {canonical}")
    return selected


def _tokens(run: TaskRun) -> int:
    return sum(int(value) for value in (run.token_usage or {}).values())


def _safe(run: TaskRun) -> bool:
    return run.failure_category not in {
        FailureCategory.DESTRUCTIVE_ACTION_ERROR.value,
        FailureCategory.FAILED_TO_REFUSE.value,
        FailureCategory.AUTHORIZATION_ERROR.value,
    }


def _pair(
    session: Session,
    model: str,
    task: BenchmarkTask,
    baseline: TaskRun,
    candidate: TaskRun,
    contract: AgenticCompatibilityContract,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "model": model,
        "task_id": task.id,
        "task_name": contract.name,
        "risk_level": contract.risk_level,
        "baseline_task_run_id": baseline.id,
        "candidate_task_run_id": candidate.id,
        "baseline_success": baseline.success,
        "candidate_success": candidate.success,
        "baseline_failure": baseline.failure_category,
        "candidate_failure": candidate.failure_category,
        "baseline_tool_calls": _tool_call_count(session, baseline.id),
        "candidate_tool_calls": _tool_call_count(session, candidate.id),
        "baseline_tokens": _tokens(baseline),
        "candidate_tokens": _tokens(candidate),
        "baseline_latency": baseline.duration,
        "candidate_latency": candidate.duration,
        "baseline_cost": baseline.cost_estimate,
        "candidate_cost": candidate.cost_estimate,
        "safety_baseline": _safe(baseline),
        "safety_candidate": _safe(candidate),
        "baseline_evaluator": baseline.evaluator_result,
        "candidate_evaluator": candidate.evaluator_result,
        "baseline_selected_tools": _selected_tools(session, baseline.id),
        "candidate_selected_tools": _selected_tools(session, candidate.id),
        "is_multi_step": len(contract.required_actions) > 1,
        "is_clarification": contract.behavior.clarification == "required",
        "is_error_recovery": "error_recovery" in contract.categories,
        "baseline_multi_step_success": baseline.success,
        "candidate_multi_step_success": candidate.success,
    }
    value["regression_type"] = classify_regression(value)
    return value


def _persist_result(run_id: str, pair: dict[str, Any]) -> CompatibilityResult:
    stored = {
        key: pair[key]
        for key in (
            "model",
            "task_id",
            "baseline_task_run_id",
            "candidate_task_run_id",
            "baseline_success",
            "candidate_success",
            "baseline_failure",
            "candidate_failure",
            "baseline_tool_calls",
            "candidate_tool_calls",
            "baseline_tokens",
            "candidate_tokens",
            "baseline_latency",
            "candidate_latency",
            "baseline_cost",
            "candidate_cost",
            "safety_baseline",
            "safety_candidate",
            "regression_type",
        )
    }
    details = {
        key: value
        for key, value in pair.items()
        if key not in stored and key not in {"baseline_evaluator", "candidate_evaluator"}
    }
    details["baseline_evaluator"] = pair["baseline_evaluator"]
    details["candidate_evaluator"] = pair["candidate_evaluator"]
    return CompatibilityResult(compatibility_run_id=run_id, details=details, **stored)


def _interface_version(
    project_id: str,
    name: str,
    key: str,
    snapshot: list[dict[str, Any]],
    parent: InterfaceVersion | None = None,
) -> InterfaceVersion:
    return InterfaceVersion(
        project_id=project_id,
        version=1 if parent is None else 2,
        parent_version_id=parent.id if parent else None,
        tool_definitions_snapshot=snapshot,
        change_description="Compatibility CI baseline"
        if parent is None
        else "Pull request candidate",
        name=name,
        variant_key=key,
        frozen=True,
    )


async def run_compatibility(
    session: Session,
    baseline_content: bytes,
    candidate_content: bytes,
    contracts: list[AgenticCompatibilityContract],
    configuration: CompatibilityConfiguration,
    settings: Settings,
) -> CompatibilityRun:
    baseline_document, baseline_tools = parse_openapi(baseline_content)
    candidate_document, candidate_tools = parse_openapi(candidate_content)
    changes = semantic_diff(baseline_tools, candidate_tools)
    selected = select_contracts(contracts, changes, configuration.selection_strategy)
    if len(selected) > min(configuration.max_tasks, settings.agentseo_max_tasks):
        raise CompatibilityConfigurationError("Selected contracts exceed AGENTSEO_MAX_TASKS")
    estimate = estimate_compatibility_cost(configuration.models, len(selected))
    cost_limit = min(configuration.max_cost_usd, settings.agentseo_max_cost_usd)
    if estimate["guarded_estimate_usd"] > cost_limit:
        raise CompatibilityBudgetError(
            f"Guarded estimate ${estimate['guarded_estimate_usd']:.4f} exceeds ${cost_limit:.4f} limit"
        )
    project = Project(
        name=f"Compatibility: {configuration.repository}",
        description="Paired baseline/candidate behavioral compatibility run",
        sandbox_domain=str(baseline_document.get("x-agentseo-sandbox", "billing")),
    )
    session.add(project)
    session.flush()
    session.add_all(
        [ToolDefinition(project_id=project.id, **tool.to_dict()) for tool in baseline_tools]
    )
    baseline_interface = _interface_version(
        project.id,
        "Compatibility baseline",
        "compatibility_baseline",
        [tool.to_dict() for tool in baseline_tools],
    )
    session.add(baseline_interface)
    session.flush()
    candidate_interface = _interface_version(
        project.id,
        "Compatibility candidate",
        "compatibility_candidate",
        _candidate_snapshot(baseline_tools, candidate_tools),
        baseline_interface,
    )
    session.add(candidate_interface)
    tasks = [_contract_task(project.id, contract) for contract in selected]
    session.add_all(tasks)
    session.flush()
    suite_hash = contract_suite_hash(selected)
    compatibility_run = CompatibilityRun(
        repository=configuration.repository,
        base_ref=configuration.base_ref,
        candidate_ref=configuration.candidate_ref,
        base_commit=configuration.base_commit,
        candidate_commit=configuration.candidate_commit or _git_commit(),
        baseline_interface_version_id=baseline_interface.id,
        candidate_interface_version_id=candidate_interface.id,
        status=RunStatus.RUNNING.value,
        models=list(configuration.models),
        task_suite_id=suite_hash,
        test_selection_strategy=configuration.selection_strategy,
        estimated_cost=float(estimate["guarded_estimate_usd"]),
        run_metadata={
            "mode": "MOCK VALIDATION"
            if all(m.startswith("mock:") for m in configuration.models)
            else "REAL AGENT COMPATIBILITY",
            "interface_diff": [change.to_dict() for change in changes],
            "interface_diff_summary": diff_summary(changes),
            "baseline_interface_hash": interface_hash(baseline_tools),
            "candidate_interface_hash": interface_hash(candidate_tools),
            "task_suite_hash": suite_hash,
            "contract_hashes": {contract.name: contract.sha256() for contract in selected},
            "model_ids": list(configuration.models),
            "provider_configuration": {"temperature": 0.0, "seed": None},
            "software": {"python": platform.python_version(), "agentseo": "0.2.0"},
            "trial_configuration": {"repetitions": 1, "paired": True},
            "cost_estimate": estimate,
            "pricing": pricing_manifest(list(configuration.models)),
        },
    )
    session.add(compatibility_run)
    session.commit()
    pairs: list[dict[str, Any]] = []
    run_configuration = {
        "compatibility_run_id": compatibility_run.id,
        "max_iterations": settings.max_iterations,
        "max_tool_calls": settings.max_tool_calls,
        "timeout_seconds": settings.run_timeout_seconds,
        "temperature": 0.0,
        "provider_seed": None,
    }
    try:
        for model in configuration.models:
            baseline_run = await run_benchmark(
                session, project, model, tasks, run_configuration, settings, baseline_interface
            )
            spent = sum(pair["baseline_cost"] + pair["candidate_cost"] for pair in pairs)
            spent += float(baseline_run.aggregate_metrics.get("estimated_cost", 0))
            if spent > cost_limit:
                raise CompatibilityBudgetError("Actual baseline spend reached the configured limit")
            candidate_run = await run_benchmark(
                session, project, model, tasks, run_configuration, settings, candidate_interface
            )
            baseline_rows = {
                row.task_id: row
                for row in session.scalars(
                    select(TaskRun).where(TaskRun.benchmark_run_id == baseline_run.id)
                )
            }
            candidate_rows = {
                row.task_id: row
                for row in session.scalars(
                    select(TaskRun).where(TaskRun.benchmark_run_id == candidate_run.id)
                )
            }
            for task, contract in zip(tasks, selected, strict=True):
                pair = _pair(
                    session, model, task, baseline_rows[task.id], candidate_rows[task.id], contract
                )
                pairs.append(pair)
                session.add(_persist_result(compatibility_run.id, pair))
            session.commit()
        per_model = {
            model: aggregate_pairs([pair for pair in pairs if pair["model"] == model])
            for model in configuration.models
        }
        pooled = aggregate_pairs(pairs)
        policy = evaluate_policy(
            pooled, pairs, PolicyConfig(fail_on_warning=configuration.fail_on_warning)
        )
        compatibility_run.actual_cost = sum(
            float(pair["baseline_cost"]) + float(pair["candidate_cost"]) for pair in pairs
        )
        compatibility_run.verdict = policy["verdict"]
        compatibility_run.release_classification = policy["classification"]
        compatibility_run.status = RunStatus.COMPLETED.value
        compatibility_run.completed_at = now()
        metadata = dict(compatibility_run.run_metadata)
        metadata.update({"metrics": {"per_model": per_model, "pooled": pooled}, "policy": policy})
        compatibility_run.run_metadata = metadata
        session.commit()
        return compatibility_run
    except Exception:
        compatibility_run.status = RunStatus.FAILED.value
        compatibility_run.completed_at = now()
        session.commit()
        raise


def validate_baseline_compatibility(
    baseline: dict[str, Any], *, models: list[str], task_suite_hash: str, evaluator_hash: str
) -> list[str]:
    warnings: list[str] = []
    if baseline.get("model_ids") != models:
        warnings.append("MODEL_CHANGED")
    if baseline.get("task_suite_hash") != task_suite_hash:
        warnings.append("TASK_SUITE_CHANGED")
    if baseline.get("evaluator_hash") != evaluator_hash:
        warnings.append("EVALUATOR_CHANGED")
    return warnings


def save_filesystem_baseline(run: CompatibilityRun, path: Path) -> None:
    payload = {
        "schema_version": "1.0",
        "interface_hash": run.run_metadata["candidate_interface_hash"],
        "model_ids": run.models,
        "task_suite_hash": run.run_metadata["task_suite_hash"],
        "contract_hashes": run.run_metadata["contract_hashes"],
        "evaluator_hash": sha256_json(run.run_metadata["contract_hashes"]),
        "metrics": run.run_metadata["metrics"],
        "timestamp": run.completed_at.isoformat() if run.completed_at else None,
        "git_commit": run.candidate_commit,
        "compatibility_run_id": run.id,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def compatibility_report(run: CompatibilityRun, results: list[CompatibilityResult]) -> str:
    metadata = run.run_metadata
    metrics = metadata.get("metrics", {})
    diff = metadata.get("interface_diff_summary", {})
    lines = [
        "## AgentSEO Compatibility",
        "",
        f"> {metadata.get('mode', 'REAL AGENT COMPATIBILITY')}",
        "",
        "### Interface changes",
        "",
    ]
    if diff.get("by_type"):
        lines.extend(f"- {count} x {kind}" for kind, count in diff["by_type"].items())
    else:
        lines.append("- No semantic interface changes detected")
    lines.extend(["", "### Changed tool behaviors", ""])
    for change in metadata.get("interface_diff", []):
        lines.append(
            f"- **{change['tool']}** `{change['change_type']}` ({change['risk_level']}): "
            f"`{change['field']}`"
        )
    if not metadata.get("interface_diff"):
        lines.append("- None")
    lines.extend(
        [
            "",
            "### Compatibility",
            "",
            "| Model | Base | PR | Delta | Safety delta | Tokens delta | Latency delta | Cost delta |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for model, row in metrics.get("per_model", {}).items():
        base, candidate, delta = row["baseline"], row["candidate"], row["delta"]
        lines.append(
            f"| {model} | {base['task_success_rate']:.1%} | {candidate['task_success_rate']:.1%} | "
            f"{delta['reliability']:+.1%} | {delta['safety']:+.1%} | {delta['tokens']:+.0f} | "
            f"{delta['latency']:+.2f}s | ${delta['cost']:+.4f} |"
        )
    regressions = [
        result
        for result in results
        if result.regression_type and result.regression_type != "RESOLVED_FAILURE"
    ]
    lines.extend(["", "### Regressions", ""])
    if regressions:
        for result in regressions:
            observed = ", ".join(result.details.get("candidate_selected_tools", [])) or "none"
            lines.extend(
                [
                    f"- **{result.details.get('task_name', result.task_id)}** ({result.model}): "
                    f"{result.regression_type}; baseline={result.baseline_failure or 'PASS'}, "
                    f"candidate={result.candidate_failure or 'PASS'}; candidate tools={observed}",
                ]
            )
    else:
        lines.append("- No behavioral regressions detected.")
    baseline_failures = {result.baseline_failure for result in results if result.baseline_failure}
    candidate_failures = {
        result.candidate_failure for result in results if result.candidate_failure
    }
    new_failures = sorted(candidate_failures - baseline_failures)
    safety_regressions = [
        result for result in results if result.safety_baseline and not result.safety_candidate
    ]
    lines.extend(["", "### New failure categories", ""])
    lines.append(f"- {', '.join(new_failures)}" if new_failures else "- None")
    lines.extend(["", "### Safety regressions", ""])
    if safety_regressions:
        lines.extend(
            f"- {result.details.get('task_name', result.task_id)} ({result.model})"
            for result in safety_regressions
        )
    else:
        lines.append("- None")
    policy = metadata.get("policy", {})
    lines.extend(["", "### Policy rules", ""])
    lines.extend(
        f"- **{rule['level']} - {rule['rule']}**: {rule['explanation']}"
        for rule in policy.get("fired_rules", [])
    )
    if not policy.get("fired_rules"):
        lines.append("- No policy rules fired.")
    lines.extend(
        [
            "",
            "### Verdict",
            "",
            f"**{run.release_classification}** - AGENT COMPATIBILITY: **{run.verdict}**",
            "",
            f"Estimated: ${run.estimated_cost:.4f}; actual: ${run.actual_cost:.4f}",
            "",
            f"Run ID: `{run.id}`",
            "",
            "### Reproducibility",
            "",
            f"- Base commit: `{run.base_commit or 'unavailable'}`",
            f"- Candidate commit: `{run.candidate_commit or 'unavailable'}`",
            f"- Baseline interface: `{metadata.get('baseline_interface_hash', 'unavailable')}`",
            f"- Candidate interface: `{metadata.get('candidate_interface_hash', 'unavailable')}`",
            f"- Task suite: `{metadata.get('task_suite_hash', 'unavailable')}`",
            f"- Models: {', '.join(run.models)}",
        ]
    )
    return "\n".join(lines) + "\n"
