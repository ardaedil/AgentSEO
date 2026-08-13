"""Source adapters that normalize agent-facing protocols into shared tool definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .openapi_parser import NormalizedTool, parse_openapi


class InterfaceSource(Protocol):
    source_type: str

    def normalize(self) -> tuple[dict[str, Any], list[NormalizedTool]]: ...


@dataclass(frozen=True, slots=True)
class OpenAPIInterface:
    content: bytes
    source_type: str = "openapi"

    def normalize(self) -> tuple[dict[str, Any], list[NormalizedTool]]:
        return parse_openapi(self.content)


@dataclass(frozen=True, slots=True)
class MCPInterface:
    """Reserved Phase 2E adapter boundary for MCP tool-list snapshots."""

    tool_list: list[dict[str, Any]]
    server_metadata: dict[str, Any]
    source_type: str = "mcp"

    def normalize(self) -> tuple[dict[str, Any], list[NormalizedTool]]:
        raise NotImplementedError(
            "Phase 2E must define MCP schema/auth/resources normalization before execution"
        )
