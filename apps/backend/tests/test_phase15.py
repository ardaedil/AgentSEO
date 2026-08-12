from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from agentseo.config import get_settings
from agentseo.database import SessionLocal
from agentseo.experiments import (
    Phase15Configuration,
    analyze_experiment,
    assign_task_split,
    create_manifest,
    estimate_experiment_cost,
    run_phase15_experiment,
)
from agentseo.interfaces import (
    create_phase15_variants,
    interface_features,
    translate_tool_call,
)
from agentseo.models import (
    BenchmarkTask,
    ExperimentStatus,
    InterfaceMutation,
    InterfaceVersion,
    Project,
    TaskRun,
    ToolDefinition,
)
from agentseo.reporting import generate_report
from agentseo.research_export import export_experiment_dataset
from agentseo.sandboxes import create_sandbox
from agentseo.statistics import mcnemar_exact, paired_binary_comparison
from sqlalchemy import func, select


def tool_snapshot() -> dict:
    return {
        "name": "get_customer",
        "operation_id": "get_customer",
        "http_method": "GET",
        "path": "/customers/{id}",
        "description": "Get one customer by unique ID. Do not search by email.",
        "parameters": [
            {
                "name": "id",
                "in": "path",
                "required": True,
                "description": "Unique customer ID",
                "schema": {"type": "string"},
            }
        ],
        "request_schema": {},
        "response_schema": {"type": "object"},
        "tags": ["Customers"],
        "is_destructive": False,
        "inferred_destructive": False,
        "requires_authentication": False,
        "tool_metadata": {"examples": ["cus_john"]},
    }


def make_project(session, task_count: int = 3):
    project = Project(name="Phase15 test", sandbox_domain="billing")
    session.add(project)
    session.flush()
    snapshot = tool_snapshot()
    session.add(ToolDefinition(project_id=project.id, **snapshot))
    interface = InterfaceVersion(
        project_id=project.id,
        version=1,
        tool_definitions_snapshot=[snapshot],
        name="V0 — Canonical baseline",
        variant_key="baseline",
        frozen=True,
    )
    session.add(interface)
    tasks = []
    for index in range(task_count):
        tasks.append(
            BenchmarkTask(
                project_id=project.id,
                title=f"Clarify customer {index}",
                natural_language_instruction=f"Look up the ambiguous customer {index}",
                difficulty=index + 1,
                category="clarification",
                requires_clarification=True,
            )
        )
    session.add_all(tasks)
    session.commit()
    return project, interface, tasks


def test_interface_mutation_variant_and_canonical_mapping():
    with SessionLocal() as session:
        project, parent, _ = make_project(session)
        degraded = create_phase15_variants(session, project, ["degraded"])[0]
        assert degraded.parent_version_id == parent.id
        assert degraded.tool_definitions_snapshot[0]["name"] == "lookup_01"
        canonical, arguments = translate_tool_call(degraded, "lookup_01", {"value_1": "cus_john"})
        assert canonical == "get_customer"
        assert arguments == {"id": "cus_john"}
        mutations = list(
            session.scalars(
                select(InterfaceMutation).where(
                    InterfaceMutation.interface_version_id == degraded.id
                )
            )
        )
        assert {mutation.mutation_type for mutation in mutations} >= {
            "TOOL_RENAME",
            "DESCRIPTION_REDUCTION",
            "DESCRIPTION_OVERLAP",
            "NEGATIVE_INSTRUCTION_REMOVAL",
            "PARAMETER_RENAME",
            "PARAMETER_DESCRIPTION_REMOVAL",
            "EXAMPLE_REMOVAL",
            "TOOL_OVERLAP",
        }


def test_toolset_expansion_is_safe_and_feature_extraction_is_structured():
    with SessionLocal() as session:
        project, _, _ = make_project(session)
        expanded = create_phase15_variants(session, project, ["toolset_25"])[0]
        features = interface_features(expanded.tool_definitions_snapshot)
        assert features["number_of_tools"] == 25
        assert features["tools"][-1]["experimental_distractor"] is True
        sandbox = create_sandbox("billing")
        before = sandbox.snapshot()
        result = sandbox.execute("experiment_read_context_25", {})
        assert result["read_only"] is True
        assert sandbox.snapshot() == before
        crm = create_sandbox("crm")
        assert crm.execute("get_company", {"id": "co_acme"})["name"] == "Acme Inc."


def test_configuration_split_cost_and_paired_statistics():
    configuration = Phase15Configuration(
        models=["openai:exact-model"], variants=["baseline", "degraded"], repetitions=3
    )
    configuration.validate()
    estimate = estimate_experiment_cost(10, configuration)
    assert estimate["expected_agent_tasks"] == 60
    assert estimate["expected_provider_calls"] == 240
    assert estimate["guarded_estimate_usd"] > 0
    with pytest.raises(ValueError, match="baseline"):
        Phase15Configuration(models=["mock:reliable"], variants=["degraded"]).validate()

    with SessionLocal() as session:
        _, _, tasks = make_project(session, task_count=10)
        first = assign_task_split(tasks, 42)
        second = assign_task_split(tasks, 42)
        assert first == second
        assert set(first.values()) == {"development", "hidden"}

    baseline = [
        {"task_id": "a", "success": False},
        {"task_id": "b", "success": True},
        {"task_id": "c", "success": False},
    ]
    treatment = [
        {"task_id": "a", "success": True},
        {"task_id": "b", "success": True},
        {"task_id": "c", "success": True},
    ]
    comparison = paired_binary_comparison(baseline, treatment, bootstrap_samples=200)
    assert comparison["absolute_difference"] == pytest.approx(2 / 3)
    assert comparison["sample_size_tasks"] == 3
    assert mcnemar_exact([False, True], [True, True])["discordant_pairs"] == 1


def test_repeated_trials_manifest_dataset_and_report(tmp_path: Path):
    with SessionLocal() as session:
        project, _, _ = make_project(session, task_count=3)
        configuration = Phase15Configuration(
            models=["mock:reliable"],
            variants=["baseline", "degraded", "optimized"],
            repetitions=3,
            max_cost_usd=1,
            bootstrap_samples=200,
        )
        experiment = asyncio.run(
            run_phase15_experiment(
                session,
                [project],
                configuration,
                get_settings(),
                manifest_path=tmp_path / "manifest.json",
            )
        )
        assert (tmp_path / "manifest.json").exists()
        assert experiment.status == ExperimentStatus.COMPLETED.value
        assert experiment.actual_cost == 0
        task_run_count = session.scalar(
            select(func.count(TaskRun.id)).where(TaskRun.experiment_id == experiment.id)
        )
        assert task_run_count == 27
        trials = set(
            session.scalars(
                select(TaskRun.trial_number).where(TaskRun.experiment_id == experiment.id)
            )
        )
        assert trials == {1, 2, 3}
        interfaces = [session.get(InterfaceVersion, item) for item in experiment.interface_versions]
        manifest = create_manifest(
            experiment,
            list(session.scalars(select(BenchmarkTask))),
            [item for item in interfaces if item is not None],
        )
        assert manifest["git_commit"]
        assert manifest["repetitions"] == 3

        analysis = analyze_experiment(session, experiment, bootstrap_samples=200)
        assert analysis["decision"] == "DO NOT PROCEED YET"
        assert analysis["real_observation_count"] == 0
        assert "cross_model_variance" in analysis
        assert "mutation_failure_analysis" in analysis
        jsonl, csv_path = export_experiment_dataset(session, experiment, tmp_path / "data")
        assert len(jsonl.read_text(encoding="utf-8").splitlines()) == 27
        assert csv_path.read_text(encoding="utf-8").startswith("experiment_id,")
        markdown, html_path, charts = generate_report(experiment, analysis, tmp_path / "reports")
        assert "# DO NOT PROCEED YET" in markdown.read_text(encoding="utf-8")
        assert html_path.exists()
        assert len(charts) >= 7
        assert all(path.exists() for path in charts)


def test_cost_guard_blocks_before_provider_calls(tmp_path: Path):
    with SessionLocal() as session:
        project, _, _ = make_project(session, task_count=2)
        configuration = Phase15Configuration(
            models=["openai:unconfigured-but-never-called"],
            variants=["baseline", "degraded"],
            repetitions=3,
            max_cost_usd=0,
        )
        experiment = asyncio.run(
            run_phase15_experiment(
                session,
                [project],
                configuration,
                get_settings(),
                manifest_path=tmp_path / "manifest.json",
            )
        )
        assert (tmp_path / "manifest.json").exists()
        assert experiment.status == ExperimentStatus.BLOCKED_COST.value
        assert (
            session.scalar(
                select(func.count(TaskRun.id)).where(TaskRun.experiment_id == experiment.id)
            )
            == 0
        )
