from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .openapi_parser import NormalizedTool


@dataclass(slots=True)
class AgentAction:
    kind: str
    content: str = ""
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    token_usage: dict[str, int] | None = None


class AgentProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def next_action(
        self,
        instruction: str,
        tools: list[NormalizedTool],
        history: list[dict[str, Any]],
        task_context: dict[str, Any],
    ) -> AgentAction: ...


def tool_input_schema(tool: NormalizedTool) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in tool.parameters:
        name = parameter.get("name")
        if name:
            properties[name] = parameter.get("schema", {"type": "string"})
            if parameter.get("required"):
                required.append(name)
    body = tool.request_schema
    if body.get("type") == "object":
        properties.update(body.get("properties", {}))
        required.extend(body.get("required", []))
    return {"type": "object", "properties": properties, "required": sorted(set(required))}


class MockAgent(AgentProvider):
    name = "mock"

    def __init__(self, model: str = "reliable") -> None:
        self.model = model

    def _arguments(self, tool: str, instruction: str, invalid: bool = False) -> dict[str, Any]:
        lower = tool.lower()
        text = instruction.lower()
        missing = "missing_record"
        if "search_customer" in lower or "find_customer" in lower or "lookup_customer" in lower:
            if "john" in text:
                return {"query": "john@example.com", "email": "john@example.com"}
            if "jane" in text:
                return {"query": "Jane Doe", "name": "Jane Doe"}
            return {"query": "alice@example.com"}
        if "subscription" in lower and lower.startswith(("list", "search", "find")):
            return {"customer_id": "cus_john"}
        if lower == "cancel_subscription":
            return {
                "subscription_id": missing if invalid else "sub_john",
                "at_period_end": True,
            }
        if "invoice" in lower and lower.startswith(("list", "search", "find")):
            return {"customer_id": "cus_john", "status": "open"}
        if "compan" in lower:
            if lower.startswith("get"):
                return {"id": missing if invalid else "co_acme"}
            return {"query": "Acme Inc."}
        if "opportunit" in lower and lower.startswith(("list", "search", "find")):
            return {"company_id": "co_acme", "status": "open", "min_value": 20000}
        if "owner" in lower:
            return {"query": "Sarah"}
        if lower == "assign_opportunity":
            return {
                "opportunity_id": missing if invalid else "opp_1",
                "owner_id": "own_sarah",
            }
        if "order" in lower and lower.startswith(("list", "search", "find")):
            return {"customer_id": "cus_jane"}
        if "shipment" in lower:
            return {"status": "failed"}
        if lower == "refund_order":
            return {"order_id": missing if invalid else "ord_1"}
        if lower == "refund_invoice":
            return {"id": missing if invalid else "inv_alice"}
        if lower == "terminate_account":
            return {"id": missing if invalid else "cus_alice"}
        if lower == "get_customer":
            return {"id": missing if invalid else ("cus_jane" if "jane" in text else "cus_john")}
        if lower == "delete_customer":
            return {"id": missing if invalid else ("cus_jane" if "jane" in text else "cus_alice")}
        if lower == "get_order":
            return {"id": missing if invalid else "ord_1"}
        if lower == "delete_opportunity":
            return {"id": missing if invalid else "opp_2"}
        if lower == "list_contacts":
            return {"company_id": "co_acme"}
        return {"id": missing if invalid else "example-id"}

    async def next_action(
        self,
        instruction: str,
        tools: list[NormalizedTool],
        history: list[dict[str, Any]],
        task_context: dict[str, Any],
    ) -> AgentAction:
        if task_context.get("requires_clarification"):
            return AgentAction(
                "clarification",
                "Which specific record should I use?",
                token_usage={"input": 24, "output": 8},
            )
        required = task_context.get("required_tools", [])
        canonical_to_agent = {
            tool.tool_metadata.get("canonical_operation_id", tool.operation_id): tool.name
            for tool in tools
        }
        called = [
            event.get("canonical_tool", event.get("tool"))
            for event in history
            if event.get("type") == "tool_result"
        ]
        successful = [
            event.get("canonical_tool", event.get("tool"))
            for event in history
            if event.get("type") == "tool_result" and not event.get("error_code")
        ]
        remaining = [name for name in required if name not in successful]
        if remaining:
            canonical_selected = remaining[0]
            # The fallible mock variant deterministically chooses a confusing destructive tool.
            if self.model == "fallible" and not called and task_context.get("forbidden_tools"):
                canonical_selected = task_context["forbidden_tools"][0]
            selected = canonical_to_agent.get(canonical_selected, canonical_selected)
            return AgentAction(
                "tool_call",
                tool=selected,
                arguments=self._arguments(
                    canonical_selected,
                    instruction,
                    invalid=bool(task_context.get("category") == "error_recovery" and not called),
                ),
                token_usage={"input": 45, "output": 14},
            )
        return AgentAction(
            "final", "The requested operation is complete.", token_usage={"input": 18, "output": 9}
        )


class HTTPProvider(AgentProvider):
    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=60)


class OpenAIProvider(HTTPProvider):
    name = "openai"

    async def next_action(
        self,
        instruction: str,
        tools: list[NormalizedTool],
        history: list[dict[str, Any]],
        task_context: dict[str, Any],
    ) -> AgentAction:
        input_items: list[dict[str, Any]] = [{"role": "user", "content": instruction}]
        for item in history:
            input_items.append({"role": "user", "content": json.dumps(item)})
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_items,
            "tools": [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool_input_schema(tool),
                }
                for tool in tools
            ],
        }
        if task_context.get("temperature") is not None:
            payload["temperature"] = task_context["temperature"]
        response = await self.client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage", {})
        for output in data.get("output", []):
            if output.get("type") == "function_call":
                return AgentAction(
                    "tool_call",
                    tool=output["name"],
                    arguments=json.loads(output.get("arguments", "{}")),
                    token_usage={
                        "input": usage.get("input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                    },
                )
        text = data.get("output_text", "")
        kind = "clarification" if text.rstrip().endswith("?") else "final"
        return AgentAction(
            kind,
            text,
            token_usage={
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
            },
        )


class AnthropicProvider(HTTPProvider):
    name = "anthropic"

    async def next_action(
        self,
        instruction: str,
        tools: list[NormalizedTool],
        history: list[dict[str, Any]],
        task_context: dict[str, Any],
    ) -> AgentAction:
        messages = [
            {"role": "user", "content": instruction + "\n\nTool history:\n" + json.dumps(history)}
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": messages,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool_input_schema(tool),
                }
                for tool in tools
            ],
        }
        if self.model != "claude-sonnet-5" and task_context.get("temperature") is not None:
            payload["temperature"] = task_context["temperature"]
        response = await self.client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage", {})
        for block in data.get("content", []):
            if block.get("type") == "tool_use":
                return AgentAction(
                    "tool_call",
                    tool=block["name"],
                    arguments=block.get("input", {}),
                    token_usage={
                        "input": usage.get("input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                    },
                )
        text = " ".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        return AgentAction(
            "clarification" if text.rstrip().endswith("?") else "final",
            text,
            token_usage={
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
            },
        )


class GeminiProvider(HTTPProvider):
    name = "google"

    async def next_action(
        self,
        instruction: str,
        tools: list[NormalizedTool],
        history: list[dict[str, Any]],
        task_context: dict[str, Any],
    ) -> AgentAction:
        response = await self.client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key},
            json={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": instruction + "\nTool history:\n" + json.dumps(history)}
                        ],
                    }
                ],
                "tools": [
                    {
                        "functionDeclarations": [
                            {
                                "name": tool.name,
                                "description": tool.description,
                                "parameters": tool_input_schema(tool),
                            }
                            for tool in tools
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": task_context.get("temperature", 0.0),
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        metadata = data.get("usageMetadata", {})
        usage = {
            "input": metadata.get("promptTokenCount", 0),
            "output": metadata.get("candidatesTokenCount", 0),
        }
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        for part in parts:
            if "functionCall" in part:
                call = part["functionCall"]
                return AgentAction(
                    "tool_call",
                    tool=call["name"],
                    arguments=call.get("args", {}),
                    token_usage=usage,
                )
        text = " ".join(part.get("text", "") for part in parts)
        return AgentAction(
            "clarification" if text.rstrip().endswith("?") else "final", text, token_usage=usage
        )


def create_provider(identifier: str, settings: Settings) -> AgentProvider:
    provider, _, model = identifier.partition(":")
    if provider == "mock":
        return MockAgent(model or "reliable")
    if provider == "openai" and settings.openai_api_key:
        return OpenAIProvider(model or settings.openai_model, settings.openai_api_key)
    if provider == "anthropic" and settings.anthropic_api_key:
        return AnthropicProvider(model or settings.anthropic_model, settings.anthropic_api_key)
    if provider in {"google", "gemini"} and settings.google_api_key:
        return GeminiProvider(model or settings.gemini_model, settings.google_api_key)
    raise ValueError(
        f"Provider {provider!r} is not configured; use mock:reliable for offline demo mode"
    )
