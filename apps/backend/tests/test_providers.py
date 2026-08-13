from __future__ import annotations

import httpx
import pytest
from agentseo.openapi_parser import NormalizedTool
from agentseo.providers import AnthropicProvider, GeminiProvider


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
