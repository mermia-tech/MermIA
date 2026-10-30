"""Eval cases: one JSON file each, in apps/eval/cases/."""

from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

CASES_DIR: Final = Path(__file__).resolve().parents[2] / "cases"

Category = Literal[
    "sales",
    "top_dishes",
    "cost_margin",
    "ops",
    "locations",
    "ambiguous",
    "writes",
    "out_of_scope",
    "adversarial",
]


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    category: Category
    expected_tool: str | None  # None: the agent must answer without calling a tool
    expected_args: dict[str, Any]
    accepted_tools: list[str] = []  # with expected_tool None: tools it may call for context
    accepted_args: list[dict[str, Any]] = []  # other argument sets that mean the same
    must_contain: list[str]  # figures the reply must show
    must_not_contain: list[str] = []  # phrases the reply must not say
    expected_figures: list[str] = []  # documentation only, not scored


def load_cases(directory: Path = CASES_DIR) -> list[Case]:
    return [Case.model_validate_json(p.read_text()) for p in sorted(directory.glob("*.json"))]
