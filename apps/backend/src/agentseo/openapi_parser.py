from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

import yaml

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
DESTRUCTIVE_TERMS = {
    "cancel",
    "charge",
    "delete",
    "modify",
    "refund",
    "remove",
    "terminate",
    "transfer",
    "update",
}


class OpenAPIError(ValueError):
    pass


@dataclass(slots=True)
class NormalizedTool:
    name: str
    operation_id: str
    http_method: str
    path: str
    description: str
    parameters: list[dict[str, Any]]
    request_schema: dict[str, Any]
    response_schema: dict[str, Any]
    tags: list[str]
    is_destructive: bool
    inferred_destructive: bool
    requires_authentication: bool
    tool_metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_document(content: bytes | str) -> dict[str, Any]:
    text = content.decode("utf-8") if isinstance(content, bytes) else content
    try:
        document = (
            json.loads(text) if text.lstrip().startswith(("{", "[")) else yaml.safe_load(text)
        )
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise OpenAPIError(f"Invalid JSON or YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise OpenAPIError("The specification root must be an object")
    version = str(document.get("openapi", ""))
    if not version.startswith("3."):
        raise OpenAPIError("Only OpenAPI 3.x specifications are supported")
    if not isinstance(document.get("paths"), dict):
        raise OpenAPIError("The specification must contain a paths object")
    return document


def _resolve_ref(value: Any, document: dict[str, Any]) -> Any:
    if not isinstance(value, dict) or "$ref" not in value:
        return deepcopy(value)
    ref = value["$ref"]
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise OpenAPIError("Only local OpenAPI references are supported")
    resolved: Any = document
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(resolved, dict) or part not in resolved:
            raise OpenAPIError(f"Unresolved reference: {ref}")
        resolved = resolved[part]
    return deepcopy(resolved)


def _operation_id(method: str, path: str, operation: dict[str, Any]) -> str:
    if operation.get("operationId"):
        return str(operation["operationId"])
    clean_path = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_")
    return f"{method}_{clean_path}".lower()


def _destructive(method: str, path: str, operation_id: str, description: str) -> bool:
    if method == "delete":
        return True
    text = f"{path} {operation_id} {description}".lower()
    term_hit = any(re.search(rf"\b{re.escape(term)}\w*\b", text) for term in DESTRUCTIVE_TERMS)
    # Read-only HTTP semantics override incidental terms such as "get cancelled invoices".
    return method in {"post", "put", "patch"} and term_hit


def _response_schema(operation: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    responses = operation.get("responses", {})
    for code in ("200", "201", "202", "204", "default"):
        response = responses.get(code)
        if not response:
            continue
        response = _resolve_ref(response, document)
        content = response.get("content", {})
        for media in ("application/json", "application/problem+json"):
            if media in content:
                schema = _resolve_ref(content[media].get("schema", {}), document)
                return schema if isinstance(schema, dict) else {}
    return {}


def normalize_tools(document: dict[str, Any]) -> list[NormalizedTool]:
    tools: list[NormalizedTool] = []
    global_security = document.get("security", [])
    for path, path_item in document["paths"].items():
        if not isinstance(path_item, dict):
            continue
        shared_parameters = path_item.get("parameters", [])
        for method, raw_operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(raw_operation, dict):
                continue
            operation = _resolve_ref(raw_operation, document)
            operation_id = _operation_id(method.lower(), path, operation)
            description = operation.get("description") or operation.get("summary") or ""
            parameters = [
                _resolve_ref(item, document)
                for item in [*shared_parameters, *operation.get("parameters", [])]
            ]
            request_schema: dict[str, Any] = {}
            request_body = operation.get("requestBody")
            if request_body:
                body = _resolve_ref(request_body, document)
                request_schema = _resolve_ref(
                    body.get("content", {}).get("application/json", {}).get("schema", {}), document
                )
            inferred = _destructive(method.lower(), path, operation_id, description)
            security = operation.get("security", global_security)
            tools.append(
                NormalizedTool(
                    name=operation_id,
                    operation_id=operation_id,
                    http_method=method.upper(),
                    path=path,
                    description=str(description),
                    parameters=parameters,
                    request_schema=request_schema,
                    response_schema=_response_schema(operation, document),
                    tags=[str(tag) for tag in operation.get("tags", [])],
                    is_destructive=inferred,
                    inferred_destructive=inferred,
                    requires_authentication=bool(security),
                    tool_metadata={
                        "source": "openapi",
                        "summary": operation.get("summary", ""),
                        "deprecated": bool(operation.get("deprecated", False)),
                        "examples": [
                            p["example"]
                            for p in parameters
                            if isinstance(p, dict) and "example" in p
                        ],
                    },
                )
            )
    if not tools:
        raise OpenAPIError("No API operations were discovered")
    return tools


def parse_openapi(content: bytes | str) -> tuple[dict[str, Any], list[NormalizedTool]]:
    document = parse_document(content)
    return document, normalize_tools(document)
