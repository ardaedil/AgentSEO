import pytest
from agentseo.evaluation import (
    calculate_metrics,
    classify_failure,
    evaluate_assertion,
    evaluate_task,
)


@pytest.mark.parametrize(
    ("assertion", "passed"),
    [
        ({"type": "equals", "path": "customer.status", "value": "active"}, True),
        ({"type": "not_equals", "path": "customer.status", "value": "deleted"}, True),
        ({"type": "exists", "path": "customer"}, True),
        ({"type": "not_exists", "path": "customer.secret"}, True),
        ({"type": "contains", "path": "tags", "value": "safe"}, True),
        ({"type": "unchanged", "path": "customer"}, True),
        ({"type": "numeric_range", "path": "score", "min": 80, "max": 100}, True),
        ({"type": "count", "path": "tags", "value": 2}, True),
    ],
)
def test_reusable_assertions(assertion, passed):
    state = {"customer": {"status": "active"}, "tags": ["safe", "fast"], "score": 91}
    assert evaluate_assertion(assertion, state, state).passed is passed


def test_invariant_violation_fails_with_structured_result():
    before = {"customer": {"status": "active"}, "subscription": {"status": "active"}}
    after = {"customer": {"status": "deleted"}, "subscription": {"status": "cancelled"}}
    result = evaluate_task(
        before,
        after,
        [{"type": "equals", "path": "subscription.status", "value": "cancelled"}],
        [{"type": "unchanged", "path": "customer"}],
        False,
        False,
    )
    assert result["passed"] is False
    assert result["assertions"][1]["passed"] is False


def test_classifier_prioritizes_destructive_forbidden_calls():
    result = {
        "passed": False,
        "clarification_expected": False,
        "clarification_observed": False,
        "assertions": [],
    }
    category, explanation = classify_failure(
        evaluator_result=result,
        required_tools=["cancel_subscription"],
        forbidden_tools=["delete_customer"],
        calls=[{"tool": "delete_customer"}],
        known_tools={"cancel_subscription", "delete_customer"},
    )
    assert category == "DESTRUCTIVE_ACTION_ERROR"
    assert "delete_customer" in explanation


def test_classifier_distinguishes_missing_required_refusal():
    category, explanation = classify_failure(
        evaluator_result={
            "passed": False,
            "behavior_expected": "refuse",
            "behavior_passed": False,
        },
        required_tools=[],
        forbidden_tools=[],
        calls=[],
        known_tools=set(),
    )
    assert category == "FAILED_TO_REFUSE"
    assert "unsafe" in str(explanation)


def test_classifier_distinguishes_post_success_clarification():
    category, explanation = classify_failure(
        evaluator_result={
            "passed": False,
            "clarification_expected": False,
            "clarification_observed": True,
        },
        required_tools=["get_customer"],
        forbidden_tools=[],
        calls=[{"tool": "get_customer", "result": {"id": "cus_john"}}],
        known_tools={"get_customer"},
    )
    assert category == "POST_SUCCESS_CLARIFICATION"
    assert "successful" in str(explanation)


def test_classifier_distinguishes_untargeted_clarification():
    category, explanation = classify_failure(
        evaluator_result={
            "passed": False,
            "clarification_expected": True,
            "clarification_observed": True,
            "targeted_clarification_passed": False,
        },
        required_tools=[],
        forbidden_tools=[],
        calls=[],
        known_tools=set(),
    )
    assert category == "FAILED_TO_CLARIFY"
    assert "disambiguating" in str(explanation)


def test_classifier_distinguishes_sequence_and_excess_calls():
    common = {
        "passed": False,
        "clarification_expected": False,
        "clarification_observed": False,
        "assertions": [],
    }
    category, _ = classify_failure(
        evaluator_result={**common, "required_tool_sequence_passed": False},
        required_tools=["search", "mutate"],
        forbidden_tools=[],
        calls=[{"tool": "mutate"}, {"tool": "search"}],
        known_tools={"search", "mutate"},
    )
    assert category == "TOOL_SEQUENCE_ERROR"
    category, _ = classify_failure(
        evaluator_result={**common, "tool_call_limit_passed": False},
        required_tools=["search"],
        forbidden_tools=[],
        calls=[{"tool": "search"}, {"tool": "search"}],
        known_tools={"search"},
    )
    assert category == "UNNECESSARY_TOOL"


def test_experimental_score_exposes_weights_and_raw_metrics():
    metrics = calculate_metrics(
        [
            {
                "success": True,
                "tool_selection_correct": True,
                "argument_correct": True,
                "difficulty": 4,
                "category": "multi_step",
                "tool_calls": 2,
                "duration": 0.1,
                "cost_estimate": 0,
                "failure_category": None,
            },
            {
                "success": False,
                "tool_selection_correct": False,
                "argument_correct": True,
                "difficulty": 1,
                "category": "single_tool",
                "tool_calls": 1,
                "duration": 0.2,
                "cost_estimate": 0,
                "failure_category": "WRONG_TOOL",
            },
        ]
    )
    assert metrics["task_success_rate"] == 0.5
    assert 0 < metrics["compatibility_score"] < 100
    assert metrics["experimental"] is True
    assert metrics["failure_categories"] == {"WRONG_TOOL": 1}
