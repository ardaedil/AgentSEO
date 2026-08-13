from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any


def proportion_confidence_interval(
    outcomes: list[bool], confidence: float = 0.95
) -> tuple[float, float]:
    """Wilson interval for a single binary proportion."""

    if not outcomes:
        return 0.0, 0.0
    z = 1.959963984540054 if confidence == 0.95 else 1.959963984540054
    n = len(outcomes)
    estimate = sum(outcomes) / n
    denominator = 1 + z * z / n
    center = (estimate + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(estimate * (1 - estimate) / n + z * z / (4 * n * n))
    margin /= denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def clustered_bootstrap_difference(
    baseline: dict[str, list[bool]],
    treatment: dict[str, list[bool]],
    samples: int = 2000,
    seed: int = 42,
) -> tuple[float, float]:
    """Bootstrap paired task clusters, preserving repeated trials within each task."""

    task_ids = sorted(set(baseline) & set(treatment))
    if not task_ids:
        return 0.0, 0.0
    differences = [
        sum(treatment[task_id]) / len(treatment[task_id])
        - sum(baseline[task_id]) / len(baseline[task_id])
        for task_id in task_ids
    ]
    randomizer = random.Random(seed)
    bootstrapped = []
    for _ in range(max(samples, 100)):
        draw = [randomizer.choice(differences) for _ in differences]
        bootstrapped.append(sum(draw) / len(draw))
    bootstrapped.sort()
    low_index = int(0.025 * (len(bootstrapped) - 1))
    high_index = int(0.975 * (len(bootstrapped) - 1))
    return bootstrapped[low_index], bootstrapped[high_index]


def mcnemar_exact(baseline: list[bool], treatment: list[bool]) -> dict[str, Any]:
    """Two-sided exact McNemar test for paired binary observations."""

    if len(baseline) != len(treatment):
        raise ValueError("McNemar outcomes must be paired")
    baseline_only = sum(left and not right for left, right in zip(baseline, treatment, strict=True))
    treatment_only = sum(
        right and not left for left, right in zip(baseline, treatment, strict=True)
    )
    discordant = baseline_only + treatment_only
    if discordant == 0:
        p_value = 1.0
    else:
        smaller = min(baseline_only, treatment_only)
        tail = sum(math.comb(discordant, index) for index in range(smaller + 1)) / (2**discordant)
        p_value = min(1.0, 2 * tail)
    return {
        "baseline_only_success": baseline_only,
        "treatment_only_success": treatment_only,
        "discordant_pairs": discordant,
        "p_value": p_value,
    }


def paired_binary_comparison(
    baseline_observations: list[dict[str, Any]],
    treatment_observations: list[dict[str, Any]],
    bootstrap_samples: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Compare variants using task-cluster bootstrap and task-level McNemar.

    Repeated trials are averaged inside task clusters for the effect and confidence
    interval. McNemar uses majority outcome per task, avoiding a false claim that
    repeated observations from one task are independent.
    """

    baseline: dict[str, list[bool]] = defaultdict(list)
    treatment: dict[str, list[bool]] = defaultdict(list)
    for item in baseline_observations:
        baseline[str(item["task_id"])].append(bool(item["success"]))
    for item in treatment_observations:
        treatment[str(item["task_id"])].append(bool(item["success"]))
    tasks = sorted(set(baseline) & set(treatment))
    if not tasks:
        return {
            "absolute_difference": 0.0,
            "relative_difference": None,
            "confidence_interval": [0.0, 0.0],
            "p_value": None,
            "sample_size_tasks": 0,
            "sample_size_observations": 0,
            "regression_count": 0,
        }
    baseline_rate = sum(sum(baseline[task]) / len(baseline[task]) for task in tasks) / len(tasks)
    treatment_rate = sum(sum(treatment[task]) / len(treatment[task]) for task in tasks) / len(tasks)
    absolute = treatment_rate - baseline_rate
    low, high = clustered_bootstrap_difference(
        baseline, treatment, samples=bootstrap_samples, seed=seed
    )
    baseline_majority = [sum(baseline[task]) / len(baseline[task]) >= 0.5 for task in tasks]
    treatment_majority = [sum(treatment[task]) / len(treatment[task]) >= 0.5 for task in tasks]
    mcnemar = mcnemar_exact(baseline_majority, treatment_majority)
    return {
        "baseline_rate": baseline_rate,
        "treatment_rate": treatment_rate,
        "absolute_difference": absolute,
        "relative_difference": absolute / baseline_rate if baseline_rate else None,
        "confidence_interval": [low, high],
        "p_value": mcnemar["p_value"],
        "mcnemar": mcnemar,
        "sample_size_tasks": len(tasks),
        "sample_size_observations": sum(len(baseline[task]) for task in tasks)
        + sum(len(treatment[task]) for task in tasks),
        "regression_count": sum(
            sum(treatment[task]) / len(treatment[task]) < sum(baseline[task]) / len(baseline[task])
            for task in tasks
        ),
        "method": "paired task-cluster bootstrap; exact McNemar on task-majority outcomes",
        "exploratory": True,
    }


def flag_model_specific_effects(
    lifts: list[dict[str, Any]], threshold: float = 0.10
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in lifts:
        grouped[(str(item["variant"]), str(item.get("task_split", "all")))].append(item)
    effects = []
    for (variant, split), rows in grouped.items():
        if len(rows) < 2:
            continue
        values = [float(row["absolute_difference"]) for row in rows]
        if max(values) - min(values) >= threshold:
            effects.append(
                {
                    "result_type": "MODEL_SPECIFIC_INTERFACE_EFFECT",
                    "variant": variant,
                    "task_split": split,
                    "range": max(values) - min(values),
                    "model_lifts": {
                        str(row["model"]): float(row["absolute_difference"]) for row in rows
                    },
                    "exploratory": True,
                }
            )
    return effects
