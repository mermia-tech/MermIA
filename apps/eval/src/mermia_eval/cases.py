"""Eval cases: one JSON file each, in apps/eval/cases/."""

from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

CASES_DIR: Final = Path(__file__).resolve().parents[2] / "cases"


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    expected_tool: str
    expected_args: dict[str, Any]
    accepted_args: list[dict[str, Any]] = []  # other argument sets that mean the same
    must_contain: list[str]  # figures the reply must show


def load_cases(directory: Path = CASES_DIR) -> list[Case]:
    return [Case.model_validate_json(p.read_text()) for p in sorted(directory.glob("*.json"))]
