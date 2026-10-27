import json
from typing import Any

import pytest

from mermia_eval.cases import Case, load_cases
from mermia_eval.score import ToolCall, score_args, score_numbers, score_tool
from mermia_mock_rpc import rpcs

CASE = next(c for c in load_cases() if c.id == "tacos_al_pastor")
ANSWER = json.dumps(rpcs.build("get_dish_margin"), ensure_ascii=False)
GOOD = ToolCall("get_dish_margin", {"dish": "tacos al pastor"})
REPLY = "El margen es $37.63 (67.2%), con costo $18.40 y precio $65.00."


def test_tool_ok() -> None:
    assert score_tool(CASE, [GOOD]) == 1.0


def test_tool_zero_when_no_call() -> None:
    assert score_tool(CASE, []) == 0.0


def test_tool_zero_when_other_tool_called() -> None:
    assert score_tool(CASE, [GOOD, ToolCall("get_top_dishes", {})]) == 0.0


def test_tool_repeated_expected_call_is_fine() -> None:
    assert score_tool(CASE, [GOOD, GOOD]) == 1.0


def test_args_null_equals_omitted() -> None:
    call = ToolCall("get_dish_margin", {"dish": "tacos al pastor", "location_id": None})
    assert score_args(CASE, [call]) == 1.0


def test_args_wrong_dish_is_zero() -> None:
    assert score_args(CASE, [ToolCall("get_dish_margin", {"dish": "hamburguesa"})]) == 0.0


def test_args_zero_when_no_call() -> None:
    assert score_args(CASE, []) == 0.0


def test_args_accepts_alternative() -> None:
    case = CASE.model_copy(update={"accepted_args": [{"dish": "tacos al pastor (orden de 3)"}]})
    call = ToolCall("get_dish_margin", {"dish": "tacos al pastor (orden de 3)"})
    assert score_args(case, [call]) == 1.0


def test_numbers_ok() -> None:
    assert score_numbers(CASE, REPLY, [ANSWER]) == 1.0


def test_numbers_zero_on_invented_figure() -> None:
    assert score_numbers(CASE, REPLY + " Unos $40 de utilidad.", [ANSWER]) == 0.0


def test_numbers_zero_when_must_contain_missing() -> None:
    assert score_numbers(CASE, "El margen es $37.63 y el costo $18.40.", [ANSWER]) == 0.0


def test_numbers_formats_are_equal() -> None:
    reply = "Margen 37.63 pesos, 67.2 %, costo $18.40 y precio $65.00"
    assert score_numbers(CASE, reply, [ANSWER]) == 1.0


def test_numbers_zero_when_no_calls_and_figures_present() -> None:
    assert score_numbers(CASE, REPLY, []) == 0.0


@pytest.mark.parametrize("n", range(1, 10))
def test_numbers_ignore_list_markers(n: int) -> None:
    assert score_numbers(CASE, f"{n}. " + REPLY, [ANSWER]) == 1.0


@pytest.mark.parametrize("prefix", ["2) ", "  3. "])
def test_numbers_ignore_other_list_marker_styles(prefix: str) -> None:
    assert score_numbers(CASE, prefix + REPLY, [ANSWER]) == 1.0


def test_numbers_marker_strip_keeps_invented_figures() -> None:
    assert score_numbers(CASE, "1. " + REPLY + " Unos $40 más.", [ANSWER]) == 0.0


def test_numbers_comma_only_before_three_digits() -> None:
    case = CASE.model_copy(update={"must_contain": []})
    assert score_numbers(case, "Hay 3,4 y 5 opciones", ["3 4 5"]) == 1.0
    assert score_numbers(case, "Vendió $1,840.00", ["1840"]) == 1.0


def test_args_ignore_case() -> None:
    assert score_args(CASE, [ToolCall("get_dish_margin", {"dish": "Tacos Al Pastor"})]) == 1.0


def test_args_case_insensitive_inside_nested_values() -> None:
    case = CASE.model_copy(update={"expected_args": {"p": {"to": "ab", "xs": ["Cd"]}}})
    call = ToolCall("get_dish_margin", {"p": {"to": "AB", "xs": ["cD"]}})
    assert score_args(case, [call]) == 1.0


def _bare(**update: Any) -> Case:
    return CASE.model_copy(update={"must_contain": [], **update})


def test_numbers_sign_flip_fails() -> None:
    case, tool = _bare(), '{"change": "-3.1%"}'
    assert score_numbers(case, "bajó +3.1%", [tool]) == 0.0
    assert score_numbers(case, "bajó -3.1%", [tool]) == 1.0
    assert score_numbers(case, "bajó \N{MINUS SIGN}3.1%", [tool]) == 1.0


def test_numbers_plus_sign_is_no_sign() -> None:
    case = _bare()
    assert score_numbers(case, "subió 7.2%", ['{"t": "+7.2%"}']) == 1.0
    assert score_numbers(case, "subió +7.2%", ['{"t": "7.2%"}']) == 1.0


def test_numbers_thousands_group_must_end_the_number() -> None:
    # "1,2345" is 1 and 2345, not 1234 and 5
    assert score_numbers(_bare(), "Hay 1,2345", ["1 2345"]) == 1.0


def test_numbers_leading_dot_decimal() -> None:
    assert score_numbers(_bare(), "Es .5", ["0.5"]) == 1.0


def test_numbers_ignore_digits_glued_to_letters() -> None:
    assert score_numbers(_bare(), "en la sucursal L7", ['{"a": 1}']) == 1.0


def test_numbers_zero_for_a_date_not_in_tool_data() -> None:
    assert score_numbers(_bare(), "Al 2026-10-20.", ['{"x": 1}']) == 0.0


def test_numbers_date_from_tool_data_is_fine() -> None:
    assert score_numbers(_bare(), "Al 2026-10-20.", ['{"d": "2026-10-20"}']) == 1.0


def test_list_marker_keeps_a_year_at_line_start() -> None:
    case = _bare(must_contain=["$18.40"])
    reply = "2026. El costo es $18.40"
    assert score_numbers(case, reply, ['{"c": "$18.40", "y": 2026}']) == 1.0
    assert score_numbers(case, reply, ['{"c": "$18.40"}']) == 0.0


def test_numbers_ids_dates_and_raw_values_are_not_known_figures() -> None:
    # Digits inside UUIDs, ISO dates and raw centavos are not figures the agent may quote.
    for invented in (
        "vendes 12 órdenes",
        "hay 405 órdenes",
        "desde hace 2026 días",
        "cuesta $6,500",
    ):
        assert score_numbers(CASE, f"{REPLY} {invented}", [ANSWER]) == 0.0, invented
    assert score_numbers(CASE, REPLY, [ANSWER]) == 1.0


def test_numbers_a_known_date_may_be_quoted_whole() -> None:
    assert score_numbers(_bare(), "Datos al 2026-10-12.", [ANSWER]) == 1.0


def test_numbers_extracted_when_glued_to_a_currency_code() -> None:
    assert score_numbers(_bare(), "subir a MXN70.00", ['{"c": "$65.00"}']) == 0.0
    assert score_numbers(_bare(), "cuesta USD65.00", ['{"c": "$65.00"}']) == 1.0


def test_numbers_sign_before_the_dollar_sign_counts() -> None:
    case, tool = _bare(), '{"m": "-$37.63"}'
    assert score_numbers(case, "pérdida de $37.63", [tool]) == 0.0
    assert score_numbers(case, "pérdida de -$37.63", [tool]) == 1.0


NO_TOOL = _bare(expected_tool=None, expected_args={})


def test_tool_none_ok_without_calls() -> None:
    assert score_tool(NO_TOOL, []) == 1.0


def test_tool_none_zero_when_a_tool_is_called() -> None:
    assert score_tool(NO_TOOL, [GOOD]) == 0.0


def test_args_none_ok_without_calls() -> None:
    assert score_args(NO_TOOL, []) == 1.0
    assert score_args(NO_TOOL, [GOOD]) == 0.0


def test_numbers_none_tool_zero_on_figure_not_in_question() -> None:
    assert score_numbers(NO_TOOL, "Vendiste $5,000", []) == 0.0
    assert score_numbers(NO_TOOL, "Hola, ¿en qué te ayudo?", []) == 1.0


def test_numbers_zero_on_forbidden_phrase() -> None:
    case = _bare(must_not_contain=["ya quedó"])
    assert score_numbers(case, "Listo, YA QUEDÓ", []) == 0.0


def test_numbers_rounding_is_zero() -> None:
    assert score_numbers(_bare(), "unos $184 mil", ['{"v": "$184,320.50"}']) == 0.0


TOP = CASE.model_copy(
    update={
        "expected_tool": "get_top_dishes",
        "expected_args": {"period": "last_30d", "limit": 5},
        "accepted_args": [],
    }
)


def _top(**args: Any) -> list[ToolCall]:
    return [ToolCall("get_top_dishes", {"period": "last_30d", **args})]


def test_args_default_limit_omitted_equals_explicit() -> None:
    omitted = TOP.model_copy(update={"expected_args": {"period": "last_30d"}})
    for case in (TOP, omitted):
        assert score_args(case, _top()) == 1.0
        assert score_args(case, _top(limit=5)) == 1.0


def test_args_schema_default_order_ignored() -> None:
    assert score_args(TOP, _top(order="desc")) == 1.0


def test_args_nested_null_removed() -> None:
    case = TOP.model_copy(update={"expected_args": {"period": "last_30d", "x": {"a": 1}}})
    assert score_args(case, _top(x={"a": 1, "effective_from": None})) == 1.0


def test_args_reason_ignored() -> None:
    assert score_args(TOP, _top(reason="porque si")) == 1.0


def test_args_non_default_wrong_value_is_zero() -> None:
    assert score_args(TOP, _top(limit=3)) == 0.0
    assert score_args(TOP, _top(order="asc")) == 0.0


def test_args_every_call_must_match() -> None:
    assert score_args(TOP, _top() + _top(limit=3)) == 0.0
    assert score_args(TOP, _top() + _top()) == 1.0


def test_args_numeric_string_equals_number() -> None:
    case = TOP.model_copy(update={"expected_args": {"period": "last_30d", "limit": 3}})
    for limit in ("3", 3.0, "3.00"):
        assert score_args(case, _top(limit=limit)) == 1.0
    assert score_args(case, _top(limit="30")) == 0.0


def test_numbers_forbidden_phrase_ignores_accents() -> None:
    case = _bare(must_not_contain=["ya cambié"])
    assert score_numbers(case, "Listo, ya cambie el precio", []) == 0.0
    assert score_numbers(_bare(must_not_contain=["ya cambie"]), "Ya cambié el precio", []) == 0.0


FORECAST = _bare(expected_tool=None, expected_args={}, accepted_tools=["get_sales_summary"])
CONTEXT = [ToolCall("get_sales_summary", {"period": "last_week"})]


def test_none_tool_accepts_listed_tool_for_context() -> None:
    for score in (score_tool, score_args):
        assert score(FORECAST, []) == 1.0
        assert score(FORECAST, CONTEXT) == 1.0
        assert score(FORECAST, [GOOD]) == 0.0
        assert score(FORECAST, [*CONTEXT, GOOD]) == 0.0
