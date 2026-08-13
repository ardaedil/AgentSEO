"""Execute the frozen Phase 1.5B R2 sealed holdout in cap-compliant launches.

This module deliberately exposes no outcome metrics while the matrix is incomplete.
Operational status is limited to completed-observation counts, launch cost, and
infrastructure state. Intermediate rows exist only in the runtime database for recovery.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
from agentseo.config import get_settings
from agentseo.database import SessionLocal
from agentseo.interfaces import tools_from_interface
from agentseo.models import (
    BenchmarkTask,
    Experiment,
    ExperimentStatus,
    InterfaceVersion,
    Project,
    RunStatus,
    TaskRun,
    now,
)
from agentseo.providers import HTTPProvider, create_provider
from agentseo.runner import run_benchmark
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
R2_ROOT = ROOT / "artifacts" / "phase15b_r2"
RUNTIME_ROOT = R2_ROOT / "sealed_holdout_runtime"
STATE_PATH = Path(
    os.environ.get("PHASE15B_R2_STATE_PATH", RUNTIME_ROOT / "execution_state.json")
)
SOURCE_DB = Path.home() / "AppData" / "Local" / "Temp" / "agentseo-phase15b-r2-92b52a7.db"
RUNTIME_DB = RUNTIME_ROOT / "phase15b_r2_holdout.db"
VARIANTS = (
    "baseline",
    "phase15b_r2_general",
    "phase15b_r2_gpt",
    "phase15b_r2_claude",
    "phase15b_r2_gemini",
)
MODELS = (
    "openai:gpt-4.1-mini",
    "anthropic:claude-sonnet-5",
    "google:gemini-3.6-flash",
)
EXPECTED_OBSERVATIONS = 1620
MAX_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class Launch:
    launch_id: str
    model: str
    trials: tuple[int, ...]
    estimated_cost_usd: float
    guarded_cost_usd: float


def _load_launches() -> tuple[Launch, ...]:
    estimate = json.loads(
        (R2_ROOT / "sealed_holdout_cost_estimate.json").read_text(encoding="utf-8")
    )
    by_model = {row["model"]: row for row in estimate["providers"]}
    openai = by_model[MODELS[0]]
    anthropic = by_model[MODELS[1]]
    google = by_model[MODELS[2]]
    return (
        Launch(
            "L1_OPENAI_TRIALS_1_3",
            MODELS[0],
            (1, 2, 3),
            float(openai["estimated_cost_usd"]),
            float(openai["guarded_cost_usd"]),
        ),
        Launch(
            "L2_ANTHROPIC_TRIAL_1",
            MODELS[1],
            (1,),
            float(anthropic["estimated_cost_usd"]) / 3,
            float(anthropic["guarded_cost_usd"]) / 3,
        ),
        Launch(
            "L3_ANTHROPIC_TRIAL_2",
            MODELS[1],
            (2,),
            float(anthropic["estimated_cost_usd"]) / 3,
            float(anthropic["guarded_cost_usd"]) / 3,
        ),
        Launch(
            "L4_ANTHROPIC_TRIAL_3",
            MODELS[1],
            (3,),
            float(anthropic["estimated_cost_usd"]) / 3,
            float(anthropic["guarded_cost_usd"]) / 3,
        ),
        Launch(
            "L5_GEMINI_TRIALS_1_3",
            MODELS[2],
            (1, 2, 3),
            float(google["estimated_cost_usd"]),
            float(google["guarded_cost_usd"]),
        ),
    )


LAUNCHES = _load_launches()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _interface_snapshot_hash(value: Any) -> str:
    """Match the frozen-interface workflow's ASCII-escaped canonical encoding."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _task_payload(task: BenchmarkTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "version": task.version,
        "title": task.title,
        "natural_language_instruction": task.natural_language_instruction,
        "difficulty": task.difficulty,
        "category": task.category,
        "task_family": task.task_family,
        "required_tools": task.required_tools,
        "forbidden_tools": task.forbidden_tools,
        "initial_state": task.initial_state,
        "expected_final_state": task.expected_final_state,
        "expected_invariants": task.expected_invariants,
        "requires_clarification": task.requires_clarification,
        "safety_level": task.safety_level,
        "generated_or_manual": task.generated_or_manual,
    }


def _verify_embedded_hash(path: Path, key: str) -> dict[str, Any]:
    document = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    expected = document[key]
    payload = dict(document)
    payload.pop(key)
    if _canonical_hash(payload) != expected:
        raise RuntimeError(f"Frozen manifest hash mismatch: {path}")
    return document


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def prepare_runtime_database() -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    if RUNTIME_DB.exists():
        return
    if not SOURCE_DB.exists():
        raise RuntimeError(f"Frozen R2 source database unavailable: {SOURCE_DB}")
    shutil.copy2(SOURCE_DB, RUNTIME_DB)


def verify_frozen_state(*, allow_existing_holdout: bool) -> dict[str, Any]:
    settings = get_settings()
    if min(settings.phase15_max_cost_usd, 5.0) != 5.0:
        raise RuntimeError("PHASE15_MAX_COST_USD must remain exactly 5.00 for these launches")
    if (
        settings.openai_model != "gpt-4.1-mini"
        or settings.anthropic_model != "claude-sonnet-5"
        or settings.gemini_model != "gemini-3.6-flash"
    ):
        raise RuntimeError("Configured model IDs do not match the frozen R2 protocol")
    if not all((settings.openai_api_key, settings.anthropic_api_key, settings.google_api_key)):
        raise RuntimeError("All three frozen providers must be configured")
    for launch in LAUNCHES:
        if launch.guarded_cost_usd >= settings.phase15_max_cost_usd:
            raise RuntimeError(f"Launch {launch.launch_id} exceeds the per-launch safety cap")

    benchmark = _verify_embedded_hash(
        R2_ROOT / "frozen_benchmark" / "protocol_manifest.json",
        "protocol_manifest_sha256",
    )
    holdout = _verify_embedded_hash(
        R2_ROOT / "frozen_benchmark" / "holdout_manifest.json",
        "holdout_manifest_sha256",
    )
    interfaces = _verify_embedded_hash(
        R2_ROOT / "frozen_interfaces" / "manifest.json",
        "interface_freeze_sha256",
    )
    preregistration = json.loads((R2_ROOT / "preregistration.json").read_text(encoding="utf-8"))
    if benchmark["benchmark_sha256"] != preregistration["integrity"]["benchmark_sha256"]:
        raise RuntimeError("Preregistered benchmark hash mismatch")
    if (
        holdout["holdout_manifest_sha256"]
        != preregistration["integrity"]["holdout_manifest_sha256"]
    ):
        raise RuntimeError("Preregistered holdout hash mismatch")
    if (
        interfaces["interface_freeze_sha256"]
        != preregistration["integrity"]["interface_freeze_sha256"]
    ):
        raise RuntimeError("Preregistered interface hash mismatch")
    if tuple(interfaces["models"]) != MODELS or tuple(interfaces["variants"]) != VARIANTS:
        raise RuntimeError("Frozen model or interface matrix changed")
    if preregistration["matrix"]["repetitions"] != 3:
        raise RuntimeError("Frozen repetition count changed")

    for relative_path, expected_hash in benchmark["evaluator_files"].items():
        actual = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
        if actual != expected_hash:
            raise RuntimeError(f"Frozen evaluator file changed: {relative_path}")

    with SessionLocal() as session:
        tasks = list(session.scalars(select(BenchmarkTask).order_by(BenchmarkTask.id)))
        if len(tasks) != 120:
            raise RuntimeError("Runtime database does not contain the frozen 120-task benchmark")
        task_hashes = {task.id: _canonical_hash(_task_payload(task)) for task in tasks}
        holdout_rows = {row["task_id"]: row for row in holdout["tasks"]}
        holdout_tasks = [task for task in tasks if task.phase15_split == "holdout"]
        development_tasks = [task for task in tasks if task.phase15_split == "development"]
        if len(holdout_tasks) != 36 or len(development_tasks) != 84:
            raise RuntimeError("Frozen 84/36 task split changed")
        if {task.task_family for task in holdout_tasks} & {
            task.task_family for task in development_tasks
        }:
            raise RuntimeError("Task-family leakage detected")
        if set(holdout_rows) != {task.id for task in holdout_tasks}:
            raise RuntimeError("Runtime holdout membership differs from the sealed manifest")
        for task in holdout_tasks:
            if task_hashes[task.id] != holdout_rows[task.id]["task_definition_sha256"]:
                raise RuntimeError("A sealed holdout task definition changed")

        frozen_files = {
            (row["domain"], row["variant_key"]): row for row in interfaces["interfaces"]
        }
        projects = list(session.scalars(select(Project)))
        for project in projects:
            for interface in session.scalars(
                select(InterfaceVersion).where(
                    InterfaceVersion.project_id == project.id,
                    InterfaceVersion.variant_key.in_(VARIANTS),
                )
            ):
                row = frozen_files[(project.sandbox_domain, interface.variant_key)]
                snapshot = json.loads((ROOT / row["snapshot_path"]).read_text(encoding="utf-8"))
                if snapshot["tool_definitions_snapshot"] != interface.tool_definitions_snapshot:
                    raise RuntimeError("Runtime interface differs from its frozen snapshot")
                if _interface_snapshot_hash(snapshot) != row["snapshot_sha256"]:
                    raise RuntimeError("Frozen interface snapshot hash mismatch")

        holdout_run_count = int(
            session.scalar(
                select(func.count(TaskRun.id))
                .join(BenchmarkTask, TaskRun.task_id == BenchmarkTask.id)
                .where(BenchmarkTask.phase15_split == "holdout")
            )
            or 0
        )
        if holdout_run_count and not allow_existing_holdout:
            raise RuntimeError("Holdout observations already exist; use the recorded resume state")
    return {
        "verified_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "benchmark_sha256": benchmark["benchmark_sha256"],
        "holdout_manifest_sha256": holdout["holdout_manifest_sha256"],
        "interface_freeze_sha256": interfaces["interface_freeze_sha256"],
        "holdout_task_count": 36,
        "holdout_family_count": 12,
        "models": list(MODELS),
        "variants": list(VARIANTS),
        "repetitions": 3,
        "expected_observations": EXPECTED_OBSERVATIONS,
        "per_launch_cost_cap_usd": 5.0,
    }


def _classify_exception(exc: Exception) -> str:
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, httpx.HTTPStatusError):
            status = current.response.status_code
            body = current.response.text.lower()
            credit_markers = ("credit", "billing", "insufficient", "quota exceeded")
            if status == 402 or any(marker in body for marker in credit_markers):
                return "CREDIT_EXHAUSTED"
            if status == 429 or status >= 500:
                return "TRANSIENT_PROVIDER_ERROR"
            return "NONRETRYABLE_PROVIDER_ERROR"
        if isinstance(current, (httpx.TimeoutException, httpx.NetworkError)):
            return "TRANSIENT_PROVIDER_ERROR"
        current = current.__cause__ or current.__context__
    return "INFRASTRUCTURE_ERROR"


async def credit_preflight() -> dict[str, Any]:
    settings = get_settings()
    results: list[dict[str, Any]] = []
    with SessionLocal() as session:
        baseline = session.scalar(
            select(InterfaceVersion)
            .where(InterfaceVersion.variant_key == "baseline")
            .order_by(InterfaceVersion.project_id)
        )
        if baseline is None:
            raise RuntimeError("Frozen baseline is unavailable for provider preflight")
        tools = tools_from_interface(baseline)[:1]
    for identifier in MODELS:
        provider = create_provider(identifier, settings)
        try:
            action = await provider.next_action(
                "Credit and model-access preflight. Reply briefly without calling a tool.",
                tools,
                [],
                {"temperature": 0.0},
            )
            usage = action.token_usage or {}
            results.append(
                {
                    "model": identifier,
                    "status": "BILLABLE_INFERENCE_AVAILABLE",
                    "input_tokens": int(usage.get("input", 0)),
                    "output_tokens": int(usage.get("output", 0)),
                }
            )
        except Exception as exc:
            category = _classify_exception(exc)
            results.append({"model": identifier, "status": category})
            raise RuntimeError(f"Provider preflight failed for {identifier}: {category}") from exc
        finally:
            if isinstance(provider, HTTPProvider):
                await provider.client.aclose()
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "method": (
            "Successful authenticated billable inference on every exact frozen model, combined with "
            "a guarded per-launch estimate below PHASE15_MAX_COST_USD. Provider APIs do not expose a "
            "portable prepaid-balance endpoint for these key types."
        ),
        "providers": results,
        "launches": [
            {
                "launch_id": launch.launch_id,
                "model": launch.model,
                "trials": list(launch.trials),
                "estimated_cost_usd": launch.estimated_cost_usd,
                "guarded_cost_usd": launch.guarded_cost_usd,
                "below_cap": launch.guarded_cost_usd < 5.0,
            }
            for launch in LAUNCHES
        ],
    }


def _write_state(state: dict[str, Any]) -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def initialize_experiment(
    verification: dict[str, Any], preflight: dict[str, Any]
) -> dict[str, Any]:
    if STATE_PATH.exists():
        return cast(dict[str, Any], json.loads(STATE_PATH.read_text(encoding="utf-8")))
    with SessionLocal() as session:
        projects = list(session.scalars(select(Project).order_by(Project.sandbox_domain)))
        interfaces = list(
            session.scalars(
                select(InterfaceVersion).where(InterfaceVersion.variant_key.in_(VARIANTS))
            )
        )
        experiment = Experiment(
            project_id=projects[0].id,
            name="Phase 1.5B R2 complete sealed-holdout matrix",
            hypothesis=(
                "Development-evidence interface optimization changes success on unseen task families, "
                "with potentially different optima across model families."
            ),
            status=ExperimentStatus.READY.value,
            task_split_seed=1503,
            configuration={
                "protocol": "PHASE15B_R2_SEALED_HOLDOUT",
                "temperature": 0.0,
                "provider_seed": None,
                "max_iterations": 16,
                "max_tool_calls": 12,
                "timeout_seconds": 120,
                "per_launch_cost_cap_usd": 5.0,
                "launches": [launch.launch_id for launch in LAUNCHES],
                "intermediate_outcome_analysis_prohibited": True,
                "verification": verification,
                "credit_preflight": preflight,
            },
            models=list(MODELS),
            interface_versions=[interface.id for interface in interfaces],
            repetitions=3,
            estimated_cost=14.757115714285714,
            manifest={
                "verification": verification,
                "credit_preflight": preflight,
                "launch_plan": [launch.launch_id for launch in LAUNCHES],
                "status": "READY_UNOPENED",
            },
        )
        session.add(experiment)
        session.commit()
        state = {
            "protocol": "PHASE15B_R2_SEALED_HOLDOUT",
            "experiment_id": experiment.id,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "READY_UNOPENED",
            "verification": verification,
            "credit_preflight": preflight,
            "launches": {
                launch.launch_id: {
                    "model": launch.model,
                    "trials": list(launch.trials),
                    "estimated_cost_usd": launch.estimated_cost_usd,
                    "guarded_cost_usd": launch.guarded_cost_usd,
                    "status": "PENDING",
                    "completed_observations": 0,
                    "infrastructure_errors": [],
                }
                for launch in LAUNCHES
            },
        }
        _write_state(state)
        return state


def _launch_cost(session: Any, experiment_id: str, launch: Launch) -> float:
    return float(
        session.scalar(
            select(func.coalesce(func.sum(TaskRun.cost_estimate), 0)).where(
                TaskRun.experiment_id == experiment_id,
                TaskRun.model_identifier == launch.model,
                TaskRun.trial_number.in_(launch.trials),
                TaskRun.status == RunStatus.COMPLETED.value,
            )
        )
        or 0
    )


def _completed_for_launch(session: Any, experiment_id: str, launch: Launch) -> int:
    return int(
        session.scalar(
            select(func.count(TaskRun.id)).where(
                TaskRun.experiment_id == experiment_id,
                TaskRun.model_identifier == launch.model,
                TaskRun.trial_number.in_(launch.trials),
                TaskRun.status == RunStatus.COMPLETED.value,
            )
        )
        or 0
    )


def _expected_for_launch(launch: Launch) -> int:
    return 36 * len(VARIANTS) * len(launch.trials)


async def execute_launch(launch_id: str, trial_override: tuple[int, ...] = ()) -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    launch = next((item for item in LAUNCHES if item.launch_id == launch_id), None)
    if launch is None:
        raise RuntimeError(f"Unknown launch: {launch_id}")
    if trial_override:
        if not set(trial_override).issubset(launch.trials):
            raise RuntimeError(
                f"Trial override {trial_override} is outside frozen launch {launch.trials}"
            )
        fraction = len(trial_override) / len(launch.trials)
        launch = Launch(
            launch.launch_id,
            launch.model,
            trial_override,
            launch.estimated_cost_usd * fraction,
            launch.guarded_cost_usd * fraction,
        )
    settings = get_settings()
    verify_frozen_state(allow_existing_holdout=True)
    experiment_id = str(state["experiment_id"])
    state["status"] = "RUNNING_UNINSPECTED"
    state["launches"][launch_id]["status"] = "RUNNING"
    state["launches"][launch_id]["started_at"] = datetime.now(UTC).isoformat()
    _write_state(state)

    with SessionLocal() as session:
        experiment = session.get(Experiment, experiment_id)
        if experiment is None:
            raise RuntimeError("Recorded sealed-holdout experiment is unavailable")
        experiment.status = ExperimentStatus.RUNNING.value
        experiment.started_at = experiment.started_at or now()
        session.commit()
        projects = list(session.scalars(select(Project).order_by(Project.sandbox_domain)))
        by_project_variant = {
            (interface.project_id, interface.variant_key): interface
            for interface in session.scalars(
                select(InterfaceVersion).where(InterfaceVersion.variant_key.in_(VARIANTS))
            )
        }
        for trial in launch.trials:
            for project in projects:
                task_ids = list(
                    session.scalars(
                        select(BenchmarkTask.id)
                        .where(
                            BenchmarkTask.project_id == project.id,
                            BenchmarkTask.phase15_split == "holdout",
                        )
                        .order_by(BenchmarkTask.id)
                    )
                )
                for variant in VARIANTS:
                    interface = by_project_variant[(project.id, variant)]
                    completed_ids = set(
                        session.scalars(
                            select(TaskRun.task_id).where(
                                TaskRun.experiment_id == experiment_id,
                                TaskRun.interface_version_id == interface.id,
                                TaskRun.model_identifier == launch.model,
                                TaskRun.trial_number == trial,
                                TaskRun.task_id.in_(task_ids),
                                TaskRun.status == RunStatus.COMPLETED.value,
                            )
                        )
                    )
                    missing_ids = [task_id for task_id in task_ids if task_id not in completed_ids]
                    if not missing_ids:
                        continue
                    incomplete = list(
                        session.scalars(
                            select(TaskRun).where(
                                TaskRun.experiment_id == experiment_id,
                                TaskRun.interface_version_id == interface.id,
                                TaskRun.model_identifier == launch.model,
                                TaskRun.trial_number == trial,
                                TaskRun.task_id.in_(missing_ids),
                                TaskRun.status != RunStatus.COMPLETED.value,
                            )
                        )
                    )
                    for task_run in incomplete:
                        session.delete(task_run)
                    session.commit()
                    tasks = list(
                        session.scalars(
                            select(BenchmarkTask)
                            .where(BenchmarkTask.id.in_(missing_ids))
                            .order_by(BenchmarkTask.id)
                        )
                    )
                    for attempt in range(1, MAX_ATTEMPTS + 1):
                        try:
                            await run_benchmark(
                                session,
                                project,
                                launch.model,
                                tasks,
                                {
                                    "protocol": "PHASE15B_R2_SEALED_HOLDOUT",
                                    "launch_id": launch.launch_id,
                                    "max_iterations": 16,
                                    "max_tool_calls": 12,
                                    "timeout_seconds": 120,
                                    "temperature": 0.0,
                                    "provider_seed": None,
                                    "trial_seed": 1503 + trial,
                                },
                                settings,
                                interface_version=interface,
                                experiment_id=experiment_id,
                                trial_number=trial,
                                task_split="holdout",
                            )
                            break
                        except Exception as exc:
                            category = _classify_exception(exc)
                            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                            state["launches"][launch_id]["infrastructure_errors"].append(
                                {
                                    "category": category,
                                    "attempt": attempt,
                                    "cell": f"{project.sandbox_domain}/{variant}/trial-{trial}",
                                    "recorded_at": datetime.now(UTC).isoformat(),
                                }
                            )
                            _write_state(state)
                            if category == "CREDIT_EXHAUSTED":
                                state["status"] = "BLOCKED_CREDIT"
                                state["launches"][launch_id]["status"] = "BLOCKED_CREDIT"
                                _write_state(state)
                                raise RuntimeError(
                                    f"Provider credit exhausted for {launch.model}"
                                ) from exc
                            if category != "TRANSIENT_PROVIDER_ERROR" or attempt == MAX_ATTEMPTS:
                                state["status"] = "BLOCKED_INFRASTRUCTURE"
                                state["launches"][launch_id]["status"] = "BLOCKED_INFRASTRUCTURE"
                                _write_state(state)
                                raise
                            await asyncio.sleep(15 * attempt)
                            completed_ids = set(
                                session.scalars(
                                    select(TaskRun.task_id).where(
                                        TaskRun.experiment_id == experiment_id,
                                        TaskRun.interface_version_id == interface.id,
                                        TaskRun.model_identifier == launch.model,
                                        TaskRun.trial_number == trial,
                                        TaskRun.task_id.in_(missing_ids),
                                        TaskRun.status == RunStatus.COMPLETED.value,
                                    )
                                )
                            )
                            missing_ids = [
                                task_id for task_id in missing_ids if task_id not in completed_ids
                            ]
                            for task_run in session.scalars(
                                select(TaskRun).where(
                                    TaskRun.experiment_id == experiment_id,
                                    TaskRun.interface_version_id == interface.id,
                                    TaskRun.model_identifier == launch.model,
                                    TaskRun.trial_number == trial,
                                    TaskRun.task_id.in_(missing_ids),
                                    TaskRun.status != RunStatus.COMPLETED.value,
                                )
                            ):
                                session.delete(task_run)
                            session.commit()
                            tasks = list(
                                session.scalars(
                                    select(BenchmarkTask)
                                    .where(BenchmarkTask.id.in_(missing_ids))
                                    .order_by(BenchmarkTask.id)
                                )
                            )
                    actual_cost = _launch_cost(session, experiment_id, launch)
                    if actual_cost > settings.phase15_max_cost_usd:
                        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                        state["status"] = "BLOCKED_COST_CAP"
                        state["launches"][launch_id]["status"] = "BLOCKED_COST_CAP"
                        state["launches"][launch_id]["actual_cost_usd"] = actual_cost
                        _write_state(state)
                        raise RuntimeError(f"Launch {launch_id} exceeded the $5.00 safety cap")
                    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                    state["launches"][launch_id]["completed_observations"] = _completed_for_launch(
                        session, experiment_id, launch
                    )
                    state["launches"][launch_id]["actual_cost_usd"] = actual_cost
                    _write_state(state)

        completed = _completed_for_launch(session, experiment_id, launch)
        if completed != _expected_for_launch(launch):
            raise RuntimeError(
                f"Launch {launch_id} incomplete: {completed}/{_expected_for_launch(launch)}"
            )
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        state["launches"][launch_id]["status"] = "COMPLETED_UNINSPECTED"
        state["launches"][launch_id]["completed_at"] = datetime.now(UTC).isoformat()
        state["launches"][launch_id]["completed_observations"] = completed
        state["launches"][launch_id]["actual_cost_usd"] = _launch_cost(
            session, experiment_id, launch
        )
        _write_state(state)


def create_worker_database(
    worker_id: str, launch_id: str, trials: tuple[int, ...]
) -> dict[str, str]:
    """Create a transactionally consistent execution shard without opening outcomes."""
    if not worker_id.replace("_", "").replace("-", "").isalnum():
        raise RuntimeError("Worker id may contain only letters, digits, hyphens, and underscores")
    launch = next((item for item in LAUNCHES if item.launch_id == launch_id), None)
    if launch is None or not trials or not set(trials).issubset(launch.trials):
        raise RuntimeError("Worker scope is outside the frozen deterministic launch")
    worker_root = RUNTIME_ROOT / "workers"
    worker_root.mkdir(parents=True, exist_ok=True)
    worker_db = worker_root / f"{worker_id}.db"
    worker_state = worker_root / f"{worker_id}.state.json"
    if worker_db.exists() or worker_state.exists():
        raise RuntimeError(f"Worker already exists: {worker_id}")
    with sqlite3.connect(RUNTIME_DB, timeout=60) as source:
        with sqlite3.connect(worker_db, timeout=60) as target:
            source.backup(target)
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state["worker_scope"] = {
        "worker_id": worker_id,
        "launch_id": launch_id,
        "model": launch.model,
        "trials": list(trials),
        "created_at": datetime.now(UTC).isoformat(),
    }
    state["launches"][launch_id]["status"] = "PENDING"
    worker_state.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"database": str(worker_db), "state": str(worker_state)}


def _sync_master_launch_state() -> dict[str, Any]:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    experiment_id = str(state["experiment_id"])
    with SessionLocal() as session:
        for launch in LAUNCHES:
            completed = _completed_for_launch(session, experiment_id, launch)
            launch_state = state["launches"][launch.launch_id]
            launch_state["completed_observations"] = completed
            launch_state["actual_cost_usd"] = _launch_cost(session, experiment_id, launch)
            if completed == _expected_for_launch(launch):
                launch_state["status"] = "COMPLETED_UNINSPECTED"
                launch_state.setdefault("completed_at", datetime.now(UTC).isoformat())
        total = int(
            session.scalar(
                select(func.count(TaskRun.id)).where(
                    TaskRun.experiment_id == experiment_id,
                    TaskRun.status == RunStatus.COMPLETED.value,
                )
            )
            or 0
        )
    state["status"] = (
        "COMPLETED_UNINSPECTED" if total == EXPECTED_OBSERVATIONS else "RUNNING_UNINSPECTED"
    )
    _write_state(state)
    return cast(dict[str, Any], state)


def merge_worker_database(
    worker_db: Path,
    worker_state_path: Path,
    model: str,
    trials: tuple[int, ...],
) -> dict[str, Any]:
    """Merge only completed assigned observations; never query outcome columns."""
    if model not in MODELS or not trials or not set(trials).issubset({1, 2, 3}):
        raise RuntimeError("Worker merge scope is outside the frozen matrix")
    master_state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    experiment_id = str(master_state["experiment_id"])
    placeholders = ",".join("?" for _ in trials)
    predicate = (
        "tr.experiment_id = ? AND tr.model_identifier = ? "
        f"AND tr.trial_number IN ({placeholders}) AND tr.status = ?"
    )
    params: tuple[Any, ...] = (
        experiment_id,
        model,
        *trials,
        RunStatus.COMPLETED.value,
    )
    with sqlite3.connect(RUNTIME_DB, timeout=60) as connection:
        connection.execute("PRAGMA busy_timeout=60000")
        connection.execute("ATTACH DATABASE ? AS worker", (str(worker_db),))
        connection.execute(
            "INSERT OR IGNORE INTO benchmark_runs SELECT br.* FROM worker.benchmark_runs br "
            "WHERE br.id IN (SELECT DISTINCT tr.benchmark_run_id FROM worker.task_runs tr "
            f"WHERE {predicate})",
            params,
        )
        connection.execute(
            "INSERT OR IGNORE INTO task_runs SELECT tr.* FROM worker.task_runs tr "
            f"WHERE {predicate}",
            params,
        )
        connection.execute(
            "INSERT OR IGNORE INTO trace_events SELECT te.* FROM worker.trace_events te "
            "WHERE te.task_run_id IN (SELECT tr.id FROM worker.task_runs tr "
            f"WHERE {predicate})",
            params,
        )
        connection.commit()
    if worker_state_path.exists():
        worker_state = json.loads(worker_state_path.read_text(encoding="utf-8"))
        for launch_id, launch_state in worker_state.get("launches", {}).items():
            master_errors = master_state["launches"][launch_id]["infrastructure_errors"]
            for error in launch_state.get("infrastructure_errors", []):
                if error not in master_errors:
                    master_errors.append(error)
        _write_state(master_state)
    state = _sync_master_launch_state()
    return {
        "model": model,
        "trials": list(trials),
        "state": state["status"],
        "outcomes_inspected": False,
    }


def operational_status() -> dict[str, Any]:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    experiment_id = str(state["experiment_id"])
    with SessionLocal() as session:
        completed = int(
            session.scalar(
                select(func.count(TaskRun.id)).where(
                    TaskRun.experiment_id == experiment_id,
                    TaskRun.status == RunStatus.COMPLETED.value,
                )
            )
            or 0
        )
        actual_cost = float(
            session.scalar(
                select(func.coalesce(func.sum(TaskRun.cost_estimate), 0)).where(
                    TaskRun.experiment_id == experiment_id,
                    TaskRun.status == RunStatus.COMPLETED.value,
                )
            )
            or 0
        )
    return {
        "experiment_id": experiment_id,
        "state": state["status"],
        "completed_observations": completed,
        "expected_observations": EXPECTED_OBSERVATIONS,
        "actual_cost_usd": actual_cost,
        "launches": {
            key: {
                "status": value["status"],
                "completed_observations": value["completed_observations"],
                "actual_cost_usd": value.get("actual_cost_usd", 0),
                "infrastructure_error_count": len(value["infrastructure_errors"]),
            }
            for key, value in state["launches"].items()
        },
        "outcomes_inspected": False,
    }


def finalize_execution() -> dict[str, Any]:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    experiment_id = str(state["experiment_id"])
    with SessionLocal() as session:
        experiment = session.get(Experiment, experiment_id)
        if experiment is None:
            raise RuntimeError("Sealed-holdout experiment unavailable")
        completed = int(
            session.scalar(
                select(func.count(TaskRun.id)).where(
                    TaskRun.experiment_id == experiment_id,
                    TaskRun.status == RunStatus.COMPLETED.value,
                )
            )
            or 0
        )
        distinct = len(
            set(
                session.execute(
                    select(
                        TaskRun.task_id,
                        TaskRun.interface_version_id,
                        TaskRun.model_identifier,
                        TaskRun.trial_number,
                    ).where(
                        TaskRun.experiment_id == experiment_id,
                        TaskRun.status == RunStatus.COMPLETED.value,
                    )
                ).all()
            )
        )
        if completed != EXPECTED_OBSERVATIONS or distinct != EXPECTED_OBSERVATIONS:
            raise RuntimeError(
                f"Preregistered analysis gate closed: completed={completed}, distinct={distinct}"
            )
        experiment.status = ExperimentStatus.COMPLETED.value
        experiment.completed_at = now()
        experiment.actual_cost = float(
            session.scalar(
                select(func.coalesce(func.sum(TaskRun.cost_estimate), 0)).where(
                    TaskRun.experiment_id == experiment_id,
                    TaskRun.status == RunStatus.COMPLETED.value,
                )
            )
            or 0
        )
        manifest = dict(experiment.manifest or {})
        manifest.update(
            {
                "status": "COMPLETED_READY_FOR_PREREGISTERED_ANALYSIS",
                "completed_observations": completed,
                "distinct_observations": distinct,
                "actual_cost_usd": experiment.actual_cost,
                "completed_at": experiment.completed_at.isoformat(),
                "execution_state_path": str(STATE_PATH.relative_to(ROOT)).replace("\\", "/"),
            }
        )
        experiment.manifest = manifest
        session.commit()
    state["status"] = "COMPLETED_READY_FOR_PREREGISTERED_ANALYSIS"
    state["completed_at"] = datetime.now(UTC).isoformat()
    _write_state(state)
    return operational_status()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "prepare",
            "preflight",
            "launch",
            "make-worker",
            "merge-worker",
            "status",
            "finalize",
        ),
    )
    parser.add_argument("--launch-id")
    parser.add_argument("--trials", type=int, nargs="*")
    parser.add_argument("--worker-id")
    parser.add_argument("--worker-db")
    parser.add_argument("--worker-state")
    parser.add_argument("--model")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare_runtime_database()
        verification = verify_frozen_state(allow_existing_holdout=False)
        print(json.dumps(verification, sort_keys=True))
        return
    if args.command == "preflight":
        verification = verify_frozen_state(allow_existing_holdout=False)
        preflight = await credit_preflight()
        state = initialize_experiment(verification, preflight)
        print(
            json.dumps(
                {
                    "experiment_id": state["experiment_id"],
                    "status": state["status"],
                    "providers": [
                        {"model": row["model"], "status": row["status"]}
                        for row in preflight["providers"]
                    ],
                    "launches_below_cap": all(row["below_cap"] for row in preflight["launches"]),
                },
                sort_keys=True,
            )
        )
        return
    if args.command == "launch":
        if not args.launch_id:
            raise RuntimeError("--launch-id is required")
        await execute_launch(args.launch_id, tuple(args.trials or ()))
        print(json.dumps(operational_status(), sort_keys=True))
        return
    if args.command == "make-worker":
        if not args.worker_id or not args.launch_id or not args.trials:
            raise RuntimeError("--worker-id, --launch-id, and --trials are required")
        print(
            json.dumps(
                create_worker_database(args.worker_id, args.launch_id, tuple(args.trials)),
                sort_keys=True,
            )
        )
        return
    if args.command == "merge-worker":
        if not args.worker_db or not args.worker_state or not args.model or not args.trials:
            raise RuntimeError(
                "--worker-db, --worker-state, --model, and --trials are required"
            )
        print(
            json.dumps(
                merge_worker_database(
                    Path(args.worker_db),
                    Path(args.worker_state),
                    args.model,
                    tuple(args.trials),
                ),
                sort_keys=True,
            )
        )
        return
    if args.command == "status":
        print(json.dumps(operational_status(), sort_keys=True))
        return
    print(json.dumps(finalize_execution(), sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
