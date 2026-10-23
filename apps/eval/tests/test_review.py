from mermia_eval.cases import Case
from mermia_eval.figures import derived_figures
from mermia_eval.review import review_table


def _case(id: str, **kw: object) -> Case:
    base: dict[str, object] = {
        "id": id,
        "question": "¿cuánto vendí?",
        "category": "sales",
        "expected_tool": None,
        "expected_args": {},
        "must_contain": [],
    }
    return Case.model_validate(base | kw)


def test_table_has_one_row_per_case() -> None:
    lines = review_table([_case("a"), _case("b")]).splitlines()
    assert len(lines) == 2 + 2  # header, separator, rows
    assert lines[2].startswith("| a |") and lines[3].startswith("| b |")


def test_table_shows_tool_none_as_ninguna() -> None:
    assert "ninguna" in review_table([_case("a")])


def test_table_names_the_source_of_a_derived_figure() -> None:
    name, value = next(iter(derived_figures().items()))
    row = review_table([_case("a", expected_figures=[value, "$0.01"])]).splitlines()[2]
    assert name in row
    assert "pending" in row


def test_table_keeps_one_row_per_case_with_pipe_and_newline() -> None:
    lines = review_table([_case("a", question="uno | dos\ntres")]).splitlines()
    assert len(lines) == 3
    assert "uno \\| dos tres" in lines[2]
