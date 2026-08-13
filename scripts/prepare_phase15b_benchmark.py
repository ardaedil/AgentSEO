"""Seed the Phase 1.5B benchmark and write the content-free sealed holdout manifest."""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from agentseo.database import SessionLocal, create_schema
from agentseo.interfaces import mutate_snapshot
from agentseo.models import BenchmarkTask, InterfaceVersion, Project, ToolDefinition
from agentseo.openapi_parser import parse_openapi
from agentseo.phase15b_benchmark import (
    PHASE15B_EVALUATOR_VERSION,
    PHASE15B_SPLIT_SEED,
    assign_phase15b_split,
    generate_phase15b_tasks,
    stable_task_key,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "artifacts" / "phase15b"


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def main() -> None:
    create_schema()
    task_rows: list[BenchmarkTask] = []
    project_ids: list[str] = []
    with SessionLocal() as session:
        if session.query(BenchmarkTask).count() or session.query(Project).count():
            raise RuntimeError("Phase 1.5B preparation requires a new empty database")
        for domain in ("billing", "ecommerce", "crm"):
            _, tools = parse_openapi((ROOT / "examples" / domain / "openapi.yaml").read_bytes())
            snapshot, _ = mutate_snapshot([tool.to_dict() for tool in tools], "baseline")
            project = Project(
                name=f"AgentSEO Phase 1.5B — {domain}",
                description="Fresh 120-task model-specific interface validation benchmark",
                sandbox_domain=domain,
            )
            session.add(project)
            session.flush()
            project_ids.append(project.id)
            session.add_all(
                [ToolDefinition(project_id=project.id, **tool.to_dict()) for tool in tools]
            )
            session.add(
                InterfaceVersion(
                    project_id=project.id,
                    version=1,
                    tool_definitions_snapshot=snapshot,
                    name="V0 — Canonical baseline",
                    variant_key="baseline",
                    frozen=True,
                )
            )
            for generated in generate_phase15b_tasks(domain):
                task = BenchmarkTask(
                    id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            stable_task_key(domain, generated.title),
                        )
                    ),
                    project_id=project.id,
                    **generated.to_dict(),
                )
                session.add(task)
                task_rows.append(task)
        session.flush()
        split = assign_phase15b_split(task_rows, PHASE15B_SPLIT_SEED)
        session.commit()

        holdout = sorted(
            (task for task in task_rows if task.phase15_split == "holdout"),
            key=lambda task: task.id,
        )
        manifest = {
            "protocol": "AgentSEO Phase 1.5B sealed holdout",
            "split_seed": PHASE15B_SPLIT_SEED,
            "git_commit": _git_commit(),
            "evaluator_version": PHASE15B_EVALUATOR_VERSION,
            "task_count": len(holdout),
            "tasks": [
                {
                    "task_id": task.id,
                    "task_version": task.version,
                    "evaluator_version": PHASE15B_EVALUATOR_VERSION,
                    "initial_state_sha256": _canonical_hash(task.initial_state),
                }
                for task in holdout
            ],
        }
        manifest_hash = _canonical_hash(manifest)
        protocol = {
            "holdout_manifest_sha256": manifest_hash,
            "benchmark_task_count": len(task_rows),
            "development_task_count": sum(value == "development" for value in split.values()),
            "holdout_task_count": sum(value == "holdout" for value in split.values()),
            "category_distribution": dict(
                sorted(Counter(task.category for task in task_rows).items())
            ),
            "development_category_distribution": dict(
                sorted(
                    Counter(
                        task.category for task in task_rows if task.phase15_split == "development"
                    ).items()
                )
            ),
            "holdout_category_distribution": dict(
                sorted(
                    Counter(
                        task.category for task in task_rows if task.phase15_split == "holdout"
                    ).items()
                )
            ),
            "project_ids": project_ids,
        }
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        (OUTPUT_ROOT / "holdout_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        (OUTPUT_ROOT / "protocol_manifest.json").write_text(
            json.dumps(protocol, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "benchmark_tasks": len(task_rows),
                    "development_tasks": protocol["development_task_count"],
                    "sealed_holdout_tasks": protocol["holdout_task_count"],
                    "holdout_manifest_sha256": manifest_hash,
                    "output_root": str(OUTPUT_ROOT),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
