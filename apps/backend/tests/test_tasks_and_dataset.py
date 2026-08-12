from pathlib import Path

import pytest
from agentseo.openapi_parser import parse_openapi
from agentseo.task_generation import generate_template_tasks, validate_generated_task

ROOT = Path(__file__).parents[3]


def test_dataset_contains_more_than_fifty_tasks_and_fifteen_operations():
    total_tasks = 0
    total_tools = 0
    for domain in ("billing", "ecommerce", "crm"):
        _, tools = parse_openapi((ROOT / f"examples/{domain}/openapi.yaml").read_bytes())
        tasks = generate_template_tasks(tools, domain)
        total_tools += len(tools)
        total_tasks += len(tasks)
        assert {task.difficulty for task in tasks} >= {1, 5, 7}
        assert not any(
            operation.name.lower() in task.natural_language_instruction.lower()
            for task in tasks
            for operation in tools
        )
    assert total_tools >= 15
    assert total_tasks == 53


def test_llm_task_validation_rejects_unknown_tools():
    with pytest.raises(ValueError, match="unknown tools"):
        validate_generated_task(
            {
                "title": "bad",
                "natural_language_instruction": "Do it",
                "required_tools": ["invented_tool"],
            },
            {"real_tool"},
        )


def test_llm_task_validation_accepts_structured_task():
    task = validate_generated_task(
        {
            "title": "Get record",
            "natural_language_instruction": "Retrieve record 123",
            "difficulty": 2,
            "required_tools": ["get_record"],
            "expected_final_state": [{"type": "exists", "path": "records.123"}],
        },
        {"get_record"},
    )
    assert task.required_tools == ["get_record"]
    assert task.difficulty == 2
