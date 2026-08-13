from collections import Counter
from pathlib import Path

from agentseo.interfaces import mutate_snapshot
from agentseo.openapi_parser import parse_openapi
from agentseo.phase15b_r2_benchmark import (
    PHASE15B_R2_EVALUATOR_VERSION,
    R2_UNCALIBRATED_FAMILIES,
    generate_phase15b_r2_tasks,
    phase15b_r2_families,
)
from agentseo.sandboxes import create_sandbox


def test_r2_candidate_pool_has_first_class_families_and_hard_distribution():
    families = phase15b_r2_families()
    tasks = generate_phase15b_r2_tasks()
    assert len(families) == 40
    assert len(tasks) == 120
    assert len({task.title for task in tasks}) == 120
    assert len({task.task_family for task in tasks}) == 40
    assert all(sum(task.task_family == family.name for task in tasks) == 3 for family in families)
    assert Counter(task.category for task in tasks) == {
        "clarification_required": 12,
        "clarification_not_required": 12,
        "multi_step": 12,
        "error_recovery": 12,
        "safety_destructive": 12,
        "tool_overlap": 12,
        "identifier_routing": 12,
        "constraint_preservation": 12,
        "unsupported_semantics": 12,
        "post_success": 12,
    }
    assert Counter(task.difficulty for task in tasks) == {6: 33, 7: 51, 8: 36}
    assert len(R2_UNCALIBRATED_FAMILIES) == 12
    assert all(
        task.initial_state["_evaluation"]["evaluator_version"] == PHASE15B_R2_EVALUATOR_VERSION
        for task in tasks
    )


def test_r2_instructions_do_not_leak_agent_interface_identifiers():
    operation_names = {
        "search_customers",
        "find_customer",
        "get_customer",
        "delete_customer",
        "list_subscriptions",
        "cancel_subscription",
        "terminate_account",
        "list_invoices",
        "refund_invoice",
        "list_orders",
        "get_order",
        "refund_order",
        "list_shipments",
        "search_companies",
        "get_company",
        "list_opportunities",
        "assign_opportunity",
        "delete_opportunity",
        "search_owners",
        "list_contacts",
    }
    parameter_names = {
        "customer_id",
        "subscription_id",
        "order_id",
        "opportunity_id",
        "owner_id",
        "at_period_end",
        "min_value",
    }
    for task in generate_phase15b_r2_tasks():
        lower = task.natural_language_instruction.lower()
        assert not any(name in lower for name in operation_names | parameter_names)
        assert "call the tool" not in lower
        assert "api" not in lower


def test_minimum_value_filter_is_inclusive_for_conditional_routing():
    sandbox = create_sandbox("crm")
    rows = sandbox.execute(
        "list_opportunities",
        {"company_id": "co_acme", "status": "open", "min_value": 25000},
    )
    assert [row["id"] for row in rows] == ["opp_1"]


def test_r2_interfaces_are_development_evidence_mutations_without_new_examples():
    root = Path(__file__).resolve().parents[3]
    _, tools = parse_openapi((root / "examples" / "billing" / "openapi.yaml").read_bytes())
    canonical = [tool.to_dict() for tool in tools]
    baseline, _ = mutate_snapshot(canonical, "baseline")
    baseline_examples = sum(
        len(tool.get("tool_metadata", {}).get("examples", [])) for tool in baseline
    )
    for variant in (
        "phase15b_r2_general",
        "phase15b_r2_gpt",
        "phase15b_r2_claude",
        "phase15b_r2_gemini",
    ):
        snapshot, mutations = mutate_snapshot(canonical, variant)
        assert mutations
        assert all("R2" in mutation.rationale for mutation in mutations)
        assert sum(len(tool.get("description", "")) for tool in snapshot) > sum(
            len(tool.get("description", "")) for tool in baseline
        )
        assert (
            sum(len(tool.get("tool_metadata", {}).get("examples", [])) for tool in snapshot)
            == baseline_examples
        )
