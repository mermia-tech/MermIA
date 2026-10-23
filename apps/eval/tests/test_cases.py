import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mermia_contracts.agent_tools import tool_definitions
from mermia_contracts.rpc import RPCS
from mermia_eval.cases import CASES_DIR, Case, load_cases
from mermia_mock_rpc import rpcs


def test_load_cases_returns_the_example() -> None:
    cases = load_cases()
    case = next(c for c in cases if c.id == "tacos_al_pastor")
    assert case.question == "¿Cuál es el margen de los tacos al pastor?"
    assert case.expected_tool == "get_dish_margin"


TOOL_CASES = [c for c in load_cases() if c.expected_tool is not None]


@pytest.mark.parametrize("case", TOOL_CASES, ids=lambda c: c.id)
def test_expected_args_validate_against_the_c3_model(case: Case) -> None:
    for args in [case.expected_args, *case.accepted_args]:
        RPCS[str(case.expected_tool)].args.model_validate(args)


@pytest.mark.parametrize("case", TOOL_CASES, ids=lambda c: c.id)
def test_must_contain_comes_from_the_mock_answer(case: Case) -> None:
    answer = json.dumps(rpcs.build(str(case.expected_tool)), ensure_ascii=False)
    assert [f for f in case.must_contain if f not in answer] == []


TOOLS = {t["name"]: t["input_schema"]["properties"] for t in tool_definitions()}


def test_ids_are_unique() -> None:
    ids = [c.id for c in load_cases()]
    assert len(ids) == len(set(ids))


def test_only_case_files_in_cases_dir() -> None:
    files = [p for p in CASES_DIR.iterdir() if not p.name.startswith(".")]
    assert [p.name for p in files if p.suffix != ".json"] == []
    assert sorted(p.stem for p in files) == sorted(c.id for c in load_cases())


def test_expected_tool_is_a_known_tool_or_none() -> None:
    assert [c.id for c in load_cases() if c.expected_tool not in {None, *TOOLS}] == []


def test_expected_args_keys_exist_in_the_tool_schema() -> None:
    for c in TOOL_CASES:
        for args in [c.expected_args, *c.accepted_args]:
            assert set(args) <= set(TOOLS[str(c.expected_tool)]), c.id


def test_null_tool_cases_have_empty_expected_args() -> None:
    assert [c.id for c in load_cases() if c.expected_tool is None and c.expected_args] == []


def test_must_not_contain_has_no_empty_phrase() -> None:
    assert [c.id for c in load_cases() if "" in c.must_not_contain] == []


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
