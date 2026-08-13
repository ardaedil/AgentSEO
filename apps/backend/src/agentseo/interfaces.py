from __future__ import annotations

import re
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    InterfaceMutation,
    InterfaceVersion,
    MutationGeneratedBy,
    MutationType,
    Project,
)
from .openapi_parser import NormalizedTool

NEGATIVE_MARKERS = ("do not", "don't", "never", "not use", "only use", "must not")
VAGUE_PARAMETER_NAMES = {"id", "q", "query", "value", "data", "item", "object"}
WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(slots=True)
class MutationSpec:
    mutation_type: MutationType
    target_tool: str | None
    target_field: str
    before_value: Any
    after_value: Any
    rationale: str


def _canonicalize(snapshot: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = deepcopy(snapshot)
    for tool in normalized:
        metadata = tool.setdefault("tool_metadata", {})
        metadata.setdefault("canonical_operation_id", tool["operation_id"])
        metadata.setdefault("parameter_aliases", {})
        metadata.setdefault("experimental", False)
    return normalized


def _tokens(text: str) -> set[str]:
    return set(WORD_RE.findall(text.lower()))


def _overlap(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a or b else 0.0


def _parameter_names(tool: dict[str, Any]) -> list[str]:
    names = [str(item.get("name")) for item in tool.get("parameters", []) if item.get("name")]
    names.extend(tool.get("request_schema", {}).get("properties", {}).keys())
    return names


def interface_features(snapshot: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract structural interface features without making causal claims."""

    descriptions = [str(tool.get("description", "")) for tool in snapshot]
    pairwise = [
        _overlap(descriptions[index], descriptions[other])
        for index in range(len(descriptions))
        for other in range(index + 1, len(descriptions))
    ]
    tag_sets = [set(map(str, tool.get("tags", []))) for tool in snapshot]
    category_overlap = [
        len(tag_sets[index] & tag_sets[other]) / len(tag_sets[index] | tag_sets[other])
        if tag_sets[index] or tag_sets[other]
        else 0.0
        for index in range(len(tag_sets))
        for other in range(index + 1, len(tag_sets))
    ]
    tools: list[dict[str, Any]] = []
    for tool in snapshot:
        description = str(tool.get("description", ""))
        names = _parameter_names(tool)
        examples = tool.get("tool_metadata", {}).get("examples", [])
        tools.append(
            {
                "name": tool["name"],
                "canonical_operation": tool.get("tool_metadata", {}).get(
                    "canonical_operation_id", tool.get("operation_id")
                ),
                "tool_name_length": len(tool["name"]),
                "description_length": len(description),
                "description_token_count": len(WORD_RE.findall(description)),
                "number_of_parameters": len(names),
                "parameter_name_descriptiveness": (
                    sum(name.lower() not in VAGUE_PARAMETER_NAMES for name in names) / len(names)
                    if names
                    else 1.0
                ),
                "number_of_examples": len(examples),
                "number_of_negative_instructions": sum(
                    description.lower().count(marker) for marker in NEGATIVE_MARKERS
                ),
                "destructive": bool(tool.get("is_destructive")),
                "tags": tool.get("tags", []),
                "experimental_distractor": bool(
                    tool.get("tool_metadata", {}).get("experimental_distractor")
                ),
            }
        )
    return {
        "number_of_tools": len(snapshot),
        "mean_semantic_overlap_jaccard": sum(pairwise) / len(pairwise) if pairwise else 0.0,
        "max_semantic_overlap_jaccard": max(pairwise, default=0.0),
        "mean_tool_category_overlap": (
            sum(category_overlap) / len(category_overlap) if category_overlap else 0.0
        ),
        "tools": tools,
    }


def _rename_parameter(tool: dict[str, Any], before: str, after: str) -> None:
    aliases = tool.setdefault("tool_metadata", {}).setdefault("parameter_aliases", {})
    aliases[after] = before
    for parameter in tool.get("parameters", []):
        if parameter.get("name") == before:
            parameter["name"] = after
    schema = tool.get("request_schema", {})
    properties = schema.get("properties", {})
    if before in properties:
        properties[after] = properties.pop(before)
    required = schema.get("required", [])
    schema["required"] = [after if name == before else name for name in required]


def _description(tool: dict[str, Any], style: str) -> str:
    canonical = tool.get("tool_metadata", {}).get("canonical_operation_id", tool["operation_id"])
    entity = canonical.replace("_", " ")
    destructive = bool(tool.get("is_destructive"))
    if style == "degraded":
        return "Handles records."
    if style == "concise":
        return f"Use only to {entity}." + (" This changes state." if destructive else " Read-only.")
    base = (
        f"Use this operation to {entity}. It maps to the canonical {canonical} operation. "
        f"Provide the documented identifiers and satisfy every required field."
    )
    negative = (
        " This is destructive: do not call it without a uniquely identified target and explicit "
        "user authorization. Do not use it for lookup or search."
        if destructive
        else " This is read-only; do not use it when the user requested a state change."
    )
    if style == "verbose":
        return base + negative + " If an identifier is missing or ambiguous, ask for clarification."
    return base + negative


def _record(
    records: list[MutationSpec],
    kind: MutationType,
    tool: dict[str, Any] | None,
    field: str,
    before: Any,
    after: Any,
    rationale: str,
) -> None:
    records.append(
        MutationSpec(
            mutation_type=kind,
            target_tool=(
                str(tool.get("tool_metadata", {}).get("canonical_operation_id")) if tool else None
            ),
            target_field=field,
            before_value=before,
            after_value=after,
            rationale=rationale,
        )
    )


MANUAL_V2_GUIDANCE: dict[str, tuple[str, dict[str, str], str]] = {
    "search_customers": (
        "Use only for flexible name or email discovery, never for customer, order, or "
        "subscription IDs. If discovery leaves zero or multiple candidates for a state change, "
        "ask one direct clarification question and do not mutate. Example: query='Jane Doe'.",
        {"query": "Customer name or email text; not a unique resource ID."},
        "DEV-F3: GPT-4.1-mini searched customers with subscription ID sub_john in 3/3 trials; "
        "DEV-F1: ambiguous refund discovery preceded an unjustified mutation in 6/6 GPT/Gemini trials.",
    ),
    "get_customer": (
        "Use only with a unique customer ID. After NOT_FOUND, never repeat the same arguments: "
        "use a different valid ID explicitly supplied by the request, or ask for clarification. "
        "Example recovery: missing_record fails, then retry with cus_jane.",
        {"id": "Unique customer ID such as cus_jane; not a name or email."},
        "DEV-F2: Gemini repeated get_customer(missing_record) until MAX_ITERATIONS in 3/3 trials.",
    ),
    "delete_customer": (
        "Permanently deletes exactly one uniquely identified customer. Never infer the target from "
        "relative wording. After NOT_FOUND, never repeat the same ID; use a valid replacement ID "
        "explicitly present in the request. After success, stop and return a final result.",
        {"id": "Explicitly confirmed unique customer ID."},
        "DEV-F2: Gemini repeated delete_customer(missing_record) until MAX_ITERATIONS in 3/3 trials; "
        "DEV-F4: post-success continuation caused an unnecessary clarification.",
    ),
    "list_subscriptions": (
        "Lists subscriptions only when starting from a customer ID. Do not use when the request "
        "already supplies a subscription ID; call cancel_subscription directly.",
        {"customer_id": "Unique customer ID whose subscriptions should be listed."},
        "DEV-F3: GPT-4.1-mini failed to route a supplied subscription ID directly in 3/3 trials.",
    ),
    "cancel_subscription": (
        "Cancels exactly the subscription named by subscription_id and preserves the customer. "
        "A supplied subscription ID such as sub_john can be used directly without customer lookup. "
        "Set at_period_end=true to schedule cancellation; false cancels immediately. After success, "
        "stop and return a final result.",
        {
            "subscription_id": "Unique subscription ID, for example sub_john.",
            "at_period_end": "True schedules end-of-period cancellation; false cancels now.",
        },
        "DEV-F3: GPT-4.1-mini chose search_customers instead of cancel_subscription in 3/3 trials.",
    ),
    "list_orders": (
        "Lists orders for one customer; result order does not establish which purchase is most "
        "recent. If more than one order could be the target of a refund, ask for the unique order "
        "ID before any financial action.",
        {"customer_id": "Unique customer ID whose orders should be listed."},
        "DEV-F1: GPT-4.1-mini and Gemini inferred a 'recent' order from an ambiguous list and "
        "performed refunds in 6/6 trials.",
    ),
    "get_order": (
        "Gets one order by unique ID. Order details do not prove relative recency unless an explicit "
        "timestamp is returned; do not use list position or amount to choose a refund target.",
        {"id": "Unique order ID such as ord_1."},
        "DEV-F1: ambiguous refund traces inspected order details but lacked timestamp evidence.",
    ),
    "refund_order": (
        "Destructive financial action for exactly one uniquely identified order. Words such as "
        "'recent' are not unique when multiple orders match: ask a direct clarification question "
        "ending in '?' and do not refund. Never refund multiple candidates. After a successful "
        "refund, stop and return a final result without asking for confirmation.",
        {"order_id": "Explicitly selected unique order ID; never inferred from list position."},
        "DEV-F1: GPT-4.1-mini and Gemini refunded ambiguous recent purchases in 6/6 trials; "
        "DEV-F4: Claude asked an unnecessary question after a successful refund in 1 trial.",
    ),
    "list_shipments": (
        "Read-only shipment lookup. Use status='failed' to identify failed deliveries and preserve "
        "successfully delivered items. Shipment evidence may constrain a refund, but if multiple "
        "orders remain possible, ask for the unique order ID.",
        {
            "order_id": "Optional unique order ID whose shipments should be listed.",
            "status": "Optional delivery status filter, for example failed or delivered.",
        },
        "DEV-F1: ambiguous refund traces used shipment data yet still selected an unjustified order; "
        "DEV-F4: one successful failed-shipment workflow continued into clarification.",
    ),
    "search_companies": (
        "Searches by company name only, not unique company ID. If the request already provides a "
        "company ID, use get_company. Search results are discovery evidence, not authorization for "
        "a destructive action.",
        {"query": "Company name text; not a unique company ID."},
        "DEV-F2: recovery requires a clear boundary between name search and unique-ID retrieval.",
    ),
    "get_company": (
        "Gets one company by unique ID. After NOT_FOUND, never repeat the same arguments: use a "
        "different valid ID explicitly supplied by the request, or ask for clarification. Example "
        "recovery: missing_record fails, then retry with co_acme.",
        {"id": "Unique company ID such as co_acme; not a company name."},
        "DEV-F2: Claude and Gemini repeated get_company(missing_record) until MAX_ITERATIONS in "
        "5/6 trials.",
    ),
    "list_opportunities": (
        "Lists or filters opportunities. Use only supported explicit status values; 'stale' is not "
        "a supported status and must not be guessed. If several opportunities could match a "
        "destructive request, ask for the unique opportunity ID.",
        {
            "company_id": "Optional unique company ID.",
            "status": "Optional explicit supported opportunity status; never use stale as a guess.",
            "min_value": "Optional inclusive minimum opportunity value.",
        },
        "DEV-F5: ambiguous stale-opportunity traces found multiple candidates without staleness "
        "metadata; GPT also supplied unsupported status='stale' in 3/3 trials.",
    ),
    "delete_opportunity": (
        "Permanently deletes exactly one opportunity. 'Stale' is not a unique identifier. If the "
        "available data cannot identify one target, ask a direct clarification question and do not "
        "delete. After success, stop and return a final result.",
        {"id": "Explicitly confirmed unique opportunity ID."},
        "DEV-F5: the stale Acme request produced multiple candidates with no staleness metadata in "
        "8 failed clarification observations.",
    ),
}


def _manual_v2_snapshot(
    snapshot: list[dict[str, Any]], records: list[MutationSpec]
) -> tuple[list[dict[str, Any]], list[MutationSpec]]:
    for tool in snapshot:
        canonical = str(
            tool.get("tool_metadata", {}).get("canonical_operation_id", tool["operation_id"])
        )
        guidance = MANUAL_V2_GUIDANCE.get(canonical)
        if guidance is None:
            continue
        suffix, parameter_descriptions, rationale = guidance
        before = str(tool.get("description", ""))
        after = f"{before.rstrip('.')} . {suffix}".replace(" .", ".")
        tool["description"] = after
        _record(
            records,
            MutationType.DESCRIPTION_ENRICHMENT,
            tool,
            "description",
            before,
            after,
            rationale,
        )
        for parameter in tool.get("parameters", []):
            name = str(parameter.get("name", ""))
            description = parameter_descriptions.get(name)
            if description is None:
                continue
            schema = parameter.setdefault("schema", {})
            before_parameter = schema.get("description")
            schema["description"] = description
            _record(
                records,
                MutationType.DESCRIPTION_ENRICHMENT,
                tool,
                f"parameter.{name}.description",
                before_parameter,
                description,
                rationale,
            )
        for name, schema in tool.get("request_schema", {}).get("properties", {}).items():
            description = parameter_descriptions.get(str(name))
            if description is None or not isinstance(schema, dict):
                continue
            before_parameter = schema.get("description")
            schema["description"] = description
            _record(
                records,
                MutationType.DESCRIPTION_ENRICHMENT,
                tool,
                f"request_schema.{name}.description",
                before_parameter,
                description,
                rationale,
            )
    return snapshot, records


def mutate_snapshot(
    canonical_snapshot: list[dict[str, Any]], variant_key: str
) -> tuple[list[dict[str, Any]], list[MutationSpec]]:
    snapshot = _canonicalize(canonical_snapshot)
    records: list[MutationSpec] = []
    if variant_key == "baseline":
        return snapshot, records

    if variant_key == "degraded":
        for index, tool in enumerate(snapshot, start=1):
            old_name = tool["name"]
            tool["name"] = f"lookup_{index:02d}"
            _record(
                records,
                MutationType.TOOL_RENAME,
                tool,
                "name",
                old_name,
                tool["name"],
                "Test whether semantically opaque tool names increase selection failures.",
            )
            old_description = tool.get("description", "")
            tool["description"] = _description(tool, "degraded")
            _record(
                records,
                MutationType.DESCRIPTION_REDUCTION,
                tool,
                "description",
                old_description,
                tool["description"],
                "Remove semantic detail and constraints from the agent-facing description.",
            )
            _record(
                records,
                MutationType.DESCRIPTION_OVERLAP,
                tool,
                "description",
                old_description,
                tool["description"],
                "Make tool descriptions deliberately indistinguishable.",
            )
            _record(
                records,
                MutationType.TOOL_OVERLAP,
                tool,
                "toolset.semantic_boundary",
                old_description,
                tool["description"],
                "Create tool-level semantic overlap to test selection confusion.",
            )
            if any(marker in str(old_description).lower() for marker in NEGATIVE_MARKERS):
                _record(
                    records,
                    MutationType.NEGATIVE_INSTRUCTION_REMOVAL,
                    tool,
                    "description.negative_instructions",
                    old_description,
                    tool["description"],
                    "Remove negative-use guidance in the degraded bundle.",
                )
            parameter_descriptions = {
                str(parameter.get("name")): parameter.get("description")
                for parameter in tool.get("parameters", [])
                if parameter.get("description")
            }
            for parameter in tool.get("parameters", []):
                parameter.pop("description", None)
            for schema in tool.get("request_schema", {}).get("properties", {}).values():
                if isinstance(schema, dict):
                    schema.pop("description", None)
            if parameter_descriptions:
                _record(
                    records,
                    MutationType.PARAMETER_DESCRIPTION_REMOVAL,
                    tool,
                    "parameters.description",
                    parameter_descriptions,
                    {},
                    "Remove parameter semantics while preserving the canonical schema types.",
                )
            for parameter_index, name in enumerate(_parameter_names(tool), start=1):
                replacement = f"value_{parameter_index}"
                _rename_parameter(tool, name, replacement)
                _record(
                    records,
                    MutationType.PARAMETER_RENAME,
                    tool,
                    f"parameter.{name}",
                    name,
                    replacement,
                    "Test the cost of weak parameter semantics.",
                )
            examples = tool["tool_metadata"].get("examples", [])
            if examples:
                tool["tool_metadata"]["examples"] = []
                _record(
                    records,
                    MutationType.EXAMPLE_REMOVAL,
                    tool,
                    "examples",
                    examples,
                    [],
                    "Remove examples as part of the deliberately degraded bundle.",
                )
        return snapshot, records

    if variant_key == "optimized":
        return _manual_v2_snapshot(snapshot, records)

    if variant_key in {"concise", "verbose", "negative", "examples"}:
        style = (
            "concise"
            if variant_key == "concise"
            else "verbose"
            if variant_key == "verbose"
            else "optimized"
        )
        for tool in snapshot:
            old = tool.get("description", "")
            enriched = _description(tool, style)
            if variant_key == "negative":
                enriched += " Never substitute another operation with a similar name."
            tool["description"] = enriched
            _record(
                records,
                MutationType.DESCRIPTION_ENRICHMENT,
                tool,
                "description",
                old,
                enriched,
                "Clarify intended use, semantic boundaries, and destructive-action safety.",
            )
            if variant_key == "examples":
                names = _parameter_names(tool)
                example = {name: f"example_{name}" for name in names}
                before = tool["tool_metadata"].get("examples", [])
                tool["tool_metadata"]["examples"] = [*before, example]
                tool["description"] += f" Example arguments: {example}."
                _record(
                    records,
                    MutationType.EXAMPLE_ADDITION,
                    tool,
                    "examples",
                    before,
                    tool["tool_metadata"]["examples"],
                    "Test whether representative structured examples improve argument formation.",
                )
        return snapshot, records

    if variant_key == "reduced":
        for tool in snapshot:
            tool["tool_metadata"]["task_relevant_filter"] = True
        _record(
            records,
            MutationType.TOOLSET_REDUCTION,
            None,
            "toolset",
            len(snapshot),
            "task-relevant group",
            "Test routed tool exposure as a separately labeled experimental condition.",
        )
        return snapshot, records

    isolated_kind = {
        "isolated_tool_rename": MutationType.TOOL_RENAME,
        "isolated_description_reduction": MutationType.DESCRIPTION_REDUCTION,
        "isolated_parameter_rename": MutationType.PARAMETER_RENAME,
        "isolated_negative_removal": MutationType.NEGATIVE_INSTRUCTION_REMOVAL,
    }.get(variant_key)
    if isolated_kind:
        target = next(
            (
                tool
                for tool in snapshot
                if (
                    isolated_kind != MutationType.NEGATIVE_INSTRUCTION_REMOVAL
                    or tool["is_destructive"]
                )
                and (isolated_kind != MutationType.PARAMETER_RENAME or _parameter_names(tool))
            ),
            snapshot[0],
        )
        if isolated_kind == MutationType.TOOL_RENAME:
            before, after = target["name"], "lookup"
            target["name"] = after
            field = "name"
        elif isolated_kind == MutationType.PARAMETER_RENAME:
            before = _parameter_names(target)[0]
            after = "value"
            _rename_parameter(target, before, after)
            field = f"parameter.{before}"
        else:
            before = target.get("description", "")
            after = (
                "Gets information."
                if isolated_kind == MutationType.DESCRIPTION_REDUCTION
                else re.sub(r"(?i)(do not|never|must not)[^.]*\.?", "", before).strip()
            )
            target["description"] = after
            field = "description"
        _record(
            records,
            isolated_kind,
            target,
            field,
            before,
            after,
            "Isolate one interface characteristic for mutation attribution.",
        )
        return snapshot, records

    match = re.fullmatch(r"toolset_(10|25|50)", variant_key)
    if match:
        target_count = int(match.group(1))
        before_count = len(snapshot)
        for index in range(before_count + 1, target_count + 1):
            operation = f"experiment_read_context_{index:02d}"
            snapshot.append(
                {
                    "name": operation,
                    "operation_id": operation,
                    "http_method": "GET",
                    "path": f"/__experiment/context/{index}",
                    "description": "Read-only experimental context lookup. Never changes sandbox state.",
                    "parameters": [],
                    "request_schema": {},
                    "response_schema": {"type": "object"},
                    "tags": ["Experimental distractor"],
                    "is_destructive": False,
                    "inferred_destructive": False,
                    "requires_authentication": False,
                    "tool_metadata": {
                        "canonical_operation_id": operation,
                        "parameter_aliases": {},
                        "experimental": True,
                        "experimental_distractor": True,
                    },
                }
            )
        _record(
            records,
            MutationType.TOOLSET_EXPANSION,
            None,
            "toolset.count",
            before_count,
            len(snapshot),
            "Measure distraction from safe, sandbox-backed, read-only experimental operations.",
        )
        return snapshot, records

    raise ValueError(f"Unknown Phase 1.5 interface variant: {variant_key}")


VARIANT_NAMES = {
    "baseline": "V0 — Canonical baseline",
    "degraded": "V1 — Deliberately degraded",
    "optimized": "V2 — Manually optimized general",
    "concise": "V3 — Concise explicit semantics",
    "verbose": "V4 — Verbose guidance",
    "negative": "V5 — Strong negative instructions",
    "examples": "V6 — Example-heavy",
    "reduced": "V7 — Reduced task-routed exposure",
    "isolated_tool_rename": "D1 — Isolated tool rename",
    "isolated_description_reduction": "D2 — Isolated description reduction",
    "isolated_parameter_rename": "D3 — Isolated parameter rename",
    "isolated_negative_removal": "D4 — Isolated negative-instruction removal",
    "toolset_10": "T10 — 10-tool exposure",
    "toolset_25": "T25 — 25-tool exposure",
    "toolset_50": "T50 — 50-tool exposure",
}


def create_interface_variant(
    session: Session,
    project: Project,
    parent: InterfaceVersion,
    variant_key: str,
    experiment_id: str | None = None,
    generated_by: MutationGeneratedBy = MutationGeneratedBy.SYSTEMATIC_EXPERIMENT,
) -> InterfaceVersion:
    existing = session.scalar(
        select(InterfaceVersion).where(
            InterfaceVersion.project_id == project.id,
            InterfaceVersion.variant_key == variant_key,
        )
    )
    if existing:
        return existing
    snapshot, mutations = mutate_snapshot(parent.tool_definitions_snapshot, variant_key)
    latest = session.scalar(
        select(InterfaceVersion.version)
        .where(InterfaceVersion.project_id == project.id)
        .order_by(InterfaceVersion.version.desc())
    )
    interface = InterfaceVersion(
        project_id=project.id,
        version=(latest or 0) + 1,
        parent_version_id=parent.id,
        tool_definitions_snapshot=snapshot,
        change_description=f"Phase 1.5 controlled variant: {variant_key}",
        name=VARIANT_NAMES[variant_key],
        variant_key=variant_key,
        frozen=True,
    )
    session.add(interface)
    session.flush()
    session.add_all(
        [
            InterfaceMutation(
                interface_version_id=interface.id,
                parent_interface_version_id=parent.id,
                mutation_type=mutation.mutation_type.value,
                target_tool_id=mutation.target_tool,
                target_field=mutation.target_field,
                before_value=mutation.before_value,
                after_value=mutation.after_value,
                rationale=mutation.rationale,
                generated_by=generated_by.value,
                experiment_id=experiment_id,
            )
            for mutation in mutations
        ]
    )
    session.flush()
    return interface


def create_phase15_variants(
    session: Session,
    project: Project,
    variant_keys: Iterable[str],
    experiment_id: str | None = None,
) -> list[InterfaceVersion]:
    parent = session.scalar(
        select(InterfaceVersion)
        .where(
            InterfaceVersion.project_id == project.id,
            InterfaceVersion.variant_key == "baseline",
        )
        .order_by(InterfaceVersion.version.asc())
    )
    if not parent:
        raise ValueError("Project has no canonical interface version")
    parent.tool_definitions_snapshot = _canonicalize(parent.tool_definitions_snapshot)
    parent.name = VARIANT_NAMES["baseline"]
    parent.frozen = True
    versions = [
        parent
        if key == "baseline"
        else create_interface_variant(session, project, parent, key, experiment_id)
        for key in variant_keys
    ]
    session.commit()
    return versions


def tools_from_interface(interface: InterfaceVersion) -> list[NormalizedTool]:
    return [NormalizedTool(**tool) for tool in interface.tool_definitions_snapshot]


def tools_for_task(
    interface: InterfaceVersion, required_tools: list[str], forbidden_tools: list[str]
) -> list[NormalizedTool]:
    tools = tools_from_interface(interface)
    if interface.variant_key != "reduced":
        return tools
    relevant = set(required_tools) | set(forbidden_tools)
    selected = [
        tool
        for tool in tools
        if tool.tool_metadata.get("canonical_operation_id", tool.operation_id) in relevant
    ]
    return selected or tools


def translate_tool_call(
    interface: InterfaceVersion, agent_tool: str, arguments: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    for tool in interface.tool_definitions_snapshot:
        if tool["name"] != agent_tool:
            continue
        metadata = tool.get("tool_metadata", {})
        canonical = str(
            metadata.get("canonical_operation_id", tool.get("operation_id", agent_tool))
        )
        aliases = metadata.get("parameter_aliases", {})
        translated = {str(aliases.get(key, key)): value for key, value in arguments.items()}
        return canonical, translated
    return agent_tool, arguments
