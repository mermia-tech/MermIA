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


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c.id)
def test_expected_args_validate_against_the_c3_model(case: Case) -> None:
    for args in [case.expected_args, *case.accepted_args]:
        RPCS[case.expected_tool].args.model_validate(args)


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c.id)
def test_must_contain_comes_from_the_mock_answer(case: Case) -> None:
    answer = json.dumps(rpcs.build(case.expected_tool), ensure_ascii=False)
    assert [f for f in case.must_contain if f not in answer] == []


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text(
        json.dumps(
            {
                "id": "x",
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
