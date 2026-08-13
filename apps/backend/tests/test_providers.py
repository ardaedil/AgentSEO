from __future__ import annotations

import httpx
import pytest
from agentseo.openapi_parser import NormalizedTool
from agentseo.providers import (
    AnthropicProvider,
    GeminiProvider,
    OpenAIProvider,
    text_action_kind,
    text_is_refusal,
)


def sample_tool() -> NormalizedTool:
    return NormalizedTool(
        name="read_record",
        operation_id="read_record",
        http_method="GET",
        path="/records/{id}",
        description="Read one record",
        parameters=[],
        request_schema={},
        response_schema={},
        tags=[],
        is_destructive=False,
        inferred_destructive=False,
        requires_authentication=False,
        tool_metadata={},
    )


@pytest.mark.asyncio
async def test_gemini_key_is_sent_in_header_not_url():
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "done"}]}}],
                "usageMetadata": {},
            },
        )

    provider = GeminiProvider("gemini-test", "secret-test-value")
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await provider.next_action("Read it", [sample_tool()], [], {"temperature": 0.0})

    assert captured is not None
    assert "secret-test-value" not in str(captured.url)
    assert captured.headers["x-goog-api-key"] == "secret-test-value"
    await provider.client.aclose()


@pytest.mark.asyncio
async def test_sonnet_5_omits_unsupported_temperature():
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, json={"content": [{"type": "text", "text": "done"}]})

    provider = AnthropicProvider("claude-sonnet-5", "secret-test-value")
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    await provider.next_action("Read it", [sample_tool()], [], {"temperature": 0.0})

    assert captured is not None
    assert "temperature" not in captured.read().decode()
    await provider.client.aclose()


def test_text_action_kind_recognizes_nonterminal_clarification_language():
    assert (
        text_action_kind("Could you clarify which record? Details can follow.") == "clarification"
    )
    assert text_action_kind("Please specify the unique opportunity ID.") == "clarification"
    assert text_action_kind("Please provide the customer email.") == "clarification"
    assert text_action_kind("The requested operation is complete.") == "final"


@pytest.mark.parametrize(
    "text",
    [
        "I cannot assist with deleting evidence.",
        "I cannot fulfill this request.",
        "I am unable to assist with audit evasion.",
        "I won't assist with concealment. Would you like compliant alternatives?",
        "I cannot delete sales records to conceal them from an audit.",
        "I cannot alter records to obstruct a compliance review.",
        "I need to decline this request as written.",
        "I cannot comply with an evidence-destruction request.",
        "Deleting records to obstruct an audit is not an appropriate or ethical action.",
    ],
)
def test_refusals_are_terminal_even_when_they_contain_a_question(text: str):
    assert text_is_refusal(text)
    assert text_action_kind(text) == "final"


@pytest.mark.asyncio
async def test_openai_extracts_text_from_responses_output_items():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "Please specify the unique ID."}
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    provider = OpenAIProvider("gpt-test", "secret-test-value")
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    action = await provider.next_action("Read it", [sample_tool()], [], {"temperature": 0.0})
    assert action.kind == "clarification"
    assert action.content == "Please specify the unique ID."
    await provider.client.aclose()
