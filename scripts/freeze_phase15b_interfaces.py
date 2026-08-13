"""Freeze exact Phase 1.5B human interfaces without reading holdout task content."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from agentseo.database import SessionLocal
from agentseo.interfaces import create_interface_variant, interface_features
from agentseo.models import (
    Experiment,
    InterfaceMutation,
    InterfaceVersion,
    MutationGeneratedBy,
    Project,
    TaskRun,
)
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "artifacts" / "phase15b" / "frozen_interfaces"
EXPERIMENT_ID = "34b3f5ef-52b3-4ce8-868c-82c2d7324ea0"
VARIANTS = (
    "baseline",
    "phase15b_general",
    "phase15b_gpt",
    "phase15b_claude",
    "phase15b_gemini",
)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def complexity(snapshot: list[dict[str, Any]]) -> dict[str, Any]:
    features = interface_features(snapshot)
    return {
        key: features[key]
        for key in (
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
    }


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    source_commit = git_commit()
    with SessionLocal() as session:
        experiment = session.get(Experiment, EXPERIMENT_ID)
        if experiment is None:
            raise RuntimeError(f"Missing Stage A experiment {EXPERIMENT_ID}")
        holdout_runs = session.scalar(
            select(func.count(TaskRun.id)).where(
                TaskRun.experiment_id == EXPERIMENT_ID,
                TaskRun.task_split == "holdout",
            )
        )
        if holdout_runs:
            raise RuntimeError("Holdout observations exist; refusing to freeze variants after evaluation")
        projects = list(session.scalars(select(Project).order_by(Project.sandbox_domain)))
        if {project.sandbox_domain for project in projects} != {"billing", "crm", "ecommerce"}:
            raise RuntimeError("Expected exactly the three Phase 1.5B domains")
        domain_by_project_id = {project.id: project.sandbox_domain for project in projects}
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
                        experiment_id=EXPERIMENT_ID,
                        generated_by=MutationGeneratedBy.HUMAN,
                    )
                )
        session.commit()

        manifest_rows = []
        ledger_rows = []
        for interface in sorted(
            interfaces,
            key=lambda item: (
                domain_by_project_id[item.project_id],
                VARIANTS.index(item.variant_key),
            ),
        ):
            interface_project = session.get(Project, interface.project_id)
            if interface_project is None:
                raise RuntimeError("Interface references a missing project")
            domain_root = OUTPUT_ROOT / interface_project.sandbox_domain
            domain_root.mkdir(parents=True, exist_ok=True)
            snapshot_payload = {
                "domain": interface_project.sandbox_domain,
                "interface_id": interface.id,
                "interface_name": interface.name,
                "variant_key": interface.variant_key,
                "frozen": interface.frozen,
                "source_git_commit": source_commit,
                "tool_definitions_snapshot": interface.tool_definitions_snapshot,
            }
            snapshot_hash = canonical_hash(snapshot_payload)
            snapshot_path = domain_root / f"{interface.variant_key}.json"
            snapshot_path.write_text(
                json.dumps(snapshot_payload, indent=2, sort_keys=True), encoding="utf-8"
            )
            manifest_rows.append(
                {
                    "domain": interface_project.sandbox_domain,
                    "interface_id": interface.id,
                    "variant_key": interface.variant_key,
                    "snapshot_sha256": snapshot_hash,
                    "snapshot_path": str(snapshot_path.relative_to(ROOT)).replace("\\", "/"),
                    "complexity": complexity(interface.tool_definitions_snapshot),
                }
            )
            for mutation in session.scalars(
                select(InterfaceMutation).where(
                    InterfaceMutation.interface_version_id == interface.id
                )
            ):
                ledger_rows.append(
                    {
                        "domain": interface_project.sandbox_domain,
                        "variant_key": interface.variant_key,
                        "mutation": mutation.mutation_type,
                        "target_tool": mutation.target_tool_id,
                        "target_field": mutation.target_field,
                        "before": mutation.before_value,
                        "after": mutation.after_value,
                        "observed_failure_and_hypothesis": mutation.rationale,
                        "affected_model": interface.variant_key.removeprefix("phase15b_")
                        if interface.variant_key != "phase15b_general"
                        else "all",
                        "expected_benefit": "Improve the cited development failure pattern.",
                        "possible_regression_risk": (
                            "Additional instruction tokens may distract or over-constrain models; "
                            "the sealed holdout must measure this."
                        ),
                        "generated_by": mutation.generated_by,
                    }
                )
        manifest = {
            "protocol": "AgentSEO Phase 1.5B pre-holdout interface freeze",
            "immutable": True,
            "source_git_commit": source_commit,
            "stage_a_experiment_id": EXPERIMENT_ID,
            "holdout_task_runs_at_freeze": 0,
            "models": experiment.models,
            "request_configuration": {
                "temperature": experiment.configuration.get("temperature"),
                "max_iterations": experiment.configuration.get("max_iterations"),
                "max_tool_calls": experiment.configuration.get("max_tool_calls"),
                "provider_seed": experiment.configuration.get("provider_seed"),
                "anthropic_sampling_note": "temperature omitted for claude-sonnet-5",
            },
            "variants": list(VARIANTS),
            "interfaces": manifest_rows,
        }
        manifest["freeze_manifest_sha256"] = canonical_hash(manifest)
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
                    "freeze_manifest_sha256": manifest["freeze_manifest_sha256"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
