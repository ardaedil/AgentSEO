"""Generate R2 development-only failure ledgers from persisted V0 traces."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from agentseo.database import SessionLocal
from agentseo.models import BenchmarkTask, TaskRun, TraceEvent
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "phase15b_r2"
MODEL_FILES = {
    "openai:gpt-4.1-mini": "gpt",
    "anthropic:claude-sonnet-5": "claude",
    "google:gemini-3.6-flash": "gemini",
}

CAUSES: dict[str, tuple[str, str, str]] = {
    "POST_SUCCESS_CLARIFICATION": (
        "INTERFACE_RELATED",
        "The interface did not make the completed-read or completed-mutation boundary salient enough.",
        "Add concise stop-after-result guidance while preserving explicitly requested verification.",
    ),
    "UNNECESSARY_CLARIFICATION": (
        "LIKELY_INTERFACE_RELATED",
        "The interface did not distinguish missing target information from a known unsupported or complete outcome.",
        "State exactly when clarification is required and when to explain or act without asking.",
    ),
    "WRONG_TOOL": (
        "INTERFACE_RELATED",
        "Identifier routing or the discovery/action boundary was insufficiently explicit.",
        "Clarify ID prefixes, name/email discovery, and semantic boundaries between related tools.",
    ),
    "MAX_ITERATIONS": (
        "LIKELY_INTERFACE_RELATED",
        "Error recovery lacked an explicit no-identical-retry or early-clarification boundary.",
        "Add bounded recovery instructions tied to returned error semantics.",
    ),
    "UNNECESSARY_TOOL": (
        "LIKELY_INTERFACE_RELATED",
        "The interface allowed redundant discovery, verification, or cross-object exploration.",
        "Add negative-use and terminal guidance to the relevant tool descriptions.",
    ),
    "TOOL_SEQUENCE_ERROR": (
        "LIKELY_INTERFACE_RELATED",
        "Dependencies between retrieval, conditional choice, mutation, and verification were not salient.",
        "Describe the local prerequisite or recovery transition without encoding benchmark-specific workflows.",
    ),
    "DESTRUCTIVE_ACTION_ERROR": (
        "INTERFACE_RELATED",
        "A related but forbidden tool lacked a sufficiently clear semantic or safety boundary.",
        "Add an explicit negative-use instruction at the confused tool boundary.",
    ),
    "FAILED_TO_REFUSE": (
        "LIKELY_INTERFACE_RELATED",
        "The destructive tool description did not explicitly cover concealment or audit-obstruction requests.",
        "State that evidence-concealment and audit-obstruction requests must be refused.",
    ),
    "UNKNOWN": (
        "NOT_INTERFACE_RELATED",
        "The stored deterministic checks did not isolate a tool-interface cause.",
        "Do not mutate the interface without stronger trace evidence.",
    ),
}


def _clean(text: str, limit: int = 140) -> str:
    return " ".join(text.replace("|", "/").split())[:limit]


def _trace_evidence(events: list[TraceEvent]) -> tuple[list[str], str]:
    tools = [
        str(event.payload.get("canonical_tool", event.payload.get("tool", "?")))
        for event in events
        if event.event_type == "TOOL_CALLED"
    ]
    terminal = next(
        (
            f"{event.event_type}: {_clean(str(event.payload.get('content', '')))}"
            for event in reversed(events)
            if event.event_type in {"CLARIFICATION", "FINAL_RESPONSE"}
        ),
        next(
            (
                f"ERROR: {_clean(str(event.payload.get('message', event.payload.get('code', ''))))}"
                for event in reversed(events)
                if event.event_type == "ERROR"
            ),
            "",
        ),
    )
    return tools, terminal


def _markdown(model: str, rows: list[dict[str, Any]]) -> str:
    failures = Counter(row["failure"] for row in rows)
    relations = Counter(row["relationship"] for row in rows)
    lines = [
        f"# Phase 1.5B R2 V0 development failures — {model}",
        "",
        "This ledger uses only the 84-task R2 development split. The sealed holdout was not read or run.",
        "",
        f"- Failed observations: {len(rows)} / 84",
        f"- Failure categories: {dict(sorted(failures.items()))}",
        f"- Interface attribution: {dict(sorted(relations.items()))}",
        "",
        "| Family | Failure | Trace evidence | Attribution | Suspected cause | Proposed interface change |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        trace = " → ".join(row["tools"]) or "no tool call"
        if row["terminal"]:
            trace += f"; {row['terminal']}"
        lines.append(
            "| {family} | {failure} | {trace} | {relationship} | {cause} | {change} |".format(
                family=row["task_family"],
                failure=row["failure"],
                trace=trace,
                relationship=row["relationship"],
                cause=row["suspected_cause"],
                change=row["proposed_change"],
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Attribution is a design hypothesis, not a claim that the interface caused every failure. "
            "Model reasoning variance, strict but audited workflow constraints, and provider latency remain alternative explanations.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_id")
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
    with SessionLocal() as session:
        query = (
            select(TaskRun, BenchmarkTask)
            .join(BenchmarkTask, TaskRun.task_id == BenchmarkTask.id)
            .where(
                TaskRun.experiment_id == args.experiment_id,
                TaskRun.success.is_(False),
                BenchmarkTask.phase15_split == "development",
            )
            .order_by(TaskRun.model_identifier, BenchmarkTask.task_family, TaskRun.id)
        )
        for task_run, task in session.execute(query):
            events = list(
                session.scalars(
                    select(TraceEvent)
                    .where(TraceEvent.task_run_id == task_run.id)
                    .order_by(TraceEvent.sequence)
                )
            )
            tools, terminal = _trace_evidence(events)
            relationship, cause, change = CAUSES.get(
                str(task_run.failure_category), CAUSES["UNKNOWN"]
            )
            rows.append(
                {
                    "model": task_run.model_identifier,
                    "task_run_id": task_run.id,
                    "task_id": task.id,
                    "task_family": task.task_family,
                    "task_category": task.category,
                    "failure": task_run.failure_category,
                    "tools": tools,
                    "terminal": terminal,
                    "relationship": relationship,
                    "suspected_cause": cause,
                    "proposed_change": change,
                }
            )

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_ROOT / "development_failure_ledger.json").write_text(
        json.dumps(
            {
                "experiment_id": args.experiment_id,
                "split": "development",
                "holdout_accessed": False,
                "rows": rows,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    for model, slug in MODEL_FILES.items():
        model_rows = [row for row in rows if row["model"] == model]
        (ROOT / "docs" / f"phase15b_r2_{slug}_failure_analysis.md").write_text(
            _markdown(model, model_rows), encoding="utf-8"
        )

    by_model = Counter(row["model"] for row in rows)
    by_failure = Counter(row["failure"] for row in rows)
    by_relation = Counter(row["relationship"] for row in rows)
    comparison = [
        "# Phase 1.5B R2 V0 failure-profile comparison",
        "",
        "Only R2 development observations are included; the sealed holdout remained unopened.",
        "",
        f"- Failures by model: {dict(sorted(by_model.items()))}",
        f"- Failures by category: {dict(sorted(by_failure.items()))}",
        f"- Attribution hypotheses: {dict(sorted(by_relation.items()))}",
        "",
        "GPT is dominated by post-success clarification and identifier/tool routing. Claude's smaller "
        "failure set concentrates on unnecessary terminal behavior and unsupported-operation handling. "
        "Gemini is distinguished by repeated-call/max-iteration recovery failures and incomplete multi-call "
        "status comparisons. Shared unnecessary-tool failures justify a concise general variant; divergent "
        "patterns justify separately frozen model-specific variants.",
        "",
    ]
    (ROOT / "docs" / "phase15b_r2_failure_profile_comparison.md").write_text(
        "\n".join(comparison), encoding="utf-8"
    )
    print(json.dumps({"failures": len(rows), "by_model": by_model, "by_failure": by_failure}))


if __name__ == "__main__":
    main()
