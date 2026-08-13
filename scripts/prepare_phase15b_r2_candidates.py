"""Seed the unsplit Phase 1.5B R2 hard-benchmark candidate pool."""

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
from agentseo.phase15b_r2_benchmark import (
    PHASE15B_R2_EVALUATOR_VERSION,
    PHASE15B_R2_PROTOCOL,
    R2_UNCALIBRATED_FAMILIES,
    generate_phase15b_r2_tasks,
    phase15b_r2_families,
    stable_r2_task_key,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "artifacts" / "phase15b_r2"


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def main() -> None:
    create_schema()
    task_rows: list[BenchmarkTask] = []
    with SessionLocal() as session:
        if session.query(BenchmarkTask).count() or session.query(Project).count():
            raise RuntimeError("R2 candidate preparation requires a new empty database")
        for domain in ("billing", "ecommerce", "crm"):
            _, tools = parse_openapi((ROOT / "examples" / domain / "openapi.yaml").read_bytes())
            snapshot, _ = mutate_snapshot([tool.to_dict() for tool in tools], "baseline")
            project = Project(
                name=f"AgentSEO Phase 1.5B R2 — {domain}",
                description="Unsplit 120-task hard-benchmark candidate pool",
                sandbox_domain=domain,
            )
            session.add(project)
            session.flush()
            session.add_all(
                [ToolDefinition(project_id=project.id, **tool.to_dict()) for tool in tools]
            )
            session.add(
                InterfaceVersion(
                    project_id=project.id,
                    version=1,
                    tool_definitions_snapshot=snapshot,
                    name="R2 V0 — Canonical baseline",
                    variant_key="baseline",
                    frozen=True,
                )
            )
            for generated in generate_phase15b_r2_tasks(domain):
                task = BenchmarkTask(
                    id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            stable_r2_task_key(domain, generated.title),
                        )
                    ),
                    project_id=project.id,
                    phase15_split=None,
                    **generated.to_dict(),
                )
                session.add(task)
                task_rows.append(task)
        session.commit()
        families = phase15b_r2_families()
        manifest = {
            "protocol": PHASE15B_R2_PROTOCOL,
            "state": "UNSPLIT_CALIBRATION_CANDIDATE_POOL",
            "git_commit": _git_commit(),
            "evaluator_version": PHASE15B_R2_EVALUATOR_VERSION,
            "task_count": len(task_rows),
            "task_family_count": len(families),
            "category_distribution": dict(sorted(Counter(task.category for task in task_rows).items())),
            "difficulty_distribution": dict(sorted(Counter(task.difficulty for task in task_rows).items())),
            "domain_distribution": dict(
                sorted(
                    Counter(
                        session.get(Project, task.project_id).sandbox_domain  # type: ignore[union-attr]
                        for task in task_rows
                    ).items()
                )
            ),
            "calibration_eligible_family_count": len(families) - len(R2_UNCALIBRATED_FAMILIES),
            "uncalibrated_reserved_family_count": len(R2_UNCALIBRATED_FAMILIES),
            "tasks": [
                {
                    "task_id": task.id,
                    "task_version": task.version,
                    "task_family": task.task_family,
                    "category": task.category,
                    "difficulty": task.difficulty,
                    "initial_state_sha256": _canonical_hash(task.initial_state),
                }
                for task in sorted(task_rows, key=lambda item: item.id)
            ],
        }
        manifest["candidate_manifest_sha256"] = _canonical_hash(manifest)
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        (OUTPUT_ROOT / "candidate_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps({key: manifest[key] for key in ("task_count", "task_family_count", "category_distribution", "difficulty_distribution", "domain_distribution", "candidate_manifest_sha256")}, indent=2))


if __name__ == "__main__":
    main()
