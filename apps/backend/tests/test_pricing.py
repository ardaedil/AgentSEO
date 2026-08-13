from agentseo.pricing import estimate_usage_cost, pricing_manifest


def test_approved_phase15_model_prices_are_frozen():
    assert estimate_usage_cost("openai:gpt-4.1-mini", 1_000_000, 1_000_000) == 2.0
    assert estimate_usage_cost("anthropic:claude-sonnet-5", 1_000_000, 1_000_000) == 12.0
    assert estimate_usage_cost("google:gemini-3.6-flash", 1_000_000, 1_000_000) == 9.0
    manifest = pricing_manifest(
        [
            "openai:gpt-4.1-mini",
            "anthropic:claude-sonnet-5",
            "google:gemini-3.6-flash",
        ]
    )
    models = manifest["models"]
    assert isinstance(models, dict)
    assert set(models) == {
        "openai:gpt-4.1-mini",
        "anthropic:claude-sonnet-5",
        "google:gemini-3.6-flash",
    }
