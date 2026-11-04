"""MR-26: the router answers only what it fully understands (spec: Router rules)."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from mermia_api.agent.router import route
from mermia_contracts.rpc import RPCS

CASES = sorted((Path(__file__).parents[4] / "apps" / "eval" / "cases").glob("*.json"))
CENTRO = "705e8e51-376b-5785-adbb-405eff4e2a22"
POLANCO = "fdda5e3b-6bcd-5c48-a6de-f524be37463e"

MUST_MATCH = {
    "sales_yesterday",
    "sales_last_week",
    "top_dishes_top5_month_units",
    "top_dishes_top3_revenue_30d",
    "cost_margin_food_cost_yesterday",
    "out_of_scope_data_status",
    "locations_centro_vs_polanco_last_week",
    "locations_this_month_sales",
    "ops_payment_split",
}

MUST_NOT_MATCH = {
    "adversarial_forecast_december",
    "adversarial_round_sales",
    "adversarial_wrong_figure_sales",
    "ambiguous_compare_sales_no_periods",
    "ambiguous_followup_no_context",
    "ambiguous_raise_price_no_value",
    "writes_ingredient_price_pastor",
    "writes_menu_price_bistec_centro",
    "writes_menu_price_torta_polanco",
    "writes_recipe_gringa",
    "out_of_scope_employee_count",
    "out_of_scope_whatsapp_supplier",
    "out_of_scope_wine_pairing",
    "cost_margin_bistec_margin",
    "cost_margin_cost_alerts_30d",
    "cost_margin_food_cost_range",
    "cost_margin_menu_engineering_30d",
    "tacos_al_pastor",
    "ops_discounts",
    "ops_sales_by_waiter",
    "ops_saturday_cancellations",
    "sales_explicit_range",
    "sales_by_weekday",
    "sales_month_vs_last",
    "top_dishes_top2_units_1_11_oct",
}


def _case(path: Path) -> dict[str, Any]:
    case: dict[str, Any] = json.loads(path.read_text())
    return case


def _norm(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    # the eval cases leave defaults out inconsistently: compare what the RPC would receive
    dumped: dict[str, Any] = (
        RPCS[tool].args.model_validate(args).model_dump(mode="json", exclude_defaults=True)
    )
    return dumped


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_eval_cases_never_mismatch(path: Path, el_guero: dict[UUID, str]) -> None:
    case = _case(path)
    match = route(case["question"], el_guero)
    if match is None:
        return
    assert match.rpc == case["expected_tool"]
    allowed = [case["expected_args"], *case.get("accepted_args", [])]
    assert _norm(match.rpc, match.args) in [_norm(match.rpc, a) for a in allowed]


def test_the_case_lists_name_real_cases() -> None:
    stems = {p.stem for p in CASES}
    assert stems >= MUST_MATCH
    assert stems >= MUST_NOT_MATCH
    assert len(CASES) == 40


@pytest.mark.parametrize("case_id", sorted(MUST_MATCH))
def test_must_match(case_id: str, el_guero: dict[UUID, str]) -> None:
    case = _case(next(p for p in CASES if p.stem == case_id))
    assert route(case["question"], el_guero) is not None


@pytest.mark.parametrize("case_id", sorted(MUST_NOT_MATCH))
def test_must_not_match(case_id: str, el_guero: dict[UUID, str]) -> None:
    case = _case(next(p for p in CASES if p.stem == case_id))
    assert route(case["question"], el_guero) is None


@pytest.mark.parametrize(
    ("text", "period"),
    [
        ("¿Cuánto VENDÍ ayer?", "yesterday"),
        ("cuanto vendi hoy", "today"),
        ("cuánto vendí esta semana", "this_week"),
        ("cuánto vendí la semana pasada", "last_week"),
        ("cuánto vendí la semana antepasada", "prev_week"),
        ("cuánto vendí este mes", "this_month"),
        ("¿cuánto llevo vendido en lo que va del mes?", None),  # "llevo" is not known
        ("cuánto vendí en lo que va del mes", "this_month"),
        ("cuánto vendí el mes pasado", "last_month"),
        ("cuánto vendí los últimos 7 días", "last_7d"),
        ("cuánto vendí en los últimos 30 días", "last_30d"),
        ("oye, dime cuánto vendí ayer porfa", "yesterday"),
        ("¿y las ventas de ayer?", "yesterday"),
    ],
)
def test_sales_total_named_periods(
    text: str, period: str | None, el_guero: dict[UUID, str]
) -> None:
    match = route(text, el_guero)
    if period is None:
        assert match is None
        return
    assert match is not None
    assert match.rpc == "get_sales_summary"
    assert match.args == {"period": period}


def test_yesterday_and_other_periods_are_two_intents(el_guero: dict[UUID, str]) -> None:
    yesterday = route("cuánto vendí ayer", el_guero)
    last_week = route("cuánto vendí la semana pasada", el_guero)
    assert yesterday is not None and yesterday.intent == "sales_yesterday"
    assert last_week is not None and last_week.intent == "sales_period"


def test_a_visible_location_sets_location_id(el_guero: dict[UUID, str]) -> None:
    match = route("cuánto vendí ayer en Polanco", el_guero)
    assert match is not None
    assert match.args == {"period": "yesterday", "location_id": POLANCO}


def test_the_longest_location_name_wins() -> None:
    historico = UUID("00000000-0000-4000-8000-000000000001")
    locations = {UUID(CENTRO): "Centro", historico: "Centro Histórico"}
    match = route("cuánto vendí ayer en el Centro Histórico", locations)
    assert match is not None
    assert match.args["location_id"] == str(historico)


@pytest.mark.parametrize(
    "text",
    [
        "cuánto vendí",  # no period
        "cuánto vendí ayer y la semana pasada",  # two periods
        "vendí $200,000 la semana pasada, ¿cierto?",  # leftover digit
        "cuánto vendí del 5 al 11 de octubre",  # explicit dates
        "redondéame las ventas de ayer",  # write verb
        "cuánto vendí ayer de tacos al pastor",  # a dish filter it cannot apply
        "¿cuánto vendió Pepe ayer?",  # a staff filter it cannot apply
        "cuánto vendí ayer sin contar las bebidas",
        "cuánto vendí ayer en Centro y Polanco",  # two locations
        "cuánto vendí ayer en Satélite",  # a location it does not know
        "cuánto me vendieron mis meseros este mes",  # "mes" is not inside "meseros"
        "ventas de ayer a las tres",  # an hour, not the whole day
        "ventas de ayer de las dos a las cinco",
    ],
)
def test_not_sure_means_no_match(text: str, el_guero: dict[UUID, str]) -> None:
    assert route(text, el_guero) is None


def test_a_location_the_user_cannot_see_is_no_match() -> None:
    polanco_only = {UUID(POLANCO): "Polanco"}
    assert route("cuánto vendí ayer en Centro", polanco_only) is None


def test_past_tense_is_not_a_write_verb(el_guero: dict[UUID, str]) -> None:
    # "subió" and "bajó" describe; "súbele" and "bájale" order a change
    assert route("súbele a las ventas de ayer", el_guero) is None
    assert route("las ventas de ayer subieron", el_guero) is None  # "subieron" is not known


@pytest.mark.parametrize("text", ["cuánto vendí ayer", "ventas del mes pasado en Centro"])
def test_match_args_validate(text: str, el_guero: dict[UUID, str]) -> None:
    match = route(text, el_guero)
    assert match is not None
    RPCS[match.rpc].args.model_validate(match.args)


@pytest.mark.parametrize(
    ("text", "metric"),
    [
        ("¿cuánto vendí la semana pasada contra la antepasada?", "net_sales"),
        ("ventas de la semana pasada vs la anterior", "net_sales"),
        ("ventas de la semana pasada comparado con la semana anterior", "net_sales"),
        ("ticket promedio de la semana pasada contra la antepasada", "avg_ticket"),
    ],
)
def test_last_week_against_the_week_before(
    text: str, metric: str, el_guero: dict[UUID, str]
) -> None:
    match = route(text, el_guero)
    assert match is not None
    assert match.intent == "compare_periods"
    assert match.rpc == "compare_periods"
    assert match.args == {"metric": metric, "period_a": "last_week", "period_b": "prev_week"}


def test_compare_periods_takes_a_location(el_guero: dict[UUID, str]) -> None:
    match = route("ventas de la semana pasada vs la anterior en Centro", el_guero)
    assert match is not None
    assert match.args["location_id"] == CENTRO


@pytest.mark.parametrize(
    "text",
    [
        "ventas de este mes contra el mes pasado",  # part of a month against a whole month
        "ventas de esta semana vs la pasada",  # part of a week against a whole week
        "ventas de ayer contra antier",
        "propinas de la semana pasada contra la antepasada",  # a metric it does not know
        "la semana pasada contra la anterior",  # no metric
        "ventas y ticket promedio de la semana pasada vs la anterior",  # two metrics
        "ventas de la semana pasada contra la anterior en Centro y Polanco",
    ],
)
def test_compare_periods_not_sure_means_no_match(text: str, el_guero: dict[UUID, str]) -> None:
    assert route(text, el_guero) is None


@pytest.mark.parametrize(
    ("text", "args"),
    [
        (
            "¿cuáles son los 5 platillos más vendidos este mes?",
            {"period": "this_month", "metric": "units", "order": "desc", "limit": 5},
        ),
        (
            "dime los tres platillos que más dinero me venden en los últimos 30 días",
            {"period": "last_30d", "metric": "revenue", "order": "desc", "limit": 3},
        ),
        (
            "¿cuál es el platillo menos vendido del mes pasado?",
            {"period": "last_month", "metric": "units", "order": "asc", "limit": 1},
        ),
        (
            "los platillos más vendidos de la semana pasada",
            {"period": "last_week", "metric": "units", "order": "desc", "limit": 5},
        ),
        (
            "¿cuál es el platillo que más ganancia en pesos me deja este mes?",
            {"period": "this_month", "metric": "margin", "order": "desc", "limit": 1},
        ),
        (
            "los 3 platillos con menor porcentaje de ganancia este mes",
            {"period": "this_month", "metric": "margin_pct", "order": "asc", "limit": 3},
        ),
        (
            "top 10 platillos más vendidos este mes",
            {"period": "this_month", "metric": "units", "order": "desc", "limit": 10},
        ),
        (
            "los 5 platillos más vendidos este mes en Centro",
            {
                "period": "this_month",
                "metric": "units",
                "order": "desc",
                "limit": 5,
                "location_id": CENTRO,
            },
        ),
    ],
)
def test_top_dishes(text: str, args: dict[str, Any], el_guero: dict[UUID, str]) -> None:
    match = route(text, el_guero)
    assert match is not None
    assert (match.intent, match.rpc, match.args) == ("top_dishes", "get_top_dishes", args)


@pytest.mark.parametrize(
    "text",
    [
        "mis platillos estrella de este mes",  # menu engineering
        "¿cuál es el platillo más rentable este mes?",  # no measure it knows
        "los 15 platillos más vendidos este mes",  # more than 10
        "los platillos de este mes",  # no measure
        "¿qué platillo me deja el menor porcentaje de ganancia este mes?",  # two measures
        "platillos más y menos vendidos este mes",  # two orders
        "los platillos que más venden este mes",  # units or money?
        "los 5 platillos más vendidos",  # no period
        "los platillos más vendidos este mes contra el mes pasado",  # two intents
        "dime en mis dos sucursales los platillos más vendidos este mes",  # "dos" is not N
    ],
)
def test_top_dishes_not_sure_means_no_match(text: str, el_guero: dict[UUID, str]) -> None:
    assert route(text, el_guero) is None


@pytest.mark.parametrize(
    ("text", "args"),
    [
        (
            "¿cuánto fue mi food cost de ayer en Centro?",
            {"period": "yesterday", "location_id": CENTRO},
        ),
        ("food cost de la semana pasada", {"period": "last_week"}),
        ("¿cuál es mi costo de alimentos de este mes?", {"period": "this_month"}),
    ],
)
def test_food_cost(text: str, args: dict[str, Any], el_guero: dict[UUID, str]) -> None:
    match = route(text, el_guero)
    assert match is not None
    assert (match.intent, match.rpc, match.args) == ("food_cost", "get_food_cost_pct", args)


@pytest.mark.parametrize("text", ["¿ya están al día mis datos?", "¿mis datos están actualizados?"])
def test_data_status(text: str, el_guero: dict[UUID, str]) -> None:
    match = route(text, el_guero)
    assert match is not None
    assert (match.intent, match.rpc, match.args) == ("data_status", "get_data_status", {})


@pytest.mark.parametrize(
    "text",
    [
        "food cost",  # no period
        "food cost de ayer en Centro y Polanco",
        "¿cuántos empleados tengo?",
        "ventas y food cost de ayer",  # two intents
        "¿mis datos de ayer están al día?",  # data status takes no period
        "¿ya está al día?",  # about what?
    ],
)
def test_food_cost_and_data_status_not_sure_means_no_match(
    text: str, el_guero: dict[UUID, str]
) -> None:
    assert route(text, el_guero) is None


@pytest.mark.parametrize(
    ("text", "args"),
    [
        (
            "cuánto vendió cada local la semana pasada",
            {"metric": "net_sales", "period": "last_week"},
        ),
        (
            "¿cuál de mis sucursales vendió más este mes?",
            {"metric": "net_sales", "period": "this_month"},
        ),
        (
            "food cost por sucursal la semana pasada",
            {"metric": "food_cost_pct", "period": "last_week"},
        ),
        (
            "ventas de ayer por sucursal, Centro y Polanco",
            {"metric": "net_sales", "period": "yesterday"},
        ),
    ],
)
def test_compare_locations(text: str, args: dict[str, Any], el_guero: dict[UUID, str]) -> None:
    match = route(text, el_guero)
    assert match is not None
    assert (match.intent, match.rpc, match.args) == ("compare_locations", "compare_locations", args)


@pytest.mark.parametrize(
    ("text", "args"),
    [
        (
            "¿cuánto entró ayer por tarjeta, efectivo y transferencia?",
            {"period": "yesterday", "by": "payment_method"},
        ),
        (
            "formas de pago de la semana pasada en Polanco",
            {"period": "last_week", "by": "payment_method", "location_id": POLANCO},
        ),
    ],
)
def test_payment_methods(text: str, args: dict[str, Any], el_guero: dict[UUID, str]) -> None:
    match = route(text, el_guero)
    assert match is not None
    assert (match.intent, match.rpc, match.args) == (
        "payment_methods",
        "get_sales_breakdown",
        args,
    )


def test_compare_locations_needs_two_locations() -> None:
    assert route("cuánto vendió cada local la semana pasada", {UUID(CENTRO): "Centro"}) is None


@pytest.mark.parametrize(
    "text",
    [
        "cada local la semana pasada",  # no metric
        "ventas y food cost por sucursal la semana pasada",  # two metrics
        "ventas por sucursal",  # no period
        "¿quién de mis meseros vende más este mes?",  # staff breakdown
        "¿qué día de la semana me deja más?",  # weekday breakdown
        "formas de pago",  # no period
        "formas de pago de ayer en Centro y Polanco",
        "formas de pago por sucursal de ayer",  # two intents
    ],
)
def test_locations_and_payments_not_sure_means_no_match(
    text: str, el_guero: dict[UUID, str]
) -> None:
    assert route(text, el_guero) is None


def test_a_payment_method_on_a_sales_question_gets_the_breakdown(
    el_guero: dict[UUID, str],
) -> None:
    # the breakdown holds that exact figure (spec D6, decided at Checkpoint B)
    match = route("¿cuánto vendí ayer en efectivo?", el_guero)
    assert match is not None
    assert match.args == {"period": "yesterday", "by": "payment_method"}


def test_a_location_name_without_letters_does_not_hang() -> None:
    # "🌮" normalizes to "", which once made _take match an empty phrase forever
    code = (
        "from uuid import uuid4\n"
        "from mermia_api.agent.router import route\n"
        "m = route('cuánto vendí ayer', {uuid4(): '🌮', uuid4(): 'Polanco', uuid4(): ''})\n"
        "assert m is not None and m.args == {'period': 'yesterday'}, m\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)


def test_two_locations_with_the_same_name_are_not_told_apart() -> None:
    a, b = uuid4(), uuid4()
    locations = {a: "Centro", b: "Céntro", UUID(POLANCO): "Polanco"}
    assert route("cuánto vendí ayer en Centro", locations) is None
    match = route("cuánto vendí ayer en Polanco", locations)
    assert match is not None and match.args["location_id"] == POLANCO


@pytest.mark.parametrize(
    "text",
    [
        # what / why questions are not "how much" (review on #78)
        "qué vendimos ayer",
        "qué se vendió ayer",
        "por qué vendí ayer",
        "qué entró ayer",
        "¿por qué las ventas de ayer?",
        # a per-location or partial-location question is not the combined total
        "ventas de ayer por sucursales",
        "en cuántas sucursales vendí ayer",
        "en qué sucursales vendí ayer",
        "ventas de ayer en centro y en todas las sucursales",
    ],
)
def test_review_misroutes_fall_through(text: str, el_guero: dict[UUID, str]) -> None:
    assert route(text, el_guero) is None


@pytest.mark.parametrize("name", ["Baja", "Roma-Norte", "Sta. Fe"])
def test_location_names_match_like_the_text(name: str) -> None:
    # "Baja" is also a write verb and punctuation is dropped from the text
    other = uuid4()
    match = route(f"cuánto vendí ayer en {name}", {UUID(CENTRO): "Centro", other: name})
    assert match is not None
    assert match.args == {"period": "yesterday", "location_id": str(other)}
