"""Apply approved R2 evaluator-equivalence fixes to stored calibration traces.

No provider calls or trace mutations are performed. The script updates the task evaluator
configuration from the current frozen source and re-scores only deterministic fields that
can be reconstructed exactly from persisted tool-call events.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from agentseo.database import SessionLocal
from agentseo.models import BenchmarkTask, TaskRun, TraceEvent
from agentseo.phase15b_r2_benchmark import generate_phase15b_r2_tasks
from agentseo.runner import _semantic_value_matches
from sqlalchemy import select


def _passed(result: dict[str, Any]) -> bool:
    return all(
        (
            all(item.get("passed", False) for item in result.get("assertions", [])),
            result.get("clarification_passed", True),
            result.get("tool_requirements_passed", True),
            result.get("forbidden_tools_avoided", True),
            result.get("behavior_passed", True),
            result.get("required_tool_sequence_passed", True),
            result.get("targeted_clarification_passed", True),
            result.get("tool_call_limit_passed", True),
            result.get("semantic_arguments_correct", True),
            result.get("error_recovery_passed", True),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_id")
    args = parser.parse_args()
    generated_by_title = {task.title: task for task in generate_phase15b_r2_tasks()}
    promoted: list[dict[str, str]] = []

    with SessionLocal() as session:
        tasks = list(session.scalars(select(BenchmarkTask)))
        for task in tasks:
            generated = generated_by_title.get(task.title)
            if generated is None:
                raise RuntimeError(f"Current R2 source does not define task {task.title}")
            task.initial_state = generated.initial_state

        for task_run, task in session.execute(
            select(TaskRun, BenchmarkTask)
            .join(BenchmarkTask, TaskRun.task_id == BenchmarkTask.id)
            .where(TaskRun.experiment_id == args.experiment_id)
        ):
            was_success = task_run.success
            result = dict(task_run.evaluator_result or {})
            config = (task.initial_state or {}).get("_evaluation", {})
            calls = [
                event.payload
                for event in session.scalars(
                    select(TraceEvent)
                    .where(
                        TraceEvent.task_run_id == task_run.id,
                        TraceEvent.event_type == "TOOL_CALLED",
                    )
                    .order_by(TraceEvent.sequence)
                )
            ]
            selected = [str(call.get("canonical_tool")) for call in calls]
            required_sequence = [str(item) for item in config.get("required_tool_sequence", [])]
            cursor = 0
            for tool in selected:
                if cursor < len(required_sequence) and tool == required_sequence[cursor]:
                    cursor += 1
            expectations = config.get("argument_expectations", [])
            semantic_correct = all(
                any(
                    call.get("canonical_tool") == expectation.get("tool")
                    and all(
                        _semantic_value_matches(
                            key,
                            call.get("canonical_arguments", {}).get(key),
                            expected,
                        )
                        for key, expected in expectation.get("arguments", {}).items()
                    )
                    for call in calls
                )
                for expectation in expectations
            )
            maximum = config.get("expected_max_tool_calls")
            result.update(
                {
                    "required_tool_sequence": required_sequence,
                    "required_tool_sequence_passed": cursor == len(required_sequence),
                    "expected_max_tool_calls": maximum,
                    "tool_call_limit_passed": maximum is None or len(calls) <= int(maximum),
                    "semantic_arguments_evaluated": bool(expectations),
                    "semantic_arguments_correct": semantic_correct,
                    "evaluator_equivalence_readjudicated": True,
                }
            )
            result["passed"] = _passed(result)
            task_run.evaluator_result = result
            task_run.success = bool(result["passed"])
            if task_run.success and not was_success:
                task_run.failure_category = None
                task_run.failure_explanation = None
                promoted.append(
                    {
                        "task_run_id": task_run.id,
                        "model": task_run.model_identifier,
                        "task_family": task.task_family,
                    }
                )
            elif was_success and not task_run.success:
                raise RuntimeError(f"Evaluator repair regressed successful task run {task_run.id}")
        session.commit()
    print(json.dumps({"provider_calls": 0, "trace_events_modified": False, "promoted": promoted}))


if __name__ == "__main__":
    main()
