"""Model-token pricing used for reproducible experiment cost estimates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenPrice:
    input_per_million: float
    output_per_million: float
    basis: str


MODEL_PRICES = {
    "openai:gpt-4.1-mini": TokenPrice(
        0.40,
        1.60,
        "OpenAI standard API pricing checked 2026-08-13",
    ),
    "anthropic:claude-sonnet-5": TokenPrice(
        2.00,
        10.00,
        "Anthropic introductory API pricing through 2026-08-31, checked 2026-08-13",
    ),
    "google:gemini-3.6-flash": TokenPrice(
        1.50,
        7.50,
        "Google Gemini API standard pricing checked 2026-08-13",
    ),
}


def estimate_usage_cost(model_identifier: str, input_tokens: int, output_tokens: int) -> float:
    price = MODEL_PRICES.get(model_identifier)
    if price is None:
        # Preserve the historical fallback for models without a frozen price record.
        return input_tokens * 0.0000005 + output_tokens * 0.0000015
    return (
        input_tokens * price.input_per_million + output_tokens * price.output_per_million
    ) / 1_000_000


def pricing_manifest(models: list[str]) -> dict[str, object]:
    return {
        "checked_at": "2026-08-13",
        "currency": "USD",
        "unit": "per_million_tokens",
        "models": {
            model: {
                "input": MODEL_PRICES[model].input_per_million,
                "output": MODEL_PRICES[model].output_per_million,
                "basis": MODEL_PRICES[model].basis,
            }
            for model in models
            if model in MODEL_PRICES
        },
    }
