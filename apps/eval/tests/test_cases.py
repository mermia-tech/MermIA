import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mermia_contracts.agent_tools import ProposeChangeArgs, tool_definitions, tools_sha256
from mermia_contracts.rpc import RPCS
from mermia_eval.cases import CASES_DIR, Case, load_cases
from mermia_mock_rpc import rpcs


def test_load_cases_returns_the_example() -> None:
    cases = load_cases()
    case = next(c for c in cases if c.id == "tacos_al_pastor")
    assert case.question == "¿Cuál es el margen de los tacos al pastor?"
    assert case.expected_tool == "get_dish_margin"


TOOL_CASES = [c for c in load_cases() if c.expected_tool in RPCS]
WRITE_CASES = [c for c in load_cases() if c.expected_tool == "propose_change"]


@pytest.mark.parametrize("case", WRITE_CASES, ids=lambda c: c.id)
def test_write_args_validate_against_propose_change(case: Case) -> None:
    for args in [case.expected_args, *case.accepted_args]:
        ProposeChangeArgs.model_validate(args)


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
    assert next(c for c in load_cases() if c.id == "tacos_al_pastor").expected_figures == []


def test_forty_cases_in_the_planned_categories() -> None:
    cases = load_cases()
    counts = {c: sum(x.category == c for x in cases) for c in {x.category for x in cases}}
    assert len(cases) == 40
    assert counts == {
        "sales": 7,
        "top_dishes": 6,
        "cost_margin": 6,
        "ops": 4,
        "locations": 3,
        "ambiguous": 3,
        "writes": 4,
        "out_of_scope": 4,
        "adversarial": 3,
    }


def test_tool_definitions_unchanged_since_the_cases_were_written() -> None:
    assert tools_sha256() == "dffa2445f97f3cfcebef94269bcf4afc7222df80dff8868835b7474745dfe3e6", (
        "tools changed: re-check the cases and update this hash"
    )
