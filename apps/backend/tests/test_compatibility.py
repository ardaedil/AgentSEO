from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from agentseo.cli import app
from agentseo.compatibility import (
    CompatibilityBudgetError,
    CompatibilityConfiguration,
    compatibility_report,
    run_compatibility,
    select_contracts,
    validate_baseline_compatibility,
)
from agentseo.compatibility_policy import (
    PolicyConfig,
    aggregate_pairs,
    classify_regression,
    evaluate_policy,
)
from agentseo.config import Settings
from agentseo.contracts import (
    AgenticCompatibilityContract,
    contract_suite_hash,
    load_contract_suite,
)
from agentseo.database import SessionLocal
from agentseo.interface_diff import InterfaceChangeType, diff_summary, semantic_diff
from agentseo.models import CompatibilityResult, FailureCategory
from agentseo.openapi_parser import parse_openapi
from sqlalchemy import select
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "examples" / "compatibility-ci-demo"


def tools(name: str):
    return parse_openapi((DEMO / name / "openapi.yaml").read_bytes())[1]


def test_semantic_diff_ignores_format_and_detects_description_changes():
    baseline = tools("baseline")
    safe = tools("candidate-safe")
    changes = semantic_diff(baseline, safe)
    assert changes
    assert {change.change_type for change in changes} == {
        InterfaceChangeType.DESCRIPTION_CHANGED.value,
        InterfaceChangeType.PARAMETER_DESCRIPTION_CHANGED.value,
    }
    assert diff_summary(changes)["affected_tools"] == [
        "cancel_subscription",
        "delete_customer",
        "refund_invoice",
        "search_customers",
    ]


def test_breaking_demo_remains_structurally_schema_compatible():
    changes = semantic_diff(tools("baseline"), tools("candidate-breaking"))
    structural_changes = {
        InterfaceChangeType.TOOL_ADDED.value,
        InterfaceChangeType.TOOL_REMOVED.value,
        InterfaceChangeType.PARAMETER_ADDED.value,
        InterfaceChangeType.PARAMETER_REMOVED.value,
        InterfaceChangeType.PARAMETER_RENAMED.value,
        InterfaceChangeType.PARAMETER_REQUIREDNESS_CHANGED.value,
        InterfaceChangeType.ENUM_CHANGED.value,
        InterfaceChangeType.REQUEST_SCHEMA_CHANGED.value,
        InterfaceChangeType.RESPONSE_SCHEMA_CHANGED.value,
    }
    assert not structural_changes.intersection(change.change_type for change in changes)
    assert any(change.change_type == "TOOL_RENAMED" for change in changes)
    assert any(change.change_type == "DESCRIPTION_CHANGED" for change in changes)


def test_semantic_diff_detects_rename_required_enum_and_schema():
    baseline = b"""openapi: 3.0.3
info: {title: x, version: 1}
paths:
  /items:
    post:
      operationId: create_item
      parameters:
        - {name: mode, in: query, required: false, schema: {type: string, enum: [a]}}
      requestBody: {content: {application/json: {schema: {type: object}}}}
      responses: {'200': {description: ok}}
"""
    candidate = b"""openapi: 3.0.3
info: {title: x, version: 2}
paths:
  /items:
    post:
      operationId: add_item
      parameters:
        - {name: mode, in: query, required: true, schema: {type: string, enum: [a, b]}}
      requestBody: {content: {application/json: {schema: {type: object, required: [name]}}}}
      responses: {'200': {description: ok}}
"""
    changes = semantic_diff(parse_openapi(baseline)[1], parse_openapi(candidate)[1])
    kinds = {change.change_type for change in changes}
    assert {
        "TOOL_RENAMED",
        "PARAMETER_REQUIREDNESS_CHANGED",
        "ENUM_CHANGED",
        "REQUEST_SCHEMA_CHANGED",
    }.issubset(kinds)


def test_contract_suite_is_versioned_hashed_and_model_agnostic():
    contracts = load_contract_suite(DEMO / "contracts")
    assert len(contracts) == 2
    assert len(contract_suite_hash(contracts)) == 64
    assert all(contract.schema_version == "1.0" for contract in contracts)
    assert "model" not in json.dumps([contract.canonical_dict() for contract in contracts])


def test_contract_validation_rejects_conflicting_actions():
    raw = load_contract_suite(DEMO / "contracts")[0].model_dump()
    raw["forbidden_actions"] = [*raw["required_actions"]]
    with pytest.raises(ValueError, match="both required and forbidden"):
        AgenticCompatibilityContract.model_validate(raw)


def test_affected_only_selection_uses_tools_and_capabilities():
    contracts = load_contract_suite(DEMO / "contracts")
    changes = semantic_diff(tools("baseline"), tools("candidate-safe"))
    selected = select_contracts(contracts, changes, "AFFECTED_ONLY")
    assert {contract.name for contract in selected} == {
        "customer_lookup",
        "safe_subscription_cancellation",
    }


def pair(**overrides):
    value = {
        "baseline_success": True,
        "candidate_success": True,
        "baseline_failure": None,
        "candidate_failure": None,
        "baseline_tool_calls": 2,
        "candidate_tool_calls": 2,
        "baseline_tokens": 100,
        "candidate_tokens": 100,
        "baseline_latency": 1.0,
        "candidate_latency": 1.0,
        "baseline_cost": 0.01,
        "candidate_cost": 0.01,
        "safety_baseline": True,
        "safety_candidate": True,
        "baseline_evaluator": {},
        "candidate_evaluator": {},
        "baseline_multi_step_success": True,
        "candidate_multi_step_success": True,
        "is_multi_step": False,
        "is_clarification": False,
        "is_error_recovery": False,
        "risk_level": "medium",
    }
    value.update(overrides)
    return value


def test_regression_taxonomy_maps_behavioral_failures():
    row = pair(
        candidate_success=False,
        candidate_failure=FailureCategory.WRONG_TOOL.value,
    )
    assert classify_regression(row) == "TOOL_SELECTION_REGRESSION"
    assert (
        classify_regression(pair(baseline_success=False, candidate_success=True))
        == "RESOLVED_FAILURE"
    )


def test_policy_is_transparent_and_fails_safety_regression():
    pairs = [pair() for _ in range(9)] + [
        pair(
            candidate_success=False,
            candidate_failure=FailureCategory.DESTRUCTIVE_ACTION_ERROR.value,
            safety_candidate=False,
            risk_level="critical",
        )
    ]
    metrics = aggregate_pairs(pairs)
    policy = evaluate_policy(metrics, pairs)
    assert policy["verdict"] == "FAIL"
    assert policy["classification"] == "AGENT_BREAKING"
    assert policy["exit_code"] == 1
    assert {rule["rule"] for rule in policy["fired_rules"]} >= {
        "SAFETY_DELTA",
        "NEW_DESTRUCTIVE_ACTION_ERROR",
        "CRITICAL_CONTRACT_REGRESSION",
    }


def test_conditional_metrics_use_only_applicable_contracts():
    rows = [
        pair(
            is_multi_step=True,
            baseline_multi_step_success=True,
            candidate_multi_step_success=False,
            is_clarification=True,
            baseline_evaluator={"clarification_passed": True},
            candidate_evaluator={"clarification_passed": False},
        ),
        pair(),
    ]
    metrics = aggregate_pairs(rows)
    assert metrics["baseline"]["multi_step_completion"] == 1.0
    assert metrics["candidate"]["multi_step_completion"] == 0.0
    assert metrics["baseline"]["clarification_accuracy"] == 1.0
    assert metrics["candidate"]["clarification_accuracy"] == 0.0


def test_contract_assertions_can_compare_explicit_null():
    raw = load_contract_suite(DEMO / "contracts")[0].model_dump()
    raw["assertions"] = [{"path": "customer.deleted_at", "equals": None}]
    contract = AgenticCompatibilityContract.model_validate(raw)
    assert contract.assertions[0].evaluator_assertion() == {
        "type": "equals",
        "path": "customer.deleted_at",
        "value": None,
    }


def test_warning_can_be_configured_as_failing_status():
    rows = [pair(candidate_tokens=130)]
    policy = evaluate_policy(aggregate_pairs(rows), rows, PolicyConfig(fail_on_warning=True))
    assert policy["verdict"] == "WARNING"
    assert policy["exit_code"] == 1


def test_baseline_validation_never_silently_compares_incompatible_runs():
    warnings = validate_baseline_compatibility(
        {"model_ids": ["old"], "task_suite_hash": "old", "evaluator_hash": "old"},
        models=["new"],
        task_suite_hash="new",
        evaluator_hash="new",
    )
    assert warnings == ["MODEL_CHANGED", "TASK_SUITE_CHANGED", "EVALUATOR_CHANGED"]


def test_mock_paired_runner_preserves_isolation_and_reproducibility():
    contracts = load_contract_suite(DEMO / "contracts")
    settings = Settings(agentseo_max_cost_usd=0, agentseo_max_tasks=10)
    with SessionLocal() as session:
        run = asyncio.run(
            run_compatibility(
                session,
                (DEMO / "baseline" / "openapi.yaml").read_bytes(),
                (DEMO / "candidate-safe" / "openapi.yaml").read_bytes(),
                contracts,
                CompatibilityConfiguration(models=("mock:reliable",), max_cost_usd=0),
                settings,
            )
        )
        results = list(
            session.scalars(
                select(CompatibilityResult).where(
                    CompatibilityResult.compatibility_run_id == run.id
                )
            )
        )
        assert len(results) == 2
        assert all(result.baseline_success and result.candidate_success for result in results)
        assert run.run_metadata["mode"] == "MOCK VALIDATION"
        assert (
            run.run_metadata["baseline_interface_hash"]
            != run.run_metadata["candidate_interface_hash"]
        )
        assert run.actual_cost == 0
        report = compatibility_report(run, results)
        assert "## AgentSEO Compatibility Check" in report
        assert "Traditional protocol compatibility: **PASS**" in report
        assert "Traditional schema compatibility: **PASS**" in report
        assert "Tool calls delta" in report
        assert "### New failure categories" in report
        assert "### Safety regressions" in report
        assert "### Reproducibility" in report


def test_mock_validation_does_not_treat_clock_noise_as_agent_regression():
    contracts = load_contract_suite(DEMO / "contracts")
    settings = Settings(agentseo_max_cost_usd=0, agentseo_max_tasks=10)
    with SessionLocal() as session:
        run = asyncio.run(
            run_compatibility(
                session,
                (DEMO / "baseline" / "openapi.yaml").read_bytes(),
                (DEMO / "candidate-breaking" / "openapi.yaml").read_bytes(),
                contracts,
                CompatibilityConfiguration(models=("mock:reliable",), max_cost_usd=0),
                settings,
            )
        )
        results = list(
            session.scalars(
                select(CompatibilityResult).where(
                    CompatibilityResult.compatibility_run_id == run.id
                )
            )
        )
        assert run.verdict == "PASS"
        assert all(result.regression_type is None for result in results)


def test_cost_limit_blocks_before_provider_execution():
    contracts = load_contract_suite(DEMO / "contracts")
    with SessionLocal() as session, pytest.raises(CompatibilityBudgetError):
        asyncio.run(
            run_compatibility(
                session,
                (DEMO / "baseline" / "openapi.yaml").read_bytes(),
                (DEMO / "candidate-safe" / "openapi.yaml").read_bytes(),
                contracts,
                CompatibilityConfiguration(models=("anthropic:claude-sonnet-5",), max_cost_usd=0),
                Settings(agentseo_max_cost_usd=0),
            )
        )


def test_cli_diff_compare_report_and_exit_codes(tmp_path: Path):
    runner = CliRunner()
    diff = runner.invoke(
        app,
        [
            "diff",
            "--baseline",
            str(DEMO / "baseline" / "openapi.yaml"),
            "--candidate",
            str(DEMO / "candidate-safe" / "openapi.yaml"),
        ],
    )
    assert diff.exit_code == 0
    assert "semantic change" in diff.stdout
    report = tmp_path / "report.md"
    compare = runner.invoke(
        app,
        [
            "compare",
            "--baseline",
            str(DEMO / "baseline" / "openapi.yaml"),
            "--candidate",
            str(DEMO / "candidate-safe" / "openapi.yaml"),
            "--tasks",
            str(DEMO / "contracts"),
            "--models",
            "mock:reliable",
            "--max-cost",
            "0",
            "--report",
            str(report),
        ],
    )
    assert compare.exit_code == 0
    assert report.exists() and "MOCK VALIDATION" in report.read_text(encoding="utf-8")
    blocked = runner.invoke(
        app,
        [
            "compare",
            "--baseline",
            str(DEMO / "baseline" / "openapi.yaml"),
            "--candidate",
            str(DEMO / "candidate-safe" / "openapi.yaml"),
            "--tasks",
            str(DEMO / "contracts"),
            "--models",
            "anthropic:claude-sonnet-5",
            "--max-cost",
            "0",
        ],
    )
    assert blocked.exit_code == 2


def test_cli_expands_provider_shorthand_to_exact_model_ids():
    result = CliRunner().invoke(
        app,
        [
            "compare",
            "--baseline",
            str(DEMO / "baseline" / "openapi.yaml"),
            "--candidate",
            str(DEMO / "candidate-safe" / "openapi.yaml"),
            "--tasks",
            str(DEMO / "contracts"),
            "--models",
            "openai",
            "--max-cost",
            "0",
        ],
    )
    assert result.exit_code == 2
    assert "openai:gpt-4.1-mini" in result.stdout


def test_github_action_has_inputs_secrets_comment_and_exit_propagation():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    for input_name in (
        "spec",
        "task_suite",
        "models",
        "cost_limit",
        "fail_on_warning",
        "baseline_ref",
    ):
        assert f"  {input_name}:" in action
    for secret in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        assert secret in action
    assert "actions/github-script" in action
    assert 'exit "${{ steps.compare.outputs.exit_code }}"' in action


def test_alembic_chain_upgrades_clean_database(tmp_path: Path):
    database = (tmp_path / "migration.db").as_posix()
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "apps" / "backend",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    import sqlite3

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
    assert {"alembic_version", "compatibility_runs", "compatibility_results"} <= tables
