"""The models under test, their prices and the prompt every model gets (spec D2, D7, D8)."""

from dataclasses import dataclass
from typing import Final

from mermia_api.agent.llm import PRICES, TIMEOUT, Price, build_model

__all__ = ["MODELS", "PAUSED", "SYSTEM_PROMPT", "TIMEOUT", "ModelSpec", "Price", "build_model"]


@dataclass(frozen=True)
class ModelSpec:
    id: str  # "provider:model_id"
    price: Price | None


# Prices: mermia_api.agent.llm.PRICES (docs/kickoff/13 section H1); gpt-6.1-sol has none.
MODELS: Final = (
    ModelSpec("openai:gpt-5.6-luna", PRICES["openai:gpt-5.6-luna"]),
    ModelSpec("anthropic:claude-haiku-5-5", PRICES["anthropic:claude-haiku-5-5"]),
    ModelSpec("google:gemini-3.8-flash", PRICES["google:gemini-3.8-flash"]),
    ModelSpec("google:gemini-3.5-flash-lite", PRICES["google:gemini-3.5-flash-lite"]),
    ModelSpec("deepseek:deepseek-flash", PRICES["deepseek:deepseek-flash"]),  # MR-27 candidate
)

# Paused to keep eval spend low (MR-20 D5); move a line back to MODELS to run it.
PAUSED: Final = (
    ModelSpec("openai:gpt-6.1-sol", None),
    ModelSpec("anthropic:claude-sonnet-5-5", PRICES["anthropic:claude-sonnet-5-5"]),
)

SYSTEM_PROMPT: Final = (
    "Eres el asistente de un restaurante en México. Responde en español de México, breve y claro. "
    "Hoy es lunes 2026-10-12; los datos llegan hasta el 2026-10-11. "
    "Sucursales: Centro (705e8e51-376b-5785-adbb-405eff4e2a22) y Polanco "
    "(fdda5e3b-6bcd-5c48-a6de-f524be37463e). "
    "Para cualquier cifra usa las herramientas; nunca inventes números. "
    "Si no existe una herramienta para lo que piden, dilo. "
    "Los cambios solo se proponen con propose_change; nunca digas que ya se aplicaron."
)
