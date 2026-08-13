"""Run the preregistered R2 analysis after the complete sealed matrix exists."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from statistics import mean
from typing import Any

from agentseo.database import SessionLocal
from agentseo.models import (
    BenchmarkRun,
    BenchmarkTask,
    Experiment,
    ExperimentStatus,
    InterfaceVersion,
    Project,
    RunStatus,
    TaskRun,
)
from agentseo.statistics import paired_binary_comparison, proportion_confidence_interval
from sqlalchemy import select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
R2_ROOT = ROOT / "artifacts" / "phase15b_r2"
OUTPUT_ROOT = R2_ROOT / "sealed_holdout_results"
EXECUTION_STATE_PATH = R2_ROOT / "sealed_holdout_runtime" / "execution_state.json"
VARIANTS = (
    "baseline",
    "phase15b_r2_general",
    "phase15b_r2_gpt",
    "phase15b_r2_claude",
    "phase15b_r2_gemini",
)
DISPLAY = {
    "baseline": "V0",
    "phase15b_r2_general": "V2-General",
    "phase15b_r2_gpt": "V2-GPT",
    "phase15b_r2_claude": "V2-Claude",
    "phase15b_r2_gemini": "V2-Gemini",
}
MODELS = (
    "openai:gpt-4.1-mini",
    "anthropic:claude-sonnet-5",
    "google:gemini-3.6-flash",
)
MODEL_DISPLAY = {
    MODELS[0]: "GPT",
    MODELS[1]: "Claude",
    MODELS[2]: "Gemini",
}
SPECIFIC = {
    MODELS[0]: "phase15b_r2_gpt",
    MODELS[1]: "phase15b_r2_claude",
    MODELS[2]: "phase15b_r2_gemini",
}


def _rate(rows: list[dict[str, Any]], key: str) -> float | None:
    return sum(bool(row[key]) for row in rows) / len(rows) if rows else None


def _cluster_rate_interval(
    rows: list[dict[str, Any]], cluster_key: str, samples: int = 5000, seed: int = 1503
) -> list[float]:
    clusters: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        clusters[str(row[cluster_key])].append(float(bool(row["success"])))
    values = [mean(items) for _, items in sorted(clusters.items())]
    if not values:
        return [0.0, 0.0]
    rng = random.Random(seed)
    draws = [mean(rng.choice(values) for _ in values) for _ in range(samples)]
    draws.sort()
    return [draws[int(0.025 * (samples - 1))], draws[int(0.975 * (samples - 1))]]


def _cluster_difference_interval(
    baseline: list[dict[str, Any]],
    treatment: list[dict[str, Any]],
    value: Callable[[dict[str, Any]], float],
    cluster_key: str = "task_id",
    samples: int = 5000,
    seed: int = 1503,
) -> list[float]:
    left: dict[str, list[float]] = defaultdict(list)
    right: dict[str, list[float]] = defaultdict(list)
    for row in baseline:
        left[str(row[cluster_key])].append(value(row))
    for row in treatment:
        right[str(row[cluster_key])].append(value(row))
    clusters = sorted(set(left) & set(right))
    differences = [mean(right[key]) - mean(left[key]) for key in clusters]
    if not differences:
        return [0.0, 0.0]
    rng = random.Random(seed)
    draws = [mean(rng.choice(differences) for _ in differences) for _ in range(samples)]
    draws.sort()
    return [draws[int(0.025 * (samples - 1))], draws[int(0.975 * (samples - 1))]]


def _task_changes(
    baseline: list[dict[str, Any]], treatment: list[dict[str, Any]]
) -> dict[str, int]:
    left: dict[str, list[bool]] = defaultdict(list)
    right: dict[str, list[bool]] = defaultdict(list)
    for row in baseline:
        left[str(row["task_id"])].append(bool(row["success"]))
    for row in treatment:
        right[str(row["task_id"])].append(bool(row["success"]))
    result = Counter[str]()
    for task_id in sorted(set(left) & set(right)):
        difference = mean(right[task_id]) - mean(left[task_id])
        result["gained" if difference > 0 else "regressed" if difference < 0 else "unchanged"] += 1
    return {key: result[key] for key in ("gained", "regressed", "unchanged")}


def _observation_rows(session: Any, experiment_id: str) -> list[dict[str, Any]]:
    query = (
        select(TaskRun, BenchmarkRun, BenchmarkTask, InterfaceVersion, Project)
        .join(BenchmarkRun, TaskRun.benchmark_run_id == BenchmarkRun.id)
        .join(BenchmarkTask, TaskRun.task_id == BenchmarkTask.id)
        .join(InterfaceVersion, TaskRun.interface_version_id == InterfaceVersion.id)
        .join(Project, BenchmarkRun.project_id == Project.id)
        .where(
            TaskRun.experiment_id == experiment_id,
            TaskRun.status == RunStatus.COMPLETED.value,
            TaskRun.task_split == "holdout",
        )
        .options(selectinload(TaskRun.trace_events))
    )
    rows: list[dict[str, Any]] = []
    for task_run, benchmark_run, task, interface, project in session.execute(query):
        result = task_run.evaluator_result or {}
        calls = [event for event in task_run.trace_events if event.event_type == "TOOL_CALLED"]
        tokens = task_run.token_usage or {}
        rows.append(
            {
                "experiment_id": experiment_id,
                "task_run_id": task_run.id,
                "benchmark_run_id": benchmark_run.id,
                "model": task_run.model_identifier,
                "variant": interface.variant_key,
                "domain": project.sandbox_domain,
                "task_id": task.id,
                "task_family": task.task_family,
                "task_category": task.category,
                "difficulty": task.difficulty,
                "trial": task_run.trial_number,
                "success": task_run.success,
                "failure_category": task_run.failure_category,
                "tool_selection_correct": bool(
                    result.get("tool_requirements_passed", False)
                    and result.get("forbidden_tools_avoided", False)
                ),
                "schema_arguments_valid": bool(result.get("schema_arguments_valid", True)),
                "semantic_arguments_evaluated": bool(
                    result.get("semantic_arguments_evaluated", False)
                ),
                "semantic_arguments_correct": bool(result.get("semantic_arguments_correct", True)),
                "clarification_passed": bool(result.get("clarification_passed", True))
                and bool(result.get("targeted_clarification_passed", True)),
                "error_recovery_passed": bool(result.get("error_recovery_passed", True)),
                "tool_calls": len(calls),
                "input_tokens": int(tokens.get("input", 0)),
                "output_tokens": int(tokens.get("output", 0)),
                "total_tokens": int(tokens.get("input", 0)) + int(tokens.get("output", 0)),
                "latency_seconds": task_run.duration,
                "cost_usd": task_run.cost_estimate,
            }
        )
    return rows


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    semantic = [row for row in rows if row["semantic_arguments_evaluated"]]
    clarification = [row for row in rows if str(row["task_category"]).startswith("clarification_")]
    recovery = [row for row in rows if row["task_category"] == "error_recovery"]
    safety = [row for row in rows if row["task_category"] == "safety_destructive"]
    multi_step = [row for row in rows if row["task_category"] == "multi_step"]
    successes = [bool(row["success"]) for row in rows]
    wilson = proportion_confidence_interval(successes)
    return {
        "observations": len(rows),
        "tasks": len({row["task_id"] for row in rows}),
        "task_success": _rate(rows, "success"),
        "task_success_ci95_task_cluster": _cluster_rate_interval(rows, "task_id"),
        "task_success_ci95_wilson_observations": list(wilson),
        "tool_selection_accuracy": _rate(rows, "tool_selection_correct"),
        "semantic_argument_correctness": _rate(semantic, "semantic_arguments_correct"),
        "semantic_argument_observations": len(semantic),
        "multi_step_completion": _rate(multi_step, "success"),
        "clarification_accuracy": _rate(clarification, "clarification_passed"),
        "error_recovery": _rate(recovery, "success"),
        "safety_success": _rate(safety, "success"),
        "average_tool_calls": mean(float(row["tool_calls"]) for row in rows),
        "average_tokens": mean(float(row["total_tokens"]) for row in rows),
        "average_latency_seconds": mean(float(row["latency_seconds"]) for row in rows),
        "estimated_cost_usd": sum(float(row["cost_usd"]) for row in rows),
        "average_cost_usd": mean(float(row["cost_usd"]) for row in rows),
    }


def _comparison(
    model: str,
    baseline_variant: str,
    treatment_variant: str,
    grouped: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    baseline = grouped[(model, baseline_variant)]
    treatment = grouped[(model, treatment_variant)]
    paired: dict[str, Any] = dict(
        paired_binary_comparison(baseline, treatment, bootstrap_samples=5000, seed=1503)
    )
    paired["family_cluster_confidence_interval"] = _cluster_difference_interval(
        baseline,
        treatment,
        lambda row: float(bool(row["success"])),
        cluster_key="task_family",
    )
    paired["task_changes"] = _task_changes(baseline, treatment)
    paired["model"] = model
    paired["baseline_variant"] = baseline_variant
    paired["treatment_variant"] = treatment_variant
    paired["token_delta"] = mean(row["total_tokens"] for row in treatment) - mean(
        row["total_tokens"] for row in baseline
    )
    paired["token_delta_ci95"] = _cluster_difference_interval(
        baseline, treatment, lambda row: float(row["total_tokens"])
    )
    paired["latency_delta_seconds"] = mean(row["latency_seconds"] for row in treatment) - mean(
        row["latency_seconds"] for row in baseline
    )
    paired["latency_delta_ci95"] = _cluster_difference_interval(
        baseline, treatment, lambda row: float(row["latency_seconds"])
    )
    paired["cost_delta_usd_per_observation"] = mean(row["cost_usd"] for row in treatment) - mean(
        row["cost_usd"] for row in baseline
    )
    paired["cost_delta_ci95_per_observation"] = _cluster_difference_interval(
        baseline, treatment, lambda row: float(row["cost_usd"])
    )
    return paired


def _pareto(aggregates: dict[str, dict[str, Any]]) -> list[str]:
    efficient: list[str] = []
    for variant, candidate in aggregates.items():
        dominated = False
        for other_variant, other in aggregates.items():
            if other_variant == variant:
                continue
            at_least_as_good = (
                other["task_success"] >= candidate["task_success"]
                and other["average_tokens"] <= candidate["average_tokens"]
                and other["average_latency_seconds"] <= candidate["average_latency_seconds"]
                and other["estimated_cost_usd"] <= candidate["estimated_cost_usd"]
            )
            strictly_better = (
                other["task_success"] > candidate["task_success"]
                or other["average_tokens"] < candidate["average_tokens"]
                or other["average_latency_seconds"] < candidate["average_latency_seconds"]
                or other["estimated_cost_usd"] < candidate["estimated_cost_usd"]
            )
            if at_least_as_good and strictly_better:
                dominated = True
                break
        if not dominated:
            efficient.append(variant)
    return efficient


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _pp(value: float) -> str:
    return f"{100 * value:+.1f} pp"


def _conclusion(
    comparisons: dict[tuple[str, str, str], dict[str, Any]],
    safety_regressions: list[dict[str, Any]],
) -> str:
    general = [comparisons[(model, "baseline", "phase15b_r2_general")] for model in MODELS]
    specific = [comparisons[(model, "baseline", SPECIFIC[model])] for model in MODELS]
    specific_advantages = []
    for model in MODELS:
        general_rate = comparisons[(model, "baseline", "phase15b_r2_general")]["treatment_rate"]
        baseline_rate = comparisons[(model, "baseline", "phase15b_r2_general")]["baseline_rate"]
        comparator = "phase15b_r2_general" if general_rate >= baseline_rate else "baseline"
        specific_advantages.append(comparisons[(model, comparator, SPECIFIC[model])])
    meaningful_general = sum(row["absolute_difference"] >= 0.05 for row in general)
    meaningful_specific = sum(row["absolute_difference"] >= 0.05 for row in specific)
    advantage_count = sum(row["absolute_difference"] >= 0.03 for row in specific_advantages)
    material_safety = any(row["absolute_difference"] <= -0.05 for row in safety_regressions)
    if meaningful_general >= 2 and not material_safety:
        return "STRONG GO — GENERAL OPTIMIZER"
    if meaningful_specific >= 2 and advantage_count >= 2 and not material_safety:
        return "STRONG GO — MODEL-SPECIFIC OPTIMIZER"
    if (meaningful_general or meaningful_specific) and not material_safety:
        return "CONDITIONAL GO"
    return "NO-GO — MORE VALIDATION REQUIRED"


def _report(analysis: dict[str, Any]) -> str:
    aggregates = analysis["cells"]
    comparisons = analysis["comparisons"]
    lines = [
        "# AgentSEO Phase 1.5B R2 sealed-holdout results",
        "",
        "The complete preregistered 1,620-observation matrix was analyzed only after execution finished. "
        "No interface, task, evaluator, model, repetition, or statistical method changed after unsealing.",
        "",
        "## Hidden-success matrix",
        "",
        "| Interface | GPT | Claude | Gemini |",
        "|---|---:|---:|---:|",
    ]
    for variant in VARIANTS:
        values = [_pct(aggregates[model][variant]["task_success"]) for model in MODELS]
        lines.append(f"| {DISPLAY[variant]} | {values[0]} | {values[1]} | {values[2]} |")
    lines.extend(
        [
            "",
            "## Complete cell metrics",
            "",
            "| Model | Interface | Success (95% task-cluster CI) | Tool selection | Semantic args | Multi-step | Clarification | Recovery | Safety | Calls | Tokens | Latency | Cost |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for model in MODELS:
        for variant in VARIANTS:
            row = aggregates[model][variant]
            low, high = row["task_success_ci95_task_cluster"]
            lines.append(
                f"| {MODEL_DISPLAY[model]} | {DISPLAY[variant]} | {_pct(row['task_success'])} "
                f"[{_pct(low)}, {_pct(high)}] | {_pct(row['tool_selection_accuracy'])} | "
                f"{_pct(row['semantic_argument_correctness'])} | {_pct(row['multi_step_completion'])} | "
                f"{_pct(row['clarification_accuracy'])} | {_pct(row['error_recovery'])} | "
                f"{_pct(row['safety_success'])} | {row['average_tool_calls']:.2f} | "
                f"{row['average_tokens']:.0f} | {row['average_latency_seconds']:.2f}s | "
                f"${row['estimated_cost_usd']:.4f} |"
            )
    lines.extend(
        [
            "",
            "## Preregistered paired comparisons",
            "",
            "| Model | Comparison | Effect | 95% task CI | 95% family sensitivity CI | Exact p | Gained | Regressed | Unchanged | Δ tokens | Δ latency | Δ cost/obs |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in comparisons:
        low, high = row["confidence_interval"]
        flow, fhigh = row["family_cluster_confidence_interval"]
        changes = row["task_changes"]
        lines.append(
            f"| {MODEL_DISPLAY[row['model']]} | {DISPLAY[row['treatment_variant']]} − "
            f"{DISPLAY[row['baseline_variant']]} | {_pp(row['absolute_difference'])} | "
            f"[{_pp(low)}, {_pp(high)}] | [{_pp(flow)}, {_pp(fhigh)}] | "
            f"{row['p_value']:.4f} | {changes['gained']} | {changes['regressed']} | "
            f"{changes['unchanged']} | {row['token_delta']:+.0f} | "
            f"{row['latency_delta_seconds']:+.2f}s | ${row['cost_delta_usd_per_observation']:+.5f} |"
        )
    lines.extend(["", "## Model-specific advantage", ""])
    for row in analysis["model_specific_advantage"]:
        lines.append(
            f"- {MODEL_DISPLAY[row['model']]}: {DISPLAY[row['treatment_variant']]} − "
            f"{DISPLAY[row['baseline_variant']]} = {_pp(row['absolute_difference'])}."
        )
    lines.extend(["", "## Cross-model transfer", ""])
    for row in analysis["cross_model_transfer"]:
        lines.append(
            f"- {DISPLAY[row['treatment_variant']]} on {MODEL_DISPLAY[row['model']]}: "
            f"{_pp(row['absolute_difference'])} versus V0; {row['task_changes']['gained']} tasks gained, "
            f"{row['task_changes']['regressed']} regressed."
        )
    lines.extend(["", "## Pareto-efficient interfaces", ""])
    for model, variants in analysis["pareto_efficient"].items():
        lines.append(
            f"- {MODEL_DISPLAY[model]}: {', '.join(DISPLAY[variant] for variant in variants)}."
        )
    q = analysis["answers"]
    lines.extend(
        [
            "",
            "## Explicit answers",
            "",
            f"- Did V2-General outperform V0 on unseen task families? {q['general']}",
            f"- Did V2-GPT outperform V0 for GPT? {q['gpt']}",
            f"- Did V2-Claude outperform V0 for Claude? {q['claude']}",
            f"- Did V2-Gemini outperform V0 for Gemini? {q['gemini']}",
            f"- Did each model-specific interface outperform V2-General for its intended model? {q['specific_over_general']}",
            f"- How well did model-specific interfaces transfer? {q['transfer']}",
            f"- Is there credible evidence of different interface optima by model family? {q['different_optima']}",
            f"- Were reliability improvements worth token/cost/latency changes? {q['efficiency']}",
            f"- Did optimized interfaces introduce safety regressions? {q['safety']}",
            "",
            "## Conclusion",
            "",
            analysis["conclusion"],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_id")
    args = parser.parse_args()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        experiment = session.get(Experiment, args.experiment_id)
        if experiment is None or experiment.status != ExperimentStatus.COMPLETED.value:
            raise RuntimeError("Analysis requires the finalized sealed-holdout experiment")
        rows = _observation_rows(session, experiment.id)
    unique_keys = {(row["task_id"], row["model"], row["variant"], row["trial"]) for row in rows}
    if len(rows) != 1620 or len(unique_keys) != 1620:
        raise RuntimeError("Preregistered analysis gate requires 1,620 unique observations")
    if set(row["model"] for row in rows) != set(MODELS) or set(
        row["variant"] for row in rows
    ) != set(VARIANTS):
        raise RuntimeError("Observed matrix differs from the preregistered model/interface matrix")

    grouped = {
        (model, variant): [
            row for row in rows if row["model"] == model and row["variant"] == variant
        ]
        for model in MODELS
        for variant in VARIANTS
    }
    if any(len(cell) != 108 for cell in grouped.values()):
        raise RuntimeError("Every model/interface cell must contain exactly 108 observations")
    cells = {
        model: {variant: _aggregate(grouped[(model, variant)]) for variant in VARIANTS}
        for model in MODELS
    }

    all_comparisons: dict[tuple[str, str, str], dict[str, Any]] = {}
    for model in MODELS:
        for variant in VARIANTS[1:]:
            all_comparisons[(model, "baseline", variant)] = _comparison(
                model, "baseline", variant, grouped
            )
    model_specific_advantage = []
    for model in MODELS:
        comparator = (
            "phase15b_r2_general"
            if cells[model]["phase15b_r2_general"]["task_success"]
            >= cells[model]["baseline"]["task_success"]
            else "baseline"
        )
        row = _comparison(model, comparator, SPECIFIC[model], grouped)
        all_comparisons[(model, comparator, SPECIFIC[model])] = row
        model_specific_advantage.append(row)
    specific_vs_general = []
    for model in MODELS:
        row = _comparison(model, "phase15b_r2_general", SPECIFIC[model], grouped)
        all_comparisons[(model, "phase15b_r2_general", SPECIFIC[model])] = row
        specific_vs_general.append(row)
    cross_model_transfer = [
        all_comparisons[(model, "baseline", variant)]
        for variant, intended in (
            ("phase15b_r2_gpt", MODELS[0]),
            ("phase15b_r2_claude", MODELS[1]),
            ("phase15b_r2_gemini", MODELS[2]),
        )
        for model in MODELS
        if model != intended
    ]
    safety_regressions = []
    for model in MODELS:
        baseline_safety = [
            row
            for row in grouped[(model, "baseline")]
            if row["task_category"] == "safety_destructive"
        ]
        for variant in VARIANTS[1:]:
            treatment_safety = [
                row
                for row in grouped[(model, variant)]
                if row["task_category"] == "safety_destructive"
            ]
            effect = mean(row["success"] for row in treatment_safety) - mean(
                row["success"] for row in baseline_safety
            )
            safety_regressions.append(
                {"model": model, "variant": variant, "absolute_difference": effect}
            )

    conclusion = _conclusion(all_comparisons, safety_regressions)
    general_effects = [
        all_comparisons[(model, "baseline", "phase15b_r2_general")]["absolute_difference"]
        for model in MODELS
    ]
    intended_effects = {
        model: all_comparisons[(model, "baseline", SPECIFIC[model])]["absolute_difference"]
        for model in MODELS
    }
    specific_general_effects = {
        row["model"]: row["absolute_difference"] for row in specific_vs_general
    }
    best = {
        model: max(VARIANTS, key=lambda variant: cells[model][variant]["task_success"])
        for model in MODELS
    }
    transfer_effects = [row["absolute_difference"] for row in cross_model_transfer]
    safety_negative = [row for row in safety_regressions if row["absolute_difference"] < 0]
    pareto = {model: _pareto(cells[model]) for model in MODELS}
    answers = {
        "general": (
            f"Effects were {', '.join(_pp(value) for value in general_effects)} for GPT, Claude, and Gemini."
        ),
        "gpt": f"Effect: {_pp(intended_effects[MODELS[0]])}.",
        "claude": f"Effect: {_pp(intended_effects[MODELS[1]])}.",
        "gemini": f"Effect: {_pp(intended_effects[MODELS[2]])}.",
        "specific_over_general": ", ".join(
            f"{MODEL_DISPLAY[model]} {_pp(effect)}"
            for model, effect in specific_general_effects.items()
        )
        + ".",
        "transfer": (
            f"Cross-transfer effects ranged from {_pp(min(transfer_effects))} to {_pp(max(transfer_effects))}; "
            "the detailed table reports gains and regressions for every non-intended model."
        ),
        "different_optima": (
            "Best hidden interfaces were "
            + ", ".join(
                f"{MODEL_DISPLAY[model]}={DISPLAY[variant]}" for model, variant in best.items()
            )
            + "."
        ),
        "efficiency": (
            "Reliability, token, latency, and cost deltas are reported pairwise; non-dominated choices are "
            "listed as Pareto-efficient rather than collapsed into a composite score."
        ),
        "safety": (
            "No optimized interface had lower safety success than V0."
            if not safety_negative
            else f"{len(safety_negative)} model/interface cells had lower safety success than V0."
        ),
    }
    primary_keys = [(model, "baseline", "phase15b_r2_general") for model in MODELS] + [
        (model, "baseline", SPECIFIC[model]) for model in MODELS
    ]
    comparison_rows = list(all_comparisons.values())
    analysis = {
        "protocol": "PHASE15B_R2_PREREGISTERED_SEALED_HOLDOUT_ANALYSIS",
        "experiment_id": args.experiment_id,
        "observation_count": len(rows),
        "unique_observation_count": len(unique_keys),
        "cells": cells,
        "primary_comparisons": [all_comparisons[key] for key in primary_keys],
        "comparisons": comparison_rows,
        "model_specific_advantage": model_specific_advantage,
        "model_specific_vs_general": specific_vs_general,
        "cross_model_transfer": cross_model_transfer,
        "safety_changes": safety_regressions,
        "pareto_efficient": pareto,
        "best_hidden_interface": best,
        "answers": answers,
        "conclusion": conclusion,
        "methods": {
            "binary_effect": "paired task-cluster bootstrap with repetitions preserved within task",
            "exact_test": "exact McNemar on task-majority outcomes",
            "sensitivity": "family-cluster bootstrap",
            "cell_interval": "task-cluster bootstrap; Wilson observation interval also retained",
            "continuous_effects": "paired task-cluster bootstrap",
            "multiple_comparisons": "exploratory; all preregistered comparisons reported",
        },
    }
    (OUTPUT_ROOT / "analysis.json").write_text(
        json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8"
    )
    (OUTPUT_ROOT / "raw_observations.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    with (OUTPUT_ROOT / "raw_observations.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = _report(analysis)
    (OUTPUT_ROOT / "report.md").write_text(report, encoding="utf-8")
    (ROOT / "docs" / "phase15b_r2_sealed_holdout_results.md").write_text(report, encoding="utf-8")
    runtime_state = json.loads(EXECUTION_STATE_PATH.read_text(encoding="utf-8"))
    execution_summary = {
        "protocol": runtime_state["protocol"],
        "experiment_id": runtime_state["experiment_id"],
        "status": runtime_state["status"],
        "created_at": runtime_state["created_at"],
        "completed_at": runtime_state.get("completed_at"),
        "verification": runtime_state["verification"],
        "provider_credit_preflight": [
            {"model": row["model"], "status": row["status"]}
            for row in runtime_state["credit_preflight"]["providers"]
        ],
        "launches": runtime_state["launches"],
        "completed_observations": len(rows),
        "unique_observations": len(unique_keys),
        "actual_cost_usd": sum(row["cost_usd"] for row in rows),
        "outcomes_inspected_before_completion": False,
    }
    (OUTPUT_ROOT / "execution_summary.json").write_text(
        json.dumps(execution_summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    reproducibility = {
        "experiment_id": args.experiment_id,
        "database": str(
            (R2_ROOT / "sealed_holdout_runtime" / "phase15b_r2_holdout.db").relative_to(ROOT)
        ).replace("\\", "/"),
        "database_committed": False,
        "frozen_benchmark_manifest": "artifacts/phase15b_r2/frozen_benchmark/protocol_manifest.json",
        "holdout_manifest": "artifacts/phase15b_r2/frozen_benchmark/holdout_manifest.json",
        "interface_manifest": "artifacts/phase15b_r2/frozen_interfaces/manifest.json",
        "preregistration": "artifacts/phase15b_r2/preregistration.json",
        "execution_summary": "artifacts/phase15b_r2/sealed_holdout_results/execution_summary.json",
        "analysis_script": "scripts/analyze_phase15b_r2_holdout.py",
        "raw_rows": 1620,
        "raw_dataset_sha256": __import__("hashlib")
        .sha256((OUTPUT_ROOT / "raw_observations.jsonl").read_bytes())
        .hexdigest(),
    }
    (OUTPUT_ROOT / "reproducibility.json").write_text(
        json.dumps(reproducibility, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "experiment_id": args.experiment_id,
                "observations": len(rows),
                "conclusion": conclusion,
                "actual_cost_usd": sum(row["cost_usd"] for row in rows),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
