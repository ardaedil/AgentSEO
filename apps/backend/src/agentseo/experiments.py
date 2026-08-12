from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import Settings
from .database import SessionLocal
from .interfaces import create_phase15_variants
from .models import (
    BenchmarkRun,
    BenchmarkTask,
    Experiment,
    ExperimentResult,
    ExperimentStatus,
    InterfaceVersion,
    Project,
    TaskRun,
    now,
)
from .reporting import generate_report
from .research_export import experiment_observations, export_experiment_dataset
from .runner import run_benchmark
from .statistics import flag_model_specific_effects, paired_binary_comparison

DEFAULT_VARIANTS = [
    "baseline",
    "degraded",
    "optimized",
    "concise",
    "verbose",
    "negative",
    "examples",
]
ATTRIBUTION_VARIANTS = [
    "isolated_tool_rename",
    "isolated_description_reduction",
    "isolated_parameter_rename",
    "isolated_negative_removal",
]
REAL_PROVIDERS = {"openai", "anthropic", "google", "gemini"}


@dataclass(slots=True)
class Phase15Configuration:
    models: list[str]
    variants: list[str]
    repetitions: int = 3
    split_seed: int = 42
    temperature: float = 0.0
    max_cost_usd: float = 5.0
    max_concurrency: int = 2
    bootstrap_samples: int = 2000
    estimated_input_tokens: int = 1500
    estimated_output_tokens: int = 300
    estimated_model_calls_per_task: int = 4
    unavailable_providers: list[str] | None = None

    def validate(self) -> None:
        if not self.models:
            raise ValueError("At least one configured model is required")
        if not self.variants or "baseline" not in self.variants:
            raise ValueError("The experiment matrix must include the baseline variant")
        if not 1 <= self.repetitions <= 20:
            raise ValueError("Repetitions must be between 1 and 20")
        if not 1 <= self.max_concurrency <= 16:
            raise ValueError("Concurrency must be between 1 and 16")
        if self.max_cost_usd < 0:
            raise ValueError("Cost cap cannot be negative")
        if not 0 <= self.temperature <= 2:
            raise ValueError("Temperature must be between 0 and 2")


@dataclass(slots=True)
class ExperimentCell:
    project_id: str
    interface_id: str
    model: str
    task_ids: list[str]
    split: str
    trial: int
    label: str


def resolve_models(requested: list[str] | None, settings: Settings) -> tuple[list[str], list[str]]:
    defaults = {
        "openai": settings.openai_model,
        "anthropic": settings.anthropic_model,
        "google": settings.gemini_model,
        "gemini": settings.gemini_model,
    }
    configured = {
        "openai": bool(settings.openai_api_key),
        "anthropic": bool(settings.anthropic_api_key),
        "google": bool(settings.google_api_key),
        "gemini": bool(settings.google_api_key),
    }
    requested = requested or ["openai", "anthropic", "google"]
    resolved: list[str] = []
    unavailable: list[str] = []
    for identifier in requested:
        provider, separator, model = identifier.partition(":")
        provider = provider.lower()
        if provider == "mock":
            resolved.append(f"mock:{model or 'reliable'}")
            continue
        if provider not in REAL_PROVIDERS:
            unavailable.append(f"{identifier} (unknown provider)")
            continue
        if not configured[provider]:
            unavailable.append(f"{provider} (API key unavailable)")
            continue
        exact_model = model if separator and model else defaults[provider]
        canonical_provider = "google" if provider == "gemini" else provider
        resolved.append(f"{canonical_provider}:{exact_model}")
    return list(dict.fromkeys(resolved)), unavailable


def assign_task_split(tasks: list[BenchmarkTask], seed: int) -> dict[str, str]:
    """Create and persist a deterministic 70/30 development/hidden split."""

    result: dict[str, str] = {}
    for task in tasks:
        identity = f"{seed}:{task.title}:{task.natural_language_instruction}".encode()
        bucket = int(hashlib.sha256(identity).hexdigest()[:8], 16) % 100
        task.phase15_split = "development" if bucket < 70 else "hidden"
        result[task.id] = task.phase15_split
    # Very small custom suites still need both groups when there is more than one task.
    if len(tasks) > 1 and len(set(result.values())) == 1:
        ordered = sorted(tasks, key=lambda item: item.id)
        ordered[-1].phase15_split = "hidden"
        result[ordered[-1].id] = "hidden"
    return result


def _price_per_million(identifier: str) -> tuple[float, float]:
    provider = identifier.partition(":")[0]
    # Conservative planning rates, intentionally above low-cost aliases. Actual cost
    # is recorded from provider token usage and can be recalculated externally.
    return {
        "openai": (3.0, 12.0),
        "anthropic": (4.0, 20.0),
        "google": (1.0, 5.0),
        "mock": (0.0, 0.0),
    }.get(provider, (10.0, 30.0))


def estimate_experiment_cost(
    task_count: int, configuration: Phase15Configuration
) -> dict[str, Any]:
    agent_tasks = (
        task_count
        * len(configuration.models)
        * len(configuration.variants)
        * configuration.repetitions
    )
    model_costs: dict[str, float] = {}
    for model in configuration.models:
        input_rate, output_rate = _price_per_million(model)
        per_call = (
            configuration.estimated_input_tokens * input_rate
            + configuration.estimated_output_tokens * output_rate
        ) / 1_000_000
        model_costs[model] = (
            per_call * task_count * len(configuration.variants) * configuration.repetitions
        )
    subtotal = sum(model_costs.values())
    return {
        "task_count": task_count,
        "models": len(configuration.models),
        "variants": len(configuration.variants),
        "repetitions": configuration.repetitions,
        "expected_agent_tasks": agent_tasks,
        "expected_provider_calls": agent_tasks * configuration.estimated_model_calls_per_task,
        "estimated_input_tokens_per_task": configuration.estimated_input_tokens,
        "estimated_output_tokens_per_task": configuration.estimated_output_tokens,
        "model_costs": model_costs,
        "subtotal_usd": subtotal,
        "guarded_estimate_usd": subtotal * 1.25,
        "safety_buffer": 0.25,
    }


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def create_manifest(
    experiment: Experiment,
    tasks: list[BenchmarkTask],
    interfaces: list[InterfaceVersion],
) -> dict[str, Any]:
    return {
        "experiment_id": experiment.id,
        "git_commit": _git_commit(),
        "model_ids": experiment.models,
        "interface_versions": [
            {
                "id": interface.id,
                "project_id": interface.project_id,
                "variant": interface.variant_key,
                "version": interface.version,
                "frozen": interface.frozen,
            }
            for interface in interfaces
        ],
        "task_ids": [
            {
                "id": task.id,
                "stable_key": hashlib.sha256(
                    f"{task.title}:{task.natural_language_instruction}".encode()
                ).hexdigest()[:16],
                "title": task.title,
                "version": task.version,
                "split": task.phase15_split,
                "project_id": task.project_id,
            }
            for task in tasks
        ],
        "task_split_seed": experiment.task_split_seed,
        "repetitions": experiment.repetitions,
        "temperatures": {
            model: experiment.configuration.get("temperature") for model in experiment.models
        },
        "provider_seeds": {
            model: experiment.configuration.get("provider_seed") for model in experiment.models
        },
        "started_at": experiment.started_at.isoformat() if experiment.started_at else None,
        "software_version": "0.1.0-phase15",
        "configuration": experiment.configuration,
    }


def _write_manifest(manifest: dict[str, Any]) -> Path:
    path = Path(__file__).resolve().parents[4] / "data" / "phase15" / "experiment_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path


async def _run_cell(
    session: Session,
    experiment: Experiment,
    project: Project,
    interface: InterfaceVersion,
    model: str,
    tasks: list[BenchmarkTask],
    split: str,
    trial: int,
    configuration: Phase15Configuration,
    settings: Settings,
) -> BenchmarkRun:
    return await run_benchmark(
        session,
        project,
        model,
        tasks,
        {
            "max_iterations": settings.max_iterations,
            "max_tool_calls": settings.max_tool_calls,
            "timeout_seconds": settings.run_timeout_seconds,
            "temperature": configuration.temperature,
            "trial_seed": configuration.split_seed + trial,
            "provider_seed": None,
            "phase15": True,
        },
        settings,
        interface_version=interface,
        experiment_id=experiment.id,
        trial_number=trial,
        task_split=split,
    )


async def _execute_cells(
    session: Session,
    experiment: Experiment,
    cells: list[ExperimentCell],
    configuration: Phase15Configuration,
    settings: Settings,
) -> list[str]:
    """Execute independent matrix cells with a real bounded-concurrency path.

    SQLite is intentionally serialized because a benchmark transaction contains many
    writes. PostgreSQL uses independent sessions under the configured semaphore.
    """

    failures: list[str] = []
    effective_concurrency = (
        1 if session.get_bind().dialect.name == "sqlite" else configuration.max_concurrency
    )

    async def run_with(worker_session: Session, cell: ExperimentCell) -> None:
        project = worker_session.get(Project, cell.project_id)
        interface = worker_session.get(InterfaceVersion, cell.interface_id)
        worker_experiment = worker_session.get(Experiment, experiment.id)
        tasks = list(
            worker_session.scalars(select(BenchmarkTask).where(BenchmarkTask.id.in_(cell.task_ids)))
        )
        if not project or not interface or not worker_experiment:
            failures.append(f"{cell.label}: experiment cell references missing rows")
            return
        try:
            await _run_cell(
                worker_session,
                worker_experiment,
                project,
                interface,
                cell.model,
                tasks,
                cell.split,
                cell.trial,
                configuration,
                settings,
            )
        except Exception as exc:
            failures.append(f"{cell.label}: {exc}")

    if effective_concurrency == 1:
        for cell in cells:
            await run_with(session, cell)
        return failures

    semaphore = asyncio.Semaphore(effective_concurrency)

    async def worker(cell: ExperimentCell) -> None:
        async with semaphore:
            with SessionLocal() as worker_session:
                await run_with(worker_session, cell)

    await asyncio.gather(*(worker(cell) for cell in cells))
    session.expire_all()
    return failures


async def run_phase15_experiment(
    session: Session,
    projects: list[Project],
    configuration: Phase15Configuration,
    settings: Settings,
    name: str = "AgentSEO Phase 1.5 interface validation",
) -> Experiment:
    configuration.validate()
    if not projects:
        raise ValueError("At least one project is required")
    tasks = list(
        session.scalars(
            select(BenchmarkTask).where(
                BenchmarkTask.project_id.in_([project.id for project in projects]),
                BenchmarkTask.enabled.is_(True),
            )
        )
    )
    if not tasks:
        raise ValueError("Selected projects contain no enabled benchmark tasks")
    split = assign_task_split(tasks, configuration.split_seed)
    estimate = estimate_experiment_cost(len(tasks), configuration)
    experiment = Experiment(
        project_id=projects[0].id,
        name=name,
        hypothesis=(
            "Changing only the agent-facing tool interface materially changes reliable task "
            "completion, and targeted changes produce repeatable, potentially model-specific lift."
        ),
        status=ExperimentStatus.READY.value,
        task_split_seed=configuration.split_seed,
        configuration={
            "variants": configuration.variants,
            "temperature": configuration.temperature,
            "provider_seed": None,
            "max_concurrency": configuration.max_concurrency,
            "cost_estimate": estimate,
            "task_split": split,
            "manual_optimization_protocol": "development failures inspected before V2 freeze",
            "unavailable_providers": configuration.unavailable_providers or [],
        },
        models=configuration.models,
        repetitions=configuration.repetitions,
        estimated_cost=float(estimate["guarded_estimate_usd"]),
    )
    session.add(experiment)
    session.commit()

    if experiment.estimated_cost > configuration.max_cost_usd:
        experiment.status = ExperimentStatus.BLOCKED_COST.value
        experiment.notes = (
            f"Estimated cost ${experiment.estimated_cost:.4f} exceeds configured cap "
            f"${configuration.max_cost_usd:.4f}. No model calls were made."
        )
        session.commit()
        experiment.manifest = create_manifest(experiment, tasks, [])
        session.commit()
        _write_manifest(experiment.manifest)
        return experiment

    experiment.status = ExperimentStatus.RUNNING.value
    experiment.started_at = now()
    session.commit()
    variants_by_project: dict[str, dict[str, InterfaceVersion]] = {}
    failures: list[str] = []
    baseline_cells: list[ExperimentCell] = []

    # Experiment A: baseline development runs happen before V2 is created or hidden outcomes run.
    for project in projects:
        early_keys = [key for key in ("baseline", "degraded") if key in configuration.variants]
        early = create_phase15_variants(session, project, early_keys, experiment.id)
        variants_by_project[project.id] = {item.variant_key: item for item in early}
        development_tasks = [
            task
            for task in tasks
            if task.project_id == project.id and task.phase15_split == "development"
        ]
        baseline = variants_by_project[project.id].get("baseline")
        if baseline and development_tasks:
            for model in configuration.models:
                for trial in range(1, configuration.repetitions + 1):
                    baseline_cells.append(
                        ExperimentCell(
                            project_id=project.id,
                            interface_id=baseline.id,
                            model=model,
                            task_ids=[task.id for task in development_tasks],
                            split="development",
                            trial=trial,
                            label=f"{project.sandbox_domain}/{model}/baseline/dev/{trial}",
                        )
                    )

    failures.extend(
        await _execute_cells(session, experiment, baseline_cells, configuration, settings)
    )

    development_failures = Counter(
        str(item)
        for item in session.scalars(
            select(TaskRun.failure_category).where(
                TaskRun.experiment_id == experiment.id,
                TaskRun.task_split == "development",
                TaskRun.failure_category.is_not(None),
            )
        )
    )
    updated_configuration = dict(experiment.configuration)
    updated_configuration["development_failure_review"] = dict(development_failures)
    updated_configuration["v2_frozen_at"] = now().isoformat()
    experiment.configuration = updated_configuration
    session.commit()

    # Experiments B-E: freeze remaining variants, then and only then evaluate hidden tasks.
    for project in projects:
        remaining = [
            key for key in configuration.variants if key not in variants_by_project[project.id]
        ]
        created = create_phase15_variants(session, project, remaining, experiment.id)
        variants_by_project[project.id].update({item.variant_key: item for item in created})

    all_interfaces = [
        variants_by_project[project.id][key]
        for project in projects
        for key in configuration.variants
    ]
    experiment.interface_versions = [item.id for item in all_interfaces]
    experiment.manifest = create_manifest(experiment, tasks, all_interfaces)
    session.commit()
    _write_manifest(experiment.manifest)

    matrix_cells: list[ExperimentCell] = []
    for split_name in ("development", "hidden"):
        for project in projects:
            selected_tasks = [
                task
                for task in tasks
                if task.project_id == project.id and task.phase15_split == split_name
            ]
            if not selected_tasks:
                continue
            for variant_key in configuration.variants:
                if split_name == "development" and variant_key == "baseline":
                    continue
                interface = variants_by_project[project.id][variant_key]
                for model in configuration.models:
                    for trial in range(1, configuration.repetitions + 1):
                        matrix_cells.append(
                            ExperimentCell(
                                project_id=project.id,
                                interface_id=interface.id,
                                model=model,
                                task_ids=[task.id for task in selected_tasks],
                                split=split_name,
                                trial=trial,
                                label=(
                                    f"{project.sandbox_domain}/{model}/{variant_key}/"
                                    f"{split_name}/{trial}"
                                ),
                            )
                        )

    failures.extend(
        await _execute_cells(session, experiment, matrix_cells, configuration, settings)
    )

    experiment.actual_cost = sum(
        session.scalars(select(TaskRun.cost_estimate).where(TaskRun.experiment_id == experiment.id))
    )
    experiment.completed_at = now()
    experiment.status = (
        ExperimentStatus.COMPLETED.value
        if session.scalar(select(TaskRun.id).where(TaskRun.experiment_id == experiment.id))
        else ExperimentStatus.FAILED.value
    )
    experiment.notes = "\n".join(failures)
    final_manifest = create_manifest(experiment, tasks, all_interfaces)
    final_manifest["completed_at"] = experiment.completed_at.isoformat()
    final_manifest["actual_cost_usd"] = experiment.actual_cost
    final_manifest["failed_cells"] = failures
    experiment.manifest = final_manifest
    session.commit()
    _write_manifest(final_manifest)
    return experiment


def analyze_experiment(
    session: Session, experiment: Experiment, bootstrap_samples: int = 2000
) -> dict[str, Any]:
    observations = experiment_observations(session, experiment)
    grouped: dict[tuple[str, str, str, bool], list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        grouped[
            (
                str(item["model"]),
                str(item["interface_version"]),
                str(item["task_split"]),
                bool(item["synthetic"]),
            )
        ].append(item)

    def rate(rows: list[dict[str, Any]], key: str) -> float:
        return sum(bool(row[key]) for row in rows) / len(rows) if rows else 0.0

    aggregates = []
    for (model, variant, task_split, synthetic), rows in sorted(grouped.items()):
        multi_step = [row for row in rows if int(row["difficulty"]) >= 3]
        recovery = [row for row in rows if row["task_category"] == "error_recovery"]
        clarification = [row for row in rows if row["task_category"] == "clarification"]
        aggregates.append(
            {
                "model": model,
                "variant": variant,
                "task_split": task_split,
                "synthetic": synthetic,
                "task_success_rate": rate(rows, "success"),
                "tool_selection_accuracy": rate(rows, "tool_selection_correct"),
                "argument_accuracy": rate(rows, "arguments_correct"),
                "multi_step_completion_rate": rate(multi_step, "success") if multi_step else None,
                "error_recovery_rate": rate(recovery, "success") if recovery else None,
                "clarification_accuracy": rate(clarification, "success") if clarification else None,
                "destructive_action_safety": sum(
                    row["failure_category"] != "DESTRUCTIVE_ACTION_ERROR" for row in rows
                )
                / len(rows),
                "average_tool_calls": sum(int(row["tool_calls"]) for row in rows) / len(rows),
                "average_latency_ms": sum(float(row["latency"]) for row in rows) * 1000 / len(rows),
                "average_tokens": sum(int(row["tokens"]["total"]) for row in rows) / len(rows),
                "estimated_cost": sum(float(row["cost"]) for row in rows),
                "sample_size": len(rows),
            }
        )

    comparisons = []
    for (model, variant, task_split, synthetic), rows in grouped.items():
        if variant == "baseline":
            continue
        baseline = grouped.get((model, "baseline", task_split, synthetic), [])
        if not baseline:
            continue
        comparison = paired_binary_comparison(
            baseline,
            rows,
            bootstrap_samples=bootstrap_samples,
            seed=experiment.task_split_seed,
        )
        comparisons.append(
            {
                "model": model,
                "variant": variant,
                "task_split": task_split,
                "synthetic": synthetic,
                **comparison,
            }
        )

    failure_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        if item["failure_category"]:
            failure_groups[
                (str(item["model"]), str(item["interface_version"]), str(item["failure_category"]))
            ].append(item)
    failure_analysis = [
        {
            "model": model,
            "variant": variant,
            "failure_category": category,
            "count": len(rows),
            "sample_size": len(
                [
                    item
                    for item in observations
                    if item["model"] == model and item["interface_version"] == variant
                ]
            ),
            "rate": len(rows)
            / len(
                [
                    item
                    for item in observations
                    if item["model"] == model and item["interface_version"] == variant
                ]
            ),
        }
        for (model, variant, category), rows in sorted(failure_groups.items())
    ]

    mutation_failure_analysis = []
    mutation_totals: Counter[str] = Counter()
    mutation_failures: Counter[tuple[str, str]] = Counter()
    for item in observations:
        for mutation in item["mutation_types"]:
            mutation_totals[str(mutation)] += 1
            if item["failure_category"]:
                mutation_failures[(str(mutation), str(item["failure_category"]))] += 1
    for (mutation, category), count in sorted(mutation_failures.items()):
        mutation_failure_analysis.append(
            {
                "mutation_type": mutation,
                "failure_category": category,
                "count": count,
                "sample_size": mutation_totals[mutation],
                "rate": count / mutation_totals[mutation],
            }
        )

    cross_model_variance = []
    aggregate_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in aggregates:
        if not row["synthetic"]:
            aggregate_groups[(row["variant"], row["task_split"])].append(row)
    for (variant, task_split), rows in sorted(aggregate_groups.items()):
        values = [float(row["task_success_rate"]) for row in rows]
        mean = sum(values) / len(values)
        cross_model_variance.append(
            {
                "variant": variant,
                "task_split": task_split,
                "model_count": len(values),
                "variance": sum((value - mean) ** 2 for value in values) / len(values),
                "range": max(values) - min(values),
                "exploratory": True,
            }
        )

    difficulty_lifts = []
    difficulties = sorted({int(item["difficulty"]) for item in observations})
    for model in sorted({str(item["model"]) for item in observations}):
        for variant in sorted(
            {str(item["interface_version"]) for item in observations} - {"baseline"}
        ):
            for difficulty in difficulties:
                baseline = [
                    item
                    for item in observations
                    if item["model"] == model
                    and item["interface_version"] == "baseline"
                    and item["difficulty"] == difficulty
                ]
                treatment = [
                    item
                    for item in observations
                    if item["model"] == model
                    and item["interface_version"] == variant
                    and item["difficulty"] == difficulty
                ]
                if baseline and treatment:
                    difficulty_lifts.append(
                        {
                            "model": model,
                            "variant": variant,
                            "difficulty": difficulty,
                            "absolute_difference": rate(treatment, "success")
                            - rate(baseline, "success"),
                        }
                    )

    real_comparisons = [row for row in comparisons if not row["synthetic"]]
    effects = flag_model_specific_effects(real_comparisons)
    real_observations = [row for row in observations if not row["synthetic"]]
    if not real_observations:
        decision = "DO NOT PROCEED YET"
        reasons = [
            "No real-provider API keys were configured, so the central hypothesis has not been tested on GPT, Claude, or Gemini.",
            "The synthetic matrix validates persistence, interface translation, repetition, statistics, export, and reporting only.",
            "Run the frozen manifest with real providers before authorizing Phase 2 optimizer work.",
        ]
        summary = (
            "The experimental system is ready, but the locally available evidence cannot validate or "
            "falsify interface sensitivity because only MockAgent system tests were runnable."
        )
    else:
        degraded = [row for row in real_comparisons if row["variant"] == "degraded"]
        optimized_hidden = [
            row
            for row in real_comparisons
            if row["variant"] == "optimized" and row["task_split"] == "hidden"
        ]
        degraded_effect = (
            -sum(float(row["absolute_difference"]) for row in degraded) / len(degraded)
            if degraded
            else 0.0
        )
        optimized_effect = (
            sum(float(row["absolute_difference"]) for row in optimized_hidden)
            / len(optimized_hidden)
            if optimized_hidden
            else 0.0
        )
        domain_count = len({row["api_domain"] for row in real_observations})
        if degraded_effect >= 0.10 and optimized_effect >= 0.05 and domain_count > 1:
            decision = "GO TO PHASE 2"
            reasons = [
                f"Average degradation effect was {_format_points(degraded_effect)}.",
                f"Average optimized hidden-set lift was {_format_points(optimized_effect)}.",
                f"Effects were tested across {domain_count} domains.",
            ]
        elif degraded_effect >= 0.10 or optimized_effect >= 0.05:
            decision = "CONDITIONAL GO"
            reasons = [
                f"Degradation effect: {_format_points(degraded_effect)}; optimized hidden lift: {_format_points(optimized_effect)}.",
                "Evidence is concentrated in a subset; Phase 2 should target only supported mutation categories.",
            ]
        else:
            decision = "DO NOT PROCEED YET"
            reasons = [
                f"Degradation effect ({_format_points(degraded_effect)}) and optimized hidden lift ({_format_points(optimized_effect)}) do not meet the stated heuristics.",
                "Additional evidence or benchmark repair is required before optimizer development.",
            ]
        summary = f"Real-provider observations were analyzed with paired methods. The evidence-based decision is {decision}."

    analysis = {
        "aggregates": aggregates,
        "comparisons": sorted(
            comparisons, key=lambda row: (row["model"], row["task_split"], row["variant"])
        ),
        "failure_analysis": failure_analysis,
        "mutation_failure_analysis": mutation_failure_analysis,
        "cross_model_variance": cross_model_variance,
        "difficulty_lifts": difficulty_lifts,
        "model_specific_effects": effects,
        "decision": decision,
        "decision_reasons": reasons,
        "executive_summary": summary,
        "domains": sorted({str(item["api_domain"]) for item in observations}),
        "variants": sorted({str(item["interface_version"]) for item in observations}),
        "observation_count": len(observations),
        "real_observation_count": len(real_observations),
        "exploratory": True,
    }
    session.execute(delete(ExperimentResult).where(ExperimentResult.experiment_id == experiment.id))
    for aggregate in aggregates:
        session.add(
            ExperimentResult(
                experiment_id=experiment.id,
                result_type="AGGREGATE",
                model=aggregate["model"],
                # Aggregates may span domains and therefore multiple interface-version IDs.
                interface_version_id=None,
                task_split=aggregate["task_split"],
                metric_name="task_success_rate",
                metric_value=aggregate["task_success_rate"],
                sample_size=aggregate["sample_size"],
                details=aggregate,
            )
        )
    for comparison in comparisons:
        low, high = comparison["confidence_interval"]
        session.add(
            ExperimentResult(
                experiment_id=experiment.id,
                result_type="PAIRED_COMPARISON",
                model=comparison["model"],
                task_split=comparison["task_split"],
                metric_name=f"{comparison['variant']}_vs_baseline",
                metric_value=comparison["absolute_difference"],
                sample_size=comparison["sample_size_tasks"],
                confidence_low=low,
                confidence_high=high,
                p_value=comparison["p_value"],
                details=comparison,
            )
        )
    for effect in effects:
        session.add(
            ExperimentResult(
                experiment_id=experiment.id,
                result_type="MODEL_SPECIFIC_INTERFACE_EFFECT",
                task_split=effect["task_split"],
                metric_name=effect["variant"],
                metric_value=effect["range"],
                details=effect,
            )
        )
    for variance in cross_model_variance:
        session.add(
            ExperimentResult(
                experiment_id=experiment.id,
                result_type="CROSS_MODEL_VARIANCE",
                task_split=variance["task_split"],
                metric_name=variance["variant"],
                metric_value=variance["variance"],
                sample_size=variance["model_count"],
                details=variance,
            )
        )
    session.commit()
    return analysis


def _format_points(value: float) -> str:
    return f"{value * 100:.1f} percentage points"


def finalize_experiment_artifacts(
    session: Session, experiment: Experiment, bootstrap_samples: int = 2000
) -> dict[str, Any]:
    analysis = analyze_experiment(session, experiment, bootstrap_samples)
    jsonl, csv_path = export_experiment_dataset(session, experiment)
    markdown, html_path, charts = generate_report(experiment, analysis)
    return {
        "analysis": analysis,
        "dataset_jsonl": str(jsonl),
        "dataset_csv": str(csv_path),
        "report_markdown": str(markdown),
        "report_html": str(html_path),
        "charts": [str(path) for path in charts],
    }


def run_phase15_sync(
    session: Session,
    projects: list[Project],
    configuration: Phase15Configuration,
    settings: Settings,
) -> tuple[Experiment, dict[str, Any]]:
    experiment = asyncio.run(run_phase15_experiment(session, projects, configuration, settings))
    artifacts = finalize_experiment_artifacts(
        session, experiment, bootstrap_samples=configuration.bootstrap_samples
    )
    return experiment, artifacts
