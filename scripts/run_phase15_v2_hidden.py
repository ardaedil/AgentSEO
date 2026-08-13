"""Run the frozen, paired V0 versus manual-V2 hidden evaluation only."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from agentseo.config import get_settings
from agentseo.database import SessionLocal, create_schema
from agentseo.experiments import (
    Phase15Configuration,
    analyze_experiment,
    assign_task_split,
    estimate_experiment_cost,
    resolve_models,
    run_phase15_experiment,
)
from agentseo.interfaces import create_interface_variant, mutate_snapshot
from agentseo.models import (
    BenchmarkTask,
    InterfaceMutation,
    InterfaceVersion,
    MutationGeneratedBy,
    Project,
    ToolDefinition,
)
from agentseo.openapi_parser import parse_openapi
from agentseo.reporting import generate_report
from agentseo.research_export import export_experiment_dataset
from agentseo.task_generation import generate_template_tasks
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
HIDDEN_TASKS = {
    "billing": {"Find unpaid invoice", "Locate a billing customer by email"},
    "ecommerce": {"Locate a shopper by email", "List failed deliveries"},
    "crm": {"Locate a company by name", "Assign one sales opportunity"},
}


def _sha256(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def seed_and_freeze_v2(split_seed: int) -> tuple[list[str], dict[str, object]]:
    project_ids: list[str] = []
    frozen_domains: dict[str, object] = {}
    with SessionLocal() as session:
        for domain, titles in HIDDEN_TASKS.items():
            _, tools = parse_openapi((ROOT / "examples" / domain / "openapi.yaml").read_bytes())
            snapshot, _ = mutate_snapshot([tool.to_dict() for tool in tools], "baseline")
            project = Project(
                name=f"Phase 1.5 frozen V0 versus V2 hidden evaluation — {domain}",
                description="Fresh temporally paired hidden evaluation; no development tasks included",
                sandbox_domain=domain,
            )
            session.add(project)
            session.flush()
            session.add_all([ToolDefinition(project_id=project.id, **tool) for tool in snapshot])
            baseline = InterfaceVersion(
                project_id=project.id,
                version=1,
                tool_definitions_snapshot=snapshot,
                name="V0 — Canonical baseline",
                variant_key="baseline",
                frozen=True,
            )
            session.add(baseline)
            session.flush()
            generated = generate_template_tasks(tools, domain)
            selected = [task for task in generated if task.title in titles]
            if {task.title for task in selected} != titles:
                missing = titles - {task.title for task in selected}
                raise RuntimeError(f"Missing hidden tasks for {domain}: {sorted(missing)}")
            session.add_all(
                [BenchmarkTask(project_id=project.id, **task.to_dict()) for task in selected]
            )
            optimized = create_interface_variant(
                session,
                project,
                baseline,
                "optimized",
                generated_by=MutationGeneratedBy.HUMAN,
            )
            mutations = list(
                session.scalars(
                    select(InterfaceMutation).where(
                        InterfaceMutation.interface_version_id == optimized.id
                    )
                )
            )
            frozen_domains[domain] = {
                "baseline_interface_id": baseline.id,
                "baseline_snapshot_sha256": _sha256(baseline.tool_definitions_snapshot),
                "v2_interface_id": optimized.id,
                "v2_snapshot_sha256": _sha256(optimized.tool_definitions_snapshot),
                "v2_frozen": optimized.frozen,
                "mutation_count": len(mutations),
                "mutations_sha256": _sha256(
                    [
                        {
                            "type": item.mutation_type,
                            "tool": item.target_tool_id,
                            "field": item.target_field,
                            "before": item.before_value,
                            "after": item.after_value,
                            "rationale": item.rationale,
                            "generated_by": item.generated_by,
                        }
                        for item in mutations
                    ]
                ),
            }
            project_ids.append(project.id)
        tasks = list(
            session.scalars(select(BenchmarkTask).where(BenchmarkTask.project_id.in_(project_ids)))
        )
        splits = assign_task_split(tasks, split_seed)
        if set(splits.values()) != {"hidden"}:
            raise RuntimeError(
                f"The frozen six-task suite is not hidden-only before evaluation: {splits}"
            )
        frozen_domains["task_definitions_sha256"] = _sha256(
            [
                {
                    "title": task.title,
                    "instruction": task.natural_language_instruction,
                    "category": task.category,
                    "required_tools": task.required_tools,
                    "forbidden_tools": task.forbidden_tools,
                    "initial_state": task.initial_state,
                    "expected_final_state": task.expected_final_state,
                    "expected_invariants": task.expected_invariants,
                    "requires_clarification": task.requires_clarification,
                    "split": task.phase15_split,
                }
                for task in sorted(tasks, key=lambda item: item.title)
            ]
        )
        session.commit()
    return project_ids, frozen_domains


async def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    models, unavailable = resolve_models(["openai", "anthropic", "google"], settings)
    if unavailable or len(models) != 3:
        raise RuntimeError(f"Requested real providers are not configured: {unavailable}")
    expected = [
        "openai:gpt-4.1-mini",
        "anthropic:claude-sonnet-5",
        "google:gemini-3.6-flash",
    ]
    if models != expected:
        raise RuntimeError(f"Model configuration differs from the frozen matrix: {models}")
    configuration = Phase15Configuration(
        models=models,
        variants=["baseline", "optimized"],
        repetitions=3,
        split_seed=settings.phase15_task_split_seed,
        temperature=settings.phase15_temperature,
        max_cost_usd=min(settings.phase15_max_cost_usd, 5.0),
        max_concurrency=settings.phase15_max_concurrency,
        bootstrap_samples=settings.phase15_bootstrap_samples,
    )
    estimate = estimate_experiment_cost(6, configuration)
    if float(estimate["guarded_estimate_usd"]) > configuration.max_cost_usd:
        raise RuntimeError("Hidden evaluation estimate exceeds PHASE15_MAX_COST_USD")

    create_schema()
    project_ids, frozen_domains = seed_and_freeze_v2(configuration.split_seed)
    freeze_record = {
        "design_document": "docs/phase15_v2_manual_design.md",
        "models": models,
        "task_titles": sorted(title for titles in HIDDEN_TASKS.values() for title in titles),
        "variants": ["baseline", "optimized"],
        "repetitions": 3,
        "cost_cap_usd": configuration.max_cost_usd,
        "cost_estimate": estimate,
        "domains": frozen_domains,
    }
    freeze_path = output_root / "v2_frozen_design.json"
    freeze_path.write_text(json.dumps(freeze_record, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"event": "V2_FROZEN", "path": str(freeze_path), **freeze_record}))

    with SessionLocal() as session:
        projects = [session.get(Project, project_id) for project_id in project_ids]
        experiment = await run_phase15_experiment(
            session,
            [project for project in projects if project is not None],
            configuration,
            settings,
            name="Phase 1.5 frozen paired V0 versus manual V2 hidden evaluation",
            manifest_path=output_root / "data" / "experiment_manifest.json",
        )
        task_splits = set(
            session.scalars(
                select(BenchmarkTask.phase15_split).where(BenchmarkTask.project_id.in_(project_ids))
            )
        )
        if task_splits != {"hidden"}:
            raise RuntimeError(f"The frozen six-task suite was not hidden-only: {task_splits}")
        analysis = analyze_experiment(
            session, experiment, bootstrap_samples=settings.phase15_bootstrap_samples
        )
        export_experiment_dataset(session, experiment, output_root / "data")
        generate_report(experiment, analysis, output_root / "report")
        result = {
            "event": "EXPERIMENT_COMPLETE",
            "experiment_id": experiment.id,
            "status": experiment.status,
            "actual_cost_usd": experiment.actual_cost,
            "failed_cells": experiment.notes.splitlines() if experiment.notes else [],
            "models": models,
            "task_runs_expected": 108,
            "artifacts": str(output_root),
        }
        (output_root / "run_summary.json").write_text(
            json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
