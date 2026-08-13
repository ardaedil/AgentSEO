"""Provider-neutral semantic interface diff primitives for compatibility CI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .openapi_parser import NormalizedTool


class InterfaceChangeType(StrEnum):
    TOOL_ADDED = "TOOL_ADDED"
    TOOL_REMOVED = "TOOL_REMOVED"
    TOOL_RENAMED = "TOOL_RENAMED"
    DESCRIPTION_CHANGED = "DESCRIPTION_CHANGED"
    PARAMETER_ADDED = "PARAMETER_ADDED"
    PARAMETER_REMOVED = "PARAMETER_REMOVED"
    PARAMETER_RENAMED = "PARAMETER_RENAMED"
    PARAMETER_DESCRIPTION_CHANGED = "PARAMETER_DESCRIPTION_CHANGED"
    PARAMETER_REQUIREDNESS_CHANGED = "PARAMETER_REQUIREDNESS_CHANGED"
    ENUM_CHANGED = "ENUM_CHANGED"
    REQUEST_SCHEMA_CHANGED = "REQUEST_SCHEMA_CHANGED"
    RESPONSE_SCHEMA_CHANGED = "RESPONSE_SCHEMA_CHANGED"
    DESTRUCTIVE_SEMANTICS_CHANGED = "DESTRUCTIVE_SEMANTICS_CHANGED"


@dataclass(frozen=True, slots=True)
class InterfaceDiff:
    change_type: str
    tool: str
    field: str
    before: Any
    after: Any
    risk_level: str
    affected_capabilities: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _capabilities(tool: NormalizedTool) -> list[str]:
    return sorted({tool.name, *tool.tags})


def _risk(change: InterfaceChangeType, destructive: bool = False) -> str:
    if destructive or change in {
        InterfaceChangeType.TOOL_REMOVED,
        InterfaceChangeType.DESTRUCTIVE_SEMANTICS_CHANGED,
        InterfaceChangeType.PARAMETER_REQUIREDNESS_CHANGED,
    }:
        return "HIGH"
    if change in {
        InterfaceChangeType.TOOL_RENAMED,
        InterfaceChangeType.PARAMETER_REMOVED,
        InterfaceChangeType.PARAMETER_RENAMED,
        InterfaceChangeType.ENUM_CHANGED,
        InterfaceChangeType.REQUEST_SCHEMA_CHANGED,
    }:
        return "MEDIUM"
    return "LOW"


def _change(
    kind: InterfaceChangeType,
    tool: NormalizedTool,
    field: str,
    before: Any,
    after: Any,
) -> InterfaceDiff:
    return InterfaceDiff(
        change_type=kind.value,
        tool=tool.name,
        field=field,
        before=before,
        after=after,
        risk_level=_risk(kind, tool.is_destructive),
        affected_capabilities=_capabilities(tool),
    )


def _parameter_map(tool: NormalizedTool) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(item.get("in", "query")), str(item.get("name", ""))): item
        for item in tool.parameters
        if item.get("name")
    }


def _enum(parameter: dict[str, Any]) -> list[Any] | None:
    schema = parameter.get("schema", {})
    value = schema.get("enum") if isinstance(schema, dict) else None
    return list(value) if isinstance(value, list) else None


def _parameter_diffs(before: NormalizedTool, after: NormalizedTool) -> list[InterfaceDiff]:
    changes: list[InterfaceDiff] = []
    old = _parameter_map(before)
    new = _parameter_map(after)
    removed = set(old) - set(new)
    added = set(new) - set(old)
    # Treat an unambiguous same-location, same-schema substitution as a rename.
    for old_key in sorted(tuple(removed)):
        candidates = [
            key
            for key in added
            if key[0] == old_key[0] and old[old_key].get("schema") == new[key].get("schema")
        ]
        if len(candidates) == 1:
            new_key = candidates[0]
            changes.append(
                _change(
                    InterfaceChangeType.PARAMETER_RENAMED,
                    after,
                    f"parameters.{old_key[1]}",
                    old_key[1],
                    new_key[1],
                )
            )
            removed.remove(old_key)
            added.remove(new_key)
    for key in sorted(removed):
        changes.append(
            _change(
                InterfaceChangeType.PARAMETER_REMOVED, after, f"parameters.{key[1]}", old[key], None
            )
        )
    for key in sorted(added):
        changes.append(
            _change(
                InterfaceChangeType.PARAMETER_ADDED, after, f"parameters.{key[1]}", None, new[key]
            )
        )
    for key in sorted(set(old) & set(new)):
        left, right = old[key], new[key]
        field = f"parameters.{key[1]}"
        if str(left.get("description", "")) != str(right.get("description", "")):
            changes.append(
                _change(
                    InterfaceChangeType.PARAMETER_DESCRIPTION_CHANGED,
                    after,
                    f"{field}.description",
                    left.get("description", ""),
                    right.get("description", ""),
                )
            )
        if bool(left.get("required")) != bool(right.get("required")):
            changes.append(
                _change(
                    InterfaceChangeType.PARAMETER_REQUIREDNESS_CHANGED,
                    after,
                    f"{field}.required",
                    bool(left.get("required")),
                    bool(right.get("required")),
                )
            )
        if _enum(left) != _enum(right):
            changes.append(
                _change(
                    InterfaceChangeType.ENUM_CHANGED,
                    after,
                    f"{field}.enum",
                    _enum(left),
                    _enum(right),
                )
            )
    return changes


def semantic_diff(
    baseline: list[NormalizedTool], candidate: list[NormalizedTool]
) -> list[InterfaceDiff]:
    """Compare normalized tools, independent of source formatting or key order."""
    changes: list[InterfaceDiff] = []
    base_by_endpoint = {(tool.http_method, tool.path): tool for tool in baseline}
    candidate_by_endpoint = {(tool.http_method, tool.path): tool for tool in candidate}
    for endpoint in sorted(set(base_by_endpoint) - set(candidate_by_endpoint)):
        tool = base_by_endpoint[endpoint]
        changes.append(
            _change(InterfaceChangeType.TOOL_REMOVED, tool, "tool", tool.to_dict(), None)
        )
    for endpoint in sorted(set(candidate_by_endpoint) - set(base_by_endpoint)):
        tool = candidate_by_endpoint[endpoint]
        changes.append(_change(InterfaceChangeType.TOOL_ADDED, tool, "tool", None, tool.to_dict()))
    for endpoint in sorted(set(base_by_endpoint) & set(candidate_by_endpoint)):
        before, after = base_by_endpoint[endpoint], candidate_by_endpoint[endpoint]
        if before.name != after.name:
            changes.append(
                _change(InterfaceChangeType.TOOL_RENAMED, after, "name", before.name, after.name)
            )
        if before.description != after.description:
            changes.append(
                _change(
                    InterfaceChangeType.DESCRIPTION_CHANGED,
                    after,
                    "description",
                    before.description,
                    after.description,
                )
            )
        changes.extend(_parameter_diffs(before, after))
        if before.request_schema != after.request_schema:
            changes.append(
                _change(
                    InterfaceChangeType.REQUEST_SCHEMA_CHANGED,
                    after,
                    "request_schema",
                    before.request_schema,
                    after.request_schema,
                )
            )
        if before.response_schema != after.response_schema:
            changes.append(
                _change(
                    InterfaceChangeType.RESPONSE_SCHEMA_CHANGED,
                    after,
                    "response_schema",
                    before.response_schema,
                    after.response_schema,
                )
            )
        if before.is_destructive != after.is_destructive:
            changes.append(
                _change(
                    InterfaceChangeType.DESTRUCTIVE_SEMANTICS_CHANGED,
                    after,
                    "is_destructive",
                    before.is_destructive,
                    after.is_destructive,
                )
            )
    return changes


def diff_summary(changes: list[InterfaceDiff]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for change in changes:
        counts[change.change_type] = counts.get(change.change_type, 0) + 1
    return {
        "change_count": len(changes),
        "by_type": dict(sorted(counts.items())),
        "affected_tools": sorted({change.tool for change in changes}),
        "affected_capabilities": sorted(
            {capability for change in changes for capability in change.affected_capabilities}
        ),
        "highest_risk": next(
            (
                risk
                for risk in ("HIGH", "MEDIUM", "LOW")
                if any(c.risk_level == risk for c in changes)
            ),
            "NONE",
        ),
    }
