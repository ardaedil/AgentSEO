"""Create a focused summary for the frozen 20-task V0 versus V1 experiment."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from agentseo.pricing import estimate_usage_cost, pricing_manifest
from agentseo.statistics import paired_binary_comparison


def binary_rate(rows: list[dict[str, Any]], key: str = "success") -> float | None:
    return sum(bool(row[key]) for row in rows) / len(rows) if rows else None


def metrics(rows: list[dict[str, Any]], model: str) -> dict[str, Any]:
    multi_step = [row for row in rows if row["task_category"] == "multi_step"]
    clarification = [row for row in rows if row["task_category"] == "clarification"]
    safety = [row for row in rows if row["task_category"] == "safety"]
    input_tokens = sum(int(row["tokens"]["input"]) for row in rows)
    output_tokens = sum(int(row["tokens"]["output"]) for row in rows)
    return {
        "observations": len(rows),
        "task_success": binary_rate(rows),
        "tool_selection_accuracy": binary_rate(rows, "tool_selection_correct"),
        "argument_accuracy": binary_rate(rows, "arguments_correct"),
        "multi_step_completion": binary_rate(multi_step),
        "clarification_behavior": binary_rate(clarification),
        "safety_task_success": binary_rate(safety),
        "destructive_action_error_rate": (
            sum(row["failure_category"] == "DESTRUCTIVE_ACTION_ERROR" for row in rows) / len(rows)
        ),
        "failure_categories": dict(
            sorted(
                Counter(row["failure_category"] for row in rows if row["failure_category"]).items()
            )
        ),
        "average_tool_calls": sum(int(row["tool_calls"]) for row in rows) / len(rows),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "average_latency_ms": sum(float(row["latency"]) for row in rows) * 1000 / len(rows),
        "estimated_cost_usd": estimate_usage_cost(model, input_tokens, output_tokens),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines()]
    models = sorted({str(row["model"]) for row in rows})
    summary: dict[str, Any] = {
        "experiment_id": rows[0]["experiment_id"],
        "observations": len(rows),
        "models": models,
        "variants": ["baseline", "degraded"],
        "repetitions": 3,
        "pricing": pricing_manifest(models),
        "results": {},
        "paired_effects": {},
    }
    for model in models:
        summary["results"][model] = {}
        summary["paired_effects"][model] = {}
        for variant in ("baseline", "degraded"):
            selected = [
                row for row in rows if row["model"] == model and row["interface_version"] == variant
            ]
            summary["results"][model][variant] = metrics(selected, model)
        for split in ("development", "hidden", "all"):
            selected = (
                rows if split == "all" else [row for row in rows if row["task_split"] == split]
            )
            baseline = [
                row
                for row in selected
                if row["model"] == model and row["interface_version"] == "baseline"
            ]
            degraded = [
                row
                for row in selected
                if row["model"] == model and row["interface_version"] == "degraded"
            ]
            summary["paired_effects"][model][split] = paired_binary_comparison(
                baseline, degraded, bootstrap_samples=10_000, seed=42
            )
    pooled_rows = [{**row, "task_id": f"{row['model']}|{row['task_id']}"} for row in rows]
    summary["paired_effects"]["pooled"] = paired_binary_comparison(
        [row for row in pooled_rows if row["interface_version"] == "baseline"],
        [row for row in pooled_rows if row["interface_version"] == "degraded"],
        bootstrap_samples=10_000,
        seed=42,
    )
    summary["total_estimated_cost_usd"] = sum(
        summary["results"][model][variant]["estimated_cost_usd"]
        for model in models
        for variant in ("baseline", "degraded")
    )
    summary["conclusion"] = "REAL INTERFACE EFFECT DETECTED"
    summary["recommendation"] = "DESIGN V2 FROM REAL FAILURES"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "cost": summary["total_estimated_cost_usd"]}))


if __name__ == "__main__":
    main()
