import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mermia_contracts.rpc import RPCS
from mermia_eval.cases import Case, load_cases
from mermia_mock_rpc import rpcs


def test_load_cases_returns_the_example() -> None:
    cases = load_cases()
    assert [c.id for c in cases] == ["tacos_al_pastor"]
    assert cases[0].question == "¿Cuál es el margen de los tacos al pastor?"
    assert cases[0].expected_tool == "get_dish_margin"


TOOL_CASES = [c for c in load_cases() if c.expected_tool]


@pytest.mark.parametrize("case", TOOL_CASES, ids=lambda c: c.id)
def test_expected_args_validate_against_the_c3_model(case: Case) -> None:
    for args in [case.expected_args, *case.accepted_args]:
        RPCS[str(case.expected_tool)].args.model_validate(args)


@pytest.mark.parametrize("case", TOOL_CASES, ids=lambda c: c.id)
def test_must_contain_comes_from_the_mock_answer(case: Case) -> None:
    answer = json.dumps(rpcs.build(str(case.expected_tool)), ensure_ascii=False)
    assert [f for f in case.must_contain if f not in answer] == []


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text(
        json.dumps(
            {
                "id": "x",
                "category": "ops",
                "question": "q",
                "expected_tool": "get_dish_margin",
                "expected_args": {},
                "must_contain": [],
                "typo": 1,
            }
        )
    )
    with pytest.raises(ValidationError):
        load_cases(tmp_path)


def test_case_without_category_is_rejected(tmp_path: Path) -> None:
    case: dict[str, object] = {
        "id": "x",
        "question": "q",
        "expected_tool": None,
        "expected_args": {},
    }
    (tmp_path / "bad.json").write_text(json.dumps({**case, "must_contain": []}))
    with pytest.raises(ValidationError):
        load_cases(tmp_path)


def test_expected_figures_default_empty() -> None:
    assert load_cases()[0].expected_figures == []
