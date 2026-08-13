from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .models import Experiment


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _svg_bar_chart(
    path: Path,
    title: str,
    labels: list[str],
    values: list[float],
    y_label: str,
    maximum: float | None = None,
) -> None:
    width = 960
    row_height = 30
    height = max(220, 110 + row_height * len(labels))
    maximum = maximum or max([abs(value) for value in values] or [1.0]) or 1.0
    plot_width = 600
    lower = -maximum if any(value < 0 for value in values) else 0.0
    upper = maximum
    span = upper - lower
    zero_x = 300 + (-lower / span) * plot_width
    rows = []
    for index, (label, value) in enumerate(zip(labels, values, strict=True)):
        y = 75 + index * row_height
        value_x = 300 + ((max(lower, min(upper, value)) - lower) / span) * plot_width
        bar_x = min(zero_x, value_x)
        bar_width = abs(value_x - zero_x)
        label_x = value_x + 5 if value >= 0 else value_x - 58
        rows.append(
            f'<text x="15" y="{y + 16}" font-size="12">{html.escape(label[:42])}</text>'
            f'<rect x="{bar_x:.1f}" y="{y}" width="{bar_width:.1f}" height="19" fill="#2563eb" />'
            f'<text x="{label_x:.1f}" y="{y + 15}" font-size="12">{value:.3f}</text>'
        )
    path.write_text(
        "\n".join(
            [
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img">',
                '<rect width="100%" height="100%" fill="white"/>',
                f'<text x="15" y="28" font-size="20" font-weight="bold">{html.escape(title)}</text>',
                f'<text x="300" y="54" font-size="12">{html.escape(y_label)}</text>',
                f'<line x1="{zero_x:.1f}" y1="65" x2="{zero_x:.1f}" y2="{height - 20}" stroke="#111" stroke-width="1"/>',
                *rows,
                "</svg>",
            ]
        ),
        encoding="utf-8",
    )


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _aggregate_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Model | Split | Interface | Success | Tool selection | Arguments | Calls | Latency ms | Tokens | Cost | n |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {model} | {task_split} | {variant} | {success} | {tool} | {args} | "
            "{calls:.2f} | {latency:.1f} | {tokens:.1f} | ${cost:.4f} | {n} |".format(
                model=row["model"],
                task_split=row["task_split"],
                variant=row["variant"],
                success=_percent(row["task_success_rate"]),
                tool=_percent(row["tool_selection_accuracy"]),
                args=_percent(row["argument_accuracy"]),
                calls=row["average_tool_calls"],
                latency=row["average_latency_ms"],
                tokens=row["average_tokens"],
                cost=row["estimated_cost"],
                n=row["sample_size"],
            )
        )
    return "\n".join(lines)


def _comparison_table(rows: list[dict[str, Any]], variants: set[str]) -> str:
    filtered = [row for row in rows if row["variant"] in variants]
    lines = [
        "| Model | Split | Variant vs baseline | Effect | 95% cluster-bootstrap CI | p | Tasks | Regressions |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in filtered:
        low, high = row["confidence_interval"]
        p_value = row.get("p_value")
        lines.append(
            f"| {row['model']} | {row['task_split']} | {row['variant']} | "
            f"{_percent(row['absolute_difference'])} | [{_percent(low)}, {_percent(high)}] | "
            f"{p_value:.4f} | {row['sample_size_tasks']} | {row['regression_count']} |"
            if p_value is not None
            else f"| {row['model']} | {row['task_split']} | {row['variant']} | "
            f"{_percent(row['absolute_difference'])} | [{_percent(low)}, {_percent(high)}] | n/a | "
            f"{row['sample_size_tasks']} | {row['regression_count']} |"
        )
    return "\n".join(lines) if filtered else "No paired real-model comparisons were available."


def generate_report(
    experiment: Experiment,
    analysis: dict[str, Any],
    output_dir: Path | None = None,
) -> tuple[Path, Path, list[Path]]:
    root = _repo_root()
    output_dir = output_dir or root / "reports"
    chart_dir = output_dir / "phase15_charts"
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_dir.mkdir(parents=True, exist_ok=True)
    aggregates = analysis.get("aggregates", [])
    comparisons = analysis.get("comparisons", [])

    chart_specs = [
        (
            "task_success_by_interface_model.svg",
            "Task success by interface and model",
            [f"{row['model']} / {row['task_split']} / {row['variant']}" for row in aggregates],
            [float(row["task_success_rate"]) for row in aggregates],
            "success rate",
            1.0,
        ),
        (
            "baseline_degraded_optimized.svg",
            "Baseline vs degraded vs optimized",
            [
                f"{row['model']} / {row['variant']}"
                for row in aggregates
                if row["variant"] in {"baseline", "degraded", "optimized"}
            ],
            [
                float(row["task_success_rate"])
                for row in aggregates
                if row["variant"] in {"baseline", "degraded", "optimized"}
            ],
            "success rate",
            1.0,
        ),
        (
            "failure_distribution.svg",
            "Failure-category distribution",
            [
                f"{row['variant']} / {row['failure_category']}"
                for row in analysis.get("failure_analysis", [])
            ],
            [float(row["rate"]) for row in analysis.get("failure_analysis", [])],
            "failure rate",
            1.0,
        ),
        (
            "interface_lift_by_model.svg",
            "Interface lift by model",
            [f"{row['model']} / {row['task_split']} / {row['variant']}" for row in comparisons],
            [float(row["absolute_difference"]) for row in comparisons],
            "absolute success-rate difference",
            max([abs(float(row["absolute_difference"])) for row in comparisons] or [1.0]),
        ),
        (
            "interface_lift_by_difficulty.svg",
            "Interface lift by task difficulty",
            [
                f"difficulty {row['difficulty']} / {row['variant']}"
                for row in analysis.get("difficulty_lifts", [])
            ],
            [float(row["absolute_difference"]) for row in analysis.get("difficulty_lifts", [])],
            "absolute success-rate difference",
            max(
                [
                    abs(float(row["absolute_difference"]))
                    for row in analysis.get("difficulty_lifts", [])
                ]
                or [1.0]
            ),
        ),
        (
            "cross_model_variant_preference.svg",
            "Cross-model variant preference",
            [f"{row['model']} / {row['variant']}" for row in comparisons],
            [float(row["absolute_difference"]) for row in comparisons],
            "lift over baseline",
            max([abs(float(row["absolute_difference"])) for row in comparisons] or [1.0]),
        ),
        (
            "token_cost_vs_success.svg",
            "Token cost versus task success (success shown; labels include cost)",
            [f"{row['variant']} (${row['estimated_cost']:.4f})" for row in aggregates],
            [float(row["task_success_rate"]) for row in aggregates],
            "success rate",
            1.0,
        ),
    ]
    charts = []
    for filename, title, labels, values, y_label, maximum in chart_specs:
        path = chart_dir / filename
        _svg_bar_chart(
            path, title, labels or ["No observations"], values or [0.0], y_label, maximum
        )
        charts.append(path)

    real_models = sorted({row["model"] for row in aggregates if not row.get("synthetic")})
    synthetic_models = sorted({row["model"] for row in aggregates if row.get("synthetic")})
    unavailable = experiment.configuration.get("unavailable_providers", [])
    decision = analysis["decision"]
    reasons = analysis.get("decision_reasons", [])
    manifest_path = root / "data" / "phase15" / "experiment_manifest.json"
    dataset_path = root / "data" / "phase15" / "experiment_results.jsonl"
    markdown = (
        f"""# AgentSEO Phase 1.5 Experimental Validation

## Executive Summary

**Decision: {decision}**

{analysis.get("executive_summary", "No valid real-model evidence was available.")}

"""
        + "\n".join(f"- {reason}" for reason in reasons)
        + f"""

Mock-agent observations are system-validation data only and are excluded from claims about RQ1–RQ6.

## Experimental Setup

- Experiment ID: `{experiment.id}`
- Hypothesis: {experiment.hypothesis}
- Domains: {", ".join(analysis.get("domains", [])) or "none"}
- Real models run: {", ".join(real_models) or "none"}
- Synthetic system-test models: {", ".join(synthetic_models) or "none"}
- Unavailable/skipped providers: {", ".join(unavailable) or "none"}
- Variants: {", ".join(analysis.get("variants", []))}
- Repetitions: {experiment.repetitions}
- Development/hidden split: 70/30, seed {experiment.task_split_seed}
- Temperature: {experiment.configuration.get("temperature")}
- Estimated pre-run cost: ${experiment.estimated_cost:.4f}
- Actual recorded model cost: ${experiment.actual_cost:.4f}
- Statistical method: paired task-cluster bootstrap; exact McNemar on task-majority outcomes. P-values are exploratory.

## Results

{_aggregate_table(aggregates)}

![Task success by interface and model](phase15_charts/task_success_by_interface_model.svg)

## Interface Lift

{_comparison_table(comparisons, {"optimized", "concise", "verbose", "negative", "examples", "reduced"})}

![Interface lift by model](phase15_charts/interface_lift_by_model.svg)

## Degradation Validation

{_comparison_table(comparisons, {"degraded"})}

![Baseline, degraded, optimized](phase15_charts/baseline_degraded_optimized.svg)

## Hidden Test Results

Hidden outcomes were not used to construct V2. V2 is frozen before the hidden matrix begins.

{_comparison_table([row for row in comparisons if row["task_split"] == "hidden"], set(analysis.get("variants", [])))}

## Failure Analysis

Failure rates are descriptive. They map interface conditions to observed mechanisms but do not establish causality without isolated-mutation evidence.

"""
        + (
            "\n".join(
                f"- {row['variant']} / {row['failure_category']}: {_percent(row['rate'])} ({row['count']}/{row['sample_size']})"
                for row in analysis.get("failure_analysis", [])
            )
            or "No failures were observed in the locally runnable system-validation matrix."
        )
        + """

![Failure distribution](phase15_charts/failure_distribution.svg)

### Failure rate by mutation type

"""
        + (
            "\n".join(
                f"- {row['mutation_type']} / {row['failure_category']}: {_percent(row['rate'])} ({row['count']}/{row['sample_size']})"
                for row in analysis.get("mutation_failure_analysis", [])
            )
            or "No mutation-associated failures were observed in the locally runnable matrix."
        )
        + f"""

## Mutation Attribution

{_comparison_table(comparisons, {"isolated_tool_rename", "isolated_description_reduction", "isolated_parameter_rename", "isolated_negative_removal"})}

## Cross-Model Effects

"""
        + (
            "\n".join(
                f"- `MODEL_SPECIFIC_INTERFACE_EFFECT`: {effect['variant']} ({effect['model_lifts']})"
                for effect in analysis.get("model_specific_effects", [])
            )
            or "No model-specific effect can be established without at least two real model families."
        )
        + """

Cross-model success-rate variance:

"""
        + (
            "\n".join(
                f"- {row['variant']} / {row['task_split']}: variance {row['variance']:.5f}, range {_percent(row['range'])}, models {row['model_count']}"
                for row in analysis.get("cross_model_variance", [])
            )
            or "Not estimable without real observations from at least two model families."
        )
        + f"""

![Cross-model preference](phase15_charts/cross_model_variant_preference.svg)

## Interface Lift by Difficulty

![Lift by difficulty](phase15_charts/interface_lift_by_difficulty.svg)

## Cost / Performance Tradeoff

![Token cost versus success](phase15_charts/token_cost_vs_success.svg)

Richer interfaces may increase prompt tokens. The table and chart report this tradeoff; synthetic zero-cost runs must not be extrapolated to provider billing.

## Statistical Confidence

Confidence intervals resample paired tasks as clusters, preserving repeated trials within each task. Exact McNemar tests operate on task-majority outcomes. Small samples, deterministic runs, and multiple exploratory comparisons limit inference; a p-value alone is not treated as proof.

## Reproducibility

- Manifest: `{manifest_path.relative_to(root).as_posix()}`
- JSONL dataset: `{dataset_path.relative_to(root).as_posix()}`
- Git commit and exact model identifiers are captured in the manifest.
- External providers may change behavior even with the same identifier.

## Limitations

- Only three resettable synthetic sandbox domains are in scope.
- Tasks are synthetic and may not reflect production distributions.
- The evaluator measures specified final state and tool constraints, not every aspect of response quality.
- Model APIs and aliases may change over time.
- Tool-routing V7 uses benchmark-known task groups and must be interpreted separately from ungated interfaces.
- The checked-in local study contains no real-provider evidence when provider keys are unavailable.
- Mock agents use benchmark context and are suitable only for runner/mapping validation.
- Multiple comparisons are exploratory and are not corrected for family-wise error.

## GO / NO-GO Decision

# {decision}

"""
        + "\n".join(f"- {reason}" for reason in reasons)
        + "\n"
    )

    markdown_path = output_dir / "phase_1_5_results.md"
    html_path = output_dir / "phase_1_5_results.html"
    markdown_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>AgentSEO Phase 1.5</title>"
        "<style>body{font-family:system-ui;max-width:1100px;margin:2rem auto;line-height:1.5}"
        "pre{white-space:pre-wrap}img{max-width:100%}</style></head><body>"
        + "".join(
            f"<img src='phase15_charts/{chart.name}' alt='{html.escape(chart.stem)}'>"
            for chart in charts
        )
        + f"<pre>{html.escape(markdown)}</pre></body></html>",
        encoding="utf-8",
    )
    return markdown_path, html_path, charts
