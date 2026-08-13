from collections import Counter

from agentseo.phase15b_r2_benchmark import (
    PHASE15B_R2_EVALUATOR_VERSION,
    R2_UNCALIBRATED_FAMILIES,
    generate_phase15b_r2_tasks,
    phase15b_r2_families,
)


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
        task.initial_state["_evaluation"]["evaluator_version"]
        == PHASE15B_R2_EVALUATOR_VERSION
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
