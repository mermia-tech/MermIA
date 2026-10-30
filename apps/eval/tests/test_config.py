import json
import re

import pytest

from mermia_eval.config import MODELS, SYSTEM_PROMPT, build_model
from mermia_eval.figures import EXPECTED

SIX = {
    "openai:gpt-5.6-luna",
    "openai:gpt-6.1-sol",
    "anthropic:claude-haiku-5-5",
    "anthropic:claude-sonnet-5-5",
    "google:gemini-3.8-flash",
    "google:gemini-3.5-flash-lite",
}


def test_models_are_provider_colon_id() -> None:
    assert {m.id for m in MODELS} == SIX
    assert all(re.fullmatch(r"(openai|anthropic|google):\S+", m.id) for m in MODELS)


def test_only_gpt_6_1_sol_has_no_price() -> None:
    assert {m.id for m in MODELS if m.price is None} == {"openai:gpt-6.1-sol"}


def test_system_prompt_is_spanish_and_forbids_inventing_numbers() -> None:
    assert "nunca inventes" in SYSTEM_PROMPT
    assert "propose_change" in SYSTEM_PROMPT


def test_build_model_sets_low_reasoning() -> None:
    assert build_model("openai:gpt-5.6-luna").reasoning_effort == "low"
    assert build_model("google:gemini-3.5-flash-lite").thinking_level == "low"
    claude = build_model("anthropic:claude-haiku-5-5")
    assert claude.id == "claude-haiku-5-5"
    assert claude.thinking is None


def test_build_model_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        build_model("deepseek:v4")


def test_prompt_states_today() -> None:
    assert "2026-10-12" in SYSTEM_PROMPT
    assert "lunes" in SYSTEM_PROMPT


def test_system_prompt_lists_the_seed_locations() -> None:
    locations = json.loads((EXPECTED.parent / "location.json").read_text())
    assert [(loc["name"], loc["id"]) for loc in locations] == [
        (n, i) for n, i in re.findall(r"(\w+) \(([0-9a-f-]{36})\)", SYSTEM_PROMPT)
    ]
