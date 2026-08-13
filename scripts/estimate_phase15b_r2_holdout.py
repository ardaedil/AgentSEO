"""Estimate the frozen R2 sealed-holdout matrix without opening task content."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from agentseo.config import get_settings
from agentseo.pricing import MODEL_PRICES, pricing_manifest

ROOT = Path(__file__).resolve().parents[1]
R2_ROOT = ROOT / "artifacts" / "phase15b_r2"


def main() -> None:
    holdout = json.loads(
        (R2_ROOT / "frozen_benchmark" / "holdout_manifest.json").read_text(encoding="utf-8")
    )
    interfaces = json.loads(
        (R2_ROOT / "frozen_interfaces" / "manifest.json").read_text(encoding="utf-8")
    )
    if holdout["state"] != "SEALED_UNOPENED" or interfaces["holdout_task_runs_at_freeze"]:
        raise RuntimeError("Cost estimation requires an unopened R2 holdout")
    observations = [
        json.loads(line)
        for line in (R2_ROOT / "calibration_b" / "data" / "experiment_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        by_model[str(row["model"])].append(row)

    description_tokens: dict[str, list[int]] = defaultdict(list)
    for row in interfaces["interfaces"]:
        description_tokens[str(row["variant_key"])].append(
            int(row["complexity"]["total_description_tokens"])
        )
    average_description_tokens = {
        variant: sum(values) / len(values) for variant, values in description_tokens.items()
    }
    variants = list(interfaces["variants"])
    treatment_variants = [variant for variant in variants if variant != "baseline"]
    holdout_tasks = int(holdout["task_count"])
    repetitions = 3
    runs_per_variant = holdout_tasks * repetitions
    runs_per_model = runs_per_variant * len(variants)
    settings = get_settings()

    providers: list[dict[str, Any]] = []
    for model in interfaces["models"]:
        rows = by_model[model]
        average_input = sum(int(row["tokens"]["input"]) for row in rows) / len(rows)
        average_output = sum(int(row["tokens"]["output"]) for row in rows) / len(rows)
        average_tool_calls = sum(int(row["tool_calls"]) for row in rows) / len(rows)
        requests_per_task = average_tool_calls + 1
        baseline_input_tokens = average_input * runs_per_model
        description_overhead = sum(
            (average_description_tokens[variant] - average_description_tokens["baseline"])
            * requests_per_task
            * runs_per_variant
            for variant in treatment_variants
        )
        estimated_input = baseline_input_tokens + description_overhead
        estimated_output = average_output * runs_per_model
        price = MODEL_PRICES[model]
        estimated_cost = (
            estimated_input * price.input_per_million + estimated_output * price.output_per_million
        ) / 1_000_000
        providers.append(
            {
                "model": model,
                "task_runs": runs_per_model,
                "expected_model_requests": requests_per_task * runs_per_model,
                "conservative_model_requests": 4 * runs_per_model,
                "estimated_input_tokens": estimated_input,
                "estimated_output_tokens": estimated_output,
                "estimated_total_tokens": estimated_input + estimated_output,
                "estimated_cost_usd": estimated_cost,
                "guarded_cost_usd": estimated_cost * 1.25,
                "calibration_average_tool_calls": average_tool_calls,
                "calibration_average_input_tokens": average_input,
                "calibration_average_output_tokens": average_output,
            }
        )

    total_cost = sum(row["estimated_cost_usd"] for row in providers)
    estimate = {
        "protocol": "PHASE15B_R2_SEALED_HOLDOUT_COST_GATE",
        "holdout_state": holdout["state"],
        "holdout_manifest_sha256": holdout["holdout_manifest_sha256"],
        "interface_freeze_sha256": interfaces["interface_freeze_sha256"],
        "holdout_tasks": holdout_tasks,
        "holdout_task_families": holdout["task_family_count"],
        "models": interfaces["models"],
        "interfaces": variants,
        "repetitions": repetitions,
        "total_task_runs": runs_per_model * len(interfaces["models"]),
        "expected_model_requests": sum(row["expected_model_requests"] for row in providers),
        "conservative_model_requests": sum(row["conservative_model_requests"] for row in providers),
        "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in providers),
        "estimated_output_tokens": sum(row["estimated_output_tokens"] for row in providers),
        "estimated_total_tokens": sum(row["estimated_total_tokens"] for row in providers),
        "providers": providers,
        "estimated_total_cost_usd": total_cost,
        "guarded_total_cost_usd": total_cost * 1.25,
        "configured_cost_cap_usd": min(settings.phase15_max_cost_usd, 5.0),
        "automatic_launch_allowed": total_cost * 1.25 <= min(settings.phase15_max_cost_usd, 5.0),
        "pricing": pricing_manifest(interfaces["models"]),
        "method": (
            "Calibration-B input/output and tool-call averages, plus per-request frozen-interface "
            "description-token deltas; 25% guard band."
        ),
    }
    (R2_ROOT / "sealed_holdout_cost_estimate.json").write_text(
        json.dumps(estimate, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(estimate, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
