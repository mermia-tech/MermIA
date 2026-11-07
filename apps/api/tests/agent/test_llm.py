"""Provider adapter: output cap per provider, DeepSeek usage, the cost rules, tracing switch."""

import base64
from decimal import Decimal

import pytest
from openai.types.completion_usage import CompletionUsage

from mermia_api.agent import llm
from mermia_api.agent.llm import PRICES, TIMEOUT, Price, build_model, cost_usd

PRICE = Price(Decimal("0.20"), Decimal("0.02"), Decimal("1.20"))


def test_build_model_caps_output_per_provider() -> None:
    assert build_model("openai:gpt-5.6-luna", max_output_tokens=400).max_output_tokens == 400
    assert (
        build_model("google:gemini-3.5-flash-lite", max_output_tokens=400).max_output_tokens == 400
    )
    assert build_model("anthropic:claude-haiku-5-5", max_output_tokens=400).max_tokens == 400
    assert build_model("deepseek:deepseek-flash", max_output_tokens=400).max_tokens == 400


def test_build_model_leaves_output_uncapped_by_default() -> None:
    # The eval and its judge measure models as MR-20 did; only the broker caps output.
    assert build_model("openai:gpt-5.6-luna").max_output_tokens is None


def test_build_model_keeps_low_reasoning_and_the_timeout() -> None:
    assert build_model("openai:gpt-5.6-luna").reasoning_effort == "low"
    assert build_model("google:gemini-3.5-flash-lite").thinking_level == "low"
    for spec in ("openai:a", "google:b", "anthropic:c", "deepseek:d"):
        assert build_model(spec).timeout == TIMEOUT


def test_build_model_turns_deepseek_thinking_off() -> None:
    assert build_model("deepseek:deepseek-flash").use_thinking is False


def test_build_model_rejects_an_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        build_model("mistral:large")


def test_deepseek_cache_hits_become_cache_read_tokens() -> None:
    # DeepSeek reports cache hits as prompt_cache_hit_tokens, which Agno does not read.
    usage = CompletionUsage.model_validate(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "total_tokens": 1050,
            "prompt_cache_hit_tokens": 800,
            "prompt_cache_miss_tokens": 200,
        }
    )
    metrics = build_model("deepseek:deepseek-flash")._get_metrics(usage)
    assert (metrics.input_tokens, metrics.cache_read_tokens) == (1000, 800)


def test_deepseek_standard_cached_field_still_wins_when_present() -> None:
    usage = CompletionUsage.model_validate(
        {
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "total_tokens": 1050,
            "prompt_tokens_details": {"cached_tokens": 600},
        }
    )
    assert build_model("deepseek:deepseek-flash")._get_metrics(usage).cache_read_tokens == 600


def test_cost_is_decimal_and_splits_cached_for_openai_style_providers() -> None:
    # input includes the cached tokens: 600k at 0.20 + 400k at 0.02 + 1M output at 1.20
    for model in ("openai:gpt-5.6-luna", "deepseek:deepseek-flash"):
        cost = cost_usd(
            model, PRICE, input=1_000_000, cached=400_000, output=1_000_000, reasoning=0
        )
        assert cost == Decimal("1.328")


def test_cost_adds_cached_for_anthropic() -> None:
    price = Price(Decimal("0.10"), Decimal("0.01"), Decimal("0.50"))
    cost = cost_usd(
        "anthropic:claude-haiku-5-5",
        price,
        input=1_000_000,
        cached=400_000,
        output=1_000_000,
        reasoning=0,
    )
    assert cost == Decimal("0.604")


def test_cost_adds_thinking_tokens_for_google_only() -> None:
    google = cost_usd("google:x", PRICE, input=0, cached=0, output=1_000_000, reasoning=500_000)
    openai = cost_usd("openai:x", PRICE, input=0, cached=0, output=1_000_000, reasoning=500_000)
    assert (google, openai) == (Decimal("1.80"), Decimal("1.20"))


def test_cost_is_none_without_a_price() -> None:
    assert cost_usd("openai:x", None, input=1, cached=0, output=1, reasoning=0) is None


def test_prices_are_decimal() -> None:
    assert PRICES and all(
        isinstance(v, Decimal) for p in PRICES.values() for v in (p.input, p.cached, p.output)
    )


def test_tracing_is_off_without_the_langfuse_variables() -> None:
    assert llm.setup_tracing({}) is None
    assert llm.setup_tracing({"LANGFUSE_PUBLIC_KEY": "pk"}) is None


def test_tracing_endpoint_and_auth_header() -> None:
    assert llm.otlp_endpoint("https://x.example/") == "https://x.example/api/public/otel/v1/traces"
    assert llm.auth_header("pk", "sk") == "Basic " + base64.b64encode(b"pk:sk").decode()


def test_deepseek_models_are_priced_at_peak() -> None:
    # Peak rates (the higher of DeepSeek's two time bands), so metered cost never undercounts.
    assert PRICES["deepseek:deepseek-flash"] == Price(
        Decimal("0.3"), Decimal("0.006"), Decimal("1.2")
    )
    assert PRICES["deepseek:deepseek-v4-pro"] == Price(
        Decimal("1.32"), Decimal("0.044"), Decimal("3.96")
    )
