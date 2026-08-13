"""Freeze R2 human-designed interfaces without reading sealed holdout task content."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from agentseo.database import SessionLocal
from agentseo.interfaces import create_interface_variant, interface_features
from agentseo.models import (
    BenchmarkTask,
    Experiment,
    InterfaceMutation,
    InterfaceVersion,
    MutationGeneratedBy,
    Project,
    TaskRun,
)
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "artifacts" / "phase15b_r2" / "frozen_interfaces"
BENCHMARK_ROOT = ROOT / "artifacts" / "phase15b_r2" / "frozen_benchmark"
VARIANTS = (
    "baseline",
    "phase15b_r2_general",
    "phase15b_r2_gpt",
    "phase15b_r2_claude",
    "phase15b_r2_gemini",
)


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _complexity(snapshot: list[dict[str, Any]]) -> dict[str, Any]:
    features = interface_features(snapshot)
    keys = (
        "number_of_tools",
        "total_description_tokens",
        "average_description_length",
        "number_of_examples",
        "number_of_negative_instructions",
        "number_of_clarification_instructions",
        "number_of_recovery_instructions",
        "mean_semantic_overlap_jaccard",
        "max_semantic_overlap_jaccard",
    )
    return {key: features[key] for key in keys}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("calibration_experiment_id")
    args = parser.parse_args()
    benchmark_manifest = json.loads(
        (BENCHMARK_ROOT / "protocol_manifest.json").read_text(encoding="utf-8")
    )
    holdout_manifest = json.loads(
        (BENCHMARK_ROOT / "holdout_manifest.json").read_text(encoding="utf-8")
    )
    if holdout_manifest.get("state") != "SEALED_UNOPENED":
        raise RuntimeError("R2 holdout is not sealed and unopened")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as session:
        experiment = session.get(Experiment, args.calibration_experiment_id)
        if experiment is None or experiment.status != "COMPLETED":
            raise RuntimeError("Completed R2 Calibration B experiment required")
        holdout_runs = int(
            session.scalar(
                select(func.count(TaskRun.id))
                .join(BenchmarkTask, TaskRun.task_id == BenchmarkTask.id)
                .where(BenchmarkTask.phase15_split == "holdout")
            )
            or 0
        )
        if holdout_runs:
            raise RuntimeError("Holdout observations exist; refusing post-outcome interface freeze")
        projects = list(session.scalars(select(Project).order_by(Project.sandbox_domain)))
        if {project.sandbox_domain for project in projects} != {"billing", "crm", "ecommerce"}:
            raise RuntimeError("Expected the three R2 domains")
        domain_by_project = {project.id: project.sandbox_domain for project in projects}
        interfaces: list[InterfaceVersion] = []
        for project in projects:
            baseline = session.scalar(
                select(InterfaceVersion).where(
                    InterfaceVersion.project_id == project.id,
                    InterfaceVersion.variant_key == "baseline",
                )
            )
            if baseline is None:
                raise RuntimeError(f"Missing baseline for {project.sandbox_domain}")
            baseline.frozen = True
            interfaces.append(baseline)
            for variant in VARIANTS[1:]:
                interfaces.append(
                    create_interface_variant(
                        session,
                        project,
                        baseline,
                        variant,
                        experiment_id=experiment.id,
                        generated_by=MutationGeneratedBy.HUMAN,
                    )
                )
        session.commit()

        manifest_rows: list[dict[str, Any]] = []
        ledger_rows: list[dict[str, Any]] = []
        for interface in sorted(
            interfaces,
            key=lambda item: (domain_by_project[item.project_id], VARIANTS.index(item.variant_key)),
        ):
            domain = domain_by_project[interface.project_id]
            domain_root = OUTPUT_ROOT / domain
            domain_root.mkdir(parents=True, exist_ok=True)
            payload = {
                "domain": domain,
                "interface_id": interface.id,
                "interface_name": interface.name,
                "variant_key": interface.variant_key,
                "frozen": interface.frozen,
                "source_git_commit": _git_commit(),
                "tool_definitions_snapshot": interface.tool_definitions_snapshot,
            }
            snapshot_hash = _hash(payload)
            path = domain_root / f"{interface.variant_key}.json"
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            manifest_rows.append(
                {
                    "domain": domain,
                    "interface_id": interface.id,
                    "variant_key": interface.variant_key,
                    "snapshot_sha256": snapshot_hash,
                    "snapshot_path": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "complexity": _complexity(interface.tool_definitions_snapshot),
                }
            )
            for mutation in session.scalars(
                select(InterfaceMutation).where(
                    InterfaceMutation.interface_version_id == interface.id
                )
            ):
                ledger_rows.append(
                    {
                        "domain": domain,
                        "variant_key": interface.variant_key,
                        "mutation": mutation.mutation_type,
                        "target_tool": mutation.target_tool_id,
                        "target_field": mutation.target_field,
                        "before": mutation.before_value,
                        "after": mutation.after_value,
                        "r2_observed_failure_and_hypothesis": mutation.rationale,
                        "affected_model": (
                            "all"
                            if interface.variant_key == "phase15b_r2_general"
                            else interface.variant_key.removeprefix("phase15b_r2_")
                        ),
                        "expected_benefit": "Reduce the cited R2 development failure mechanism.",
                        "possible_regression_risk": (
                            "Extra constraints may cause premature stopping or distract from multi-step work; "
                            "the sealed holdout must measure transfer and regressions."
                        ),
                        "generated_by": mutation.generated_by,
                    }
                )

        variant_hashes = {
            variant: _hash(
                [
                    {"domain": row["domain"], "snapshot_sha256": row["snapshot_sha256"]}
                    for row in manifest_rows
                    if row["variant_key"] == variant
                ]
            )
            for variant in VARIANTS
        }
        manifest = {
            "protocol": "PHASE15B_R2_HARD_BENCHMARK_PRE_HOLDOUT_INTERFACE_FREEZE",
            "immutable": True,
            "source_git_commit": _git_commit(),
            "calibration_experiment_id": experiment.id,
            "benchmark_sha256": benchmark_manifest["benchmark_sha256"],
            "holdout_manifest_sha256": holdout_manifest["holdout_manifest_sha256"],
            "holdout_task_runs_at_freeze": 0,
            "development_evidence_only": True,
            "models": experiment.models,
            "request_configuration": {
                "temperature": experiment.configuration.get("temperature"),
                "max_iterations": experiment.configuration.get("max_iterations"),
                "max_tool_calls": experiment.configuration.get("max_tool_calls"),
                "provider_seed": experiment.configuration.get("provider_seed"),
                "anthropic_sampling_note": "temperature omitted for claude-sonnet-5",
            },
            "variants": list(VARIANTS),
            "variant_sha256": variant_hashes,
            "interfaces": manifest_rows,
        }
        manifest["interface_freeze_sha256"] = _hash(manifest)
        (OUTPUT_ROOT / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        (OUTPUT_ROOT / "mutation_ledger.json").write_text(
            json.dumps(ledger_rows, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "frozen_interfaces": len(manifest_rows),
                    "mutations": len(ledger_rows),
                    "holdout_task_runs": 0,
                    "variant_sha256": variant_hashes,
                    "interface_freeze_sha256": manifest["interface_freeze_sha256"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
