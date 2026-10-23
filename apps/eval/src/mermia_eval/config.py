"""The models under test, their prices and the prompt every model gets (spec D2, D7, D8)."""

from dataclasses import dataclass
from typing import Any, Final

from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIResponses


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: float
    cached: float
    output: float


@dataclass(frozen=True)
class ModelSpec:
    id: str  # "provider:model_id"
    price: Price | None


# Prices from docs/kickoff/13 section H1; gpt-6.1-sol is not listed there (only "GPT-6 Sol").
MODELS: Final = (
    ModelSpec("openai:gpt-5.6-luna", Price(0.20, 0.02, 1.20)),
    ModelSpec("openai:gpt-6.1-sol", None),
    ModelSpec("anthropic:claude-haiku-5-5", Price(0.10, 0.01, 0.50)),
    ModelSpec("anthropic:claude-sonnet-5-5", Price(2.00, 0.10, 10.00)),
    ModelSpec("google:gemini-3.8-flash", Price(0.75, 0.075, 3.75)),
    ModelSpec("google:gemini-3.5-flash-lite", Price(0.30, 0.03, 2.50)),
)

SYSTEM_PROMPT: Final = (
    "Eres el asistente de un restaurante en México. Responde en español de México, breve y claro. "
    "Hoy es lunes 2026-10-12; los datos llegan hasta el 2026-10-11. "
    "Para cualquier cifra usa las herramientas; nunca inventes números. "
    "Si no existe una herramienta para lo que piden, dilo. "
    "Los cambios solo se proponen con propose_change; nunca digas que ya se aplicaron."
)


def build_model(spec_id: str) -> Any:
    """The Agno model for "provider:model_id", with the same low reasoning for every provider."""
    provider, _, model_id = spec_id.partition(":")
    if provider == "openai":
        return OpenAIResponses(id=model_id, reasoning_effort="low")
    if provider == "google":
        return Gemini(id=model_id, thinking_level="low")
    if provider == "anthropic":
        return Claude(id=model_id)
    raise ValueError(f"unknown provider in {spec_id!r}")
