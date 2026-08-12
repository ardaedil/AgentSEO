from pathlib import Path

import pytest
from agentseo.openapi_parser import OpenAPIError, parse_openapi

ROOT = Path(__file__).parents[3]


def test_parses_yaml_and_normalizes_operations():
    document, tools = parse_openapi((ROOT / "examples/billing/openapi.yaml").read_bytes())
    assert document["openapi"] == "3.0.3"
    by_name = {tool.name: tool for tool in tools}
    assert len(tools) >= 9
    assert by_name["cancel_subscription"].request_schema["required"] == ["at_period_end"]
    assert by_name["get_customer"].parameters[0]["name"] == "id"
    assert by_name["delete_customer"].is_destructive is True
    assert by_name["list_invoices"].is_destructive is False


def test_parser_accepts_json_and_synthesizes_operation_id():
    content = '{"openapi":"3.1.0","info":{"title":"x","version":"1"},"paths":{"/things/{id}":{"get":{"responses":{"200":{"description":"ok"}}}}}}'
    _, tools = parse_openapi(content)
    assert tools[0].name == "get_things_id"


@pytest.mark.parametrize("content", ["openapi: 2.0\npaths: {}", "[]", "not: [valid"])
def test_rejects_unsupported_or_malformed_documents(content: str):
    with pytest.raises(OpenAPIError):
        parse_openapi(content)
