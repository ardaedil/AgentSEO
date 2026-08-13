from collections import Counter, defaultdict
from types import SimpleNamespace

import pytest
from agentseo.phase15b_benchmark import (
    HOLDOUT_GROUPS_BY_CATEGORY,
    assign_phase15b_split,
    generate_phase15b_tasks,
)
from agentseo.sandboxes import SandboxError, create_sandbox


def test_phase15b_benchmark_size_distribution_and_leakage_rules():
    tasks = generate_phase15b_tasks()
    assert len(tasks) == 120
    assert len({task.title for task in tasks}) == 120
    assert Counter(task.title[0] for task in tasks) == {"B": 40, "E": 40, "C": 40}
    assert Counter(task.category for task in tasks) == {
        "ambiguous_tool_selection": 6,
        "clarification_required": 18,
        "clarification_not_required": 12,
        "multi_step": 12,
        "error_recovery": 18,
        "tool_overlap": 6,
        "identifier_routing": 12,
        "constraint_preservation": 6,
        "safety_confirmation": 6,
        "safety_refusal": 6,
        "distractor_tools": 6,
        "post_success": 6,
        "unsupported_semantics": 6,
    }
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
    prohibited_meta_language = ("call the tool", "operation name", "parameter name", "api method")
    for task in tasks:
        lower = task.natural_language_instruction.lower()
        assert not any(name in lower for name in operation_names)
        assert not any(phrase in lower for phrase in prohibited_meta_language)


def test_phase15b_split_is_exact_stratified_and_keeps_paraphrases_together():
    generated = generate_phase15b_tasks()
    tasks = [
        SimpleNamespace(
            id=f"task-{index}",
            title=task.title,
            category=task.category,
            initial_state=task.initial_state,
            phase15_split=None,
        )
        for index, task in enumerate(generated)
    ]
    first = assign_phase15b_split(tasks)
    second = assign_phase15b_split(tasks)
    assert first == second
    assert Counter(first.values()) == {"development": 80, "holdout": 40}
    groups: dict[str, set[str]] = defaultdict(set)
    holdout_categories: Counter[str] = Counter()
    for task in tasks:
        group = task.initial_state["_evaluation"]["scenario_group"]
        groups[group].add(task.phase15_split)
        if task.phase15_split == "holdout":
            holdout_categories[task.category] += 1
    assert all(len(splits) == 1 for splits in groups.values())
    assert holdout_categories == Counter(
        {category: groups * 2 for category, groups in HOLDOUT_GROUPS_BY_CATEGORY.items()}
    )


def test_task_scoped_faults_support_replacement_and_temporary_retry():
    sandbox = create_sandbox("billing")
    state = sandbox.snapshot()
    state["_faults"] = [
        {
            "tool": "get_customer",
            "arguments": {"id": "cus_legacy"},
            "code": "NOT_FOUND",
            "message": "Moved.",
            "replacement_id": "cus_john",
            "remaining": 1,
        },
        {
            "tool": "get_customer",
            "arguments": {"id": "cus_john"},
            "code": "TEMPORARY_UNAVAILABLE",
            "message": "Retry once.",
            "remaining": 1,
        },
    ]
    sandbox.reset(state)
    with pytest.raises(SandboxError, match="cus_john") as moved:
        sandbox.execute("get_customer", {"id": "cus_legacy"})
    assert moved.value.code == "NOT_FOUND"
    with pytest.raises(SandboxError) as temporary:
        sandbox.execute("get_customer", {"id": "cus_john"})
    assert temporary.value.code == "TEMPORARY_UNAVAILABLE"
    assert sandbox.execute("get_customer", {"id": "cus_john"})["id"] == "cus_john"
