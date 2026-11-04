"""MR-26: replies copy the figures the RPC formatted; nothing is computed (spec: Rendering)."""

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from mermia_api.agent.templates import no_data, render
from mermia_contracts.rpc import Flag

CENTRO = "705e8e51-376b-5785-adbb-405eff4e2a22"


def test_sales_summary(example: Any, el_guero: dict[UUID, str]) -> None:
    reply = render(
        "get_sales_summary",
        {"period": "last_week", "location_id": CENTRO},
        example("get_sales_summary"),
        el_guero,
    )
    assert reply.text == (
        "La semana pasada en Centro vendiste $184,320.50.\n"
        "648 tickets, ticket promedio $284.45.\n"
        "Contra el periodo anterior: +7.2%."
    )


def test_null_figures_are_left_out_not_shown_as_zero(
    example: Any, el_guero: dict[UUID, str]
) -> None:
    reply = render(
        "get_sales_summary",
        {"period": "yesterday", "location_id": CENTRO},
        example("get_sales_summary.nulls"),
        el_guero,
    )
    assert reply.text == (
        "Ayer en Centro vendiste $31,195.00.\n"
        "La fuente no reporta comensales, descuentos ni cancelaciones."
    )


def test_no_location_means_all_of_the_users(example: Any, el_guero: dict[UUID, str]) -> None:
    reply = render(
        "get_sales_summary", {"period": "yesterday"}, example("get_sales_summary"), el_guero
    )
    assert reply.text.startswith("Ayer en tus 2 sucursales vendiste $184,320.50.")


def test_a_single_location_is_named(example: Any) -> None:
    reply = render(
        "get_sales_summary",
        {"period": "this_month"},
        example("get_sales_summary"),
        {UUID(CENTRO): "Centro"},
    )
    assert reply.text.startswith("Este mes en Centro vendiste $184,320.50.")


def test_every_flag_message_is_its_own_line_in_order(
    example: Any, el_guero: dict[UUID, str]
) -> None:
    envelope = example("get_sales_summary").model_copy(
        update={
            "flags": [
                Flag(code="missing_days", message="Faltan datos de 2 de 7 días del periodo."),
                Flag(code="no_message"),
                Flag(code="previous_partial", message="Faltan días en el periodo anterior."),
            ]
        }
    )
    reply = render("get_sales_summary", {"period": "last_week"}, envelope, el_guero)
    assert reply.text.splitlines()[-2:] == [
        "Faltan datos de 2 de 7 días del periodo.",
        "Faltan días en el periodo anterior.",
    ]


def test_data_that_does_not_fit_the_rpc_model_is_rejected(
    example: Any, el_guero: dict[UUID, str]
) -> None:
    envelope = example("get_sales_summary").model_copy(update={"data": {"net_sales": "lots"}})
    with pytest.raises(ValidationError):
        render("get_sales_summary", {"period": "last_week"}, envelope, el_guero)


def test_compare_periods(example: Any, el_guero: dict[UUID, str]) -> None:
    args = {
        "metric": "net_sales",
        "period_a": "last_week",
        "period_b": "prev_week",
        "location_id": CENTRO,
    }
    reply = render("compare_periods", args, example("compare_periods"), el_guero)
    assert reply.text == (
        "La semana pasada en Centro vendiste $184,320.50 contra $171,905.00 la semana "
        "antepasada.\n"
        "Diferencia: +$12,415.50 (+7.2%)."
    )


def test_compare_periods_average_ticket_and_no_percentage(
    example: Any, el_guero: dict[UUID, str]
) -> None:
    envelope = example("compare_periods")
    data = {**envelope.data, "metric": "avg_ticket", "pct_change": None}
    args = {"metric": "avg_ticket", "period_a": "last_week", "period_b": "prev_week"}
    reply = render("compare_periods", args, envelope.model_copy(update={"data": data}), el_guero)
    assert reply.text == (
        "La semana pasada en tus 2 sucursales tu ticket promedio fue $184,320.50 contra "
        "$171,905.00 la semana antepasada.\n"
        "Diferencia: +$12,415.50."
    )


def test_top_dishes(example: Any, el_guero: dict[UUID, str]) -> None:
    args = {"period": "this_month", "metric": "units", "order": "desc", "limit": 5}
    reply = render("get_top_dishes", args, example("get_top_dishes"), el_guero)
    assert reply.text == (
        "Tus 2 platillos más vendidos este mes en tus 2 sucursales:\n"
        "1. Tacos al pastor (orden de 3): 1,208\n"
        "2. Coca-Cola: 816"
    )


def test_one_dish_reads_singular(example: Any, el_guero: dict[UUID, str]) -> None:
    envelope = example("get_top_dishes")
    data = {**envelope.data, "rows": envelope.data["rows"][:1]}
    args = {
        "period": "last_month",
        "metric": "units",
        "order": "asc",
        "limit": 1,
        "location_id": CENTRO,
    }
    reply = render("get_top_dishes", args, envelope.model_copy(update={"data": data}), el_guero)
    assert reply.text == (
        "Tu platillo menos vendido el mes pasado en Centro:\n1. Tacos al pastor (orden de 3): 1,208"
    )


def test_no_dishes_sold(example: Any, el_guero: dict[UUID, str]) -> None:
    envelope = example("get_top_dishes")
    data = {**envelope.data, "rows": []}
    args = {"period": "yesterday", "metric": "units", "order": "desc", "limit": 5}
    reply = render("get_top_dishes", args, envelope.model_copy(update={"data": data}), el_guero)
    assert reply.text == "No hay ventas registradas ayer en tus 2 sucursales."


def test_uncosted_sales_flag_is_shown(example: Any, el_guero: dict[UUID, str]) -> None:
    message = "Algunos platillos vendidos no tienen costo y no entran en el ranking."
    envelope = example("get_top_dishes").model_copy(
        update={"flags": [Flag(code="uncosted_sales", message=message)]}
    )
    args = {"period": "this_month", "metric": "units", "order": "desc", "limit": 5}
    reply = render("get_top_dishes", args, envelope, el_guero)
    assert reply.text.splitlines()[-1] == message


def test_food_cost(example: Any, el_guero: dict[UUID, str]) -> None:
    args = {"period": "yesterday", "location_id": CENTRO}
    reply = render("get_food_cost_pct", args, example("get_food_cost_pct"), el_guero)
    assert reply.text == (
        "Tu food cost de ayer en Centro fue 37.5% (meta: 32.0%).\n"
        "Cobertura de costos: 71.4% de las ventas."
    )


def test_food_cost_without_target_shows_the_estimate_caveat(
    example: Any, el_guero: dict[UUID, str]
) -> None:
    message = "Costos estimados: hay precios de más de 30 días o sin CFDI, o recetas sin confirmar."
    envelope = example("get_food_cost_pct")
    envelope = envelope.model_copy(
        update={
            "data": {**envelope.data, "target": None},
            "flags": [Flag(code="cost_estimated", message=message)],
        }
    )
    reply = render("get_food_cost_pct", {"period": "last_week"}, envelope, el_guero)
    assert reply.text == (
        "Tu food cost de la semana pasada en tus 2 sucursales fue 37.5%.\n"
        "Cobertura de costos: 71.4% de las ventas.\n" + message
    )


def test_data_status(example: Any, el_guero: dict[UUID, str]) -> None:
    reply = render("get_data_status", {}, example("get_data_status"), el_guero)
    assert reply.text == (
        "Último reporte cargado el 12 de octubre de 2026.\n"
        "No falta ningún día.\n"
        "29 ingredientes con precio desactualizado.\n"
        "Cobertura de costos: 100.0%."
    )


def test_data_status_with_gaps_and_no_report(example: Any, el_guero: dict[UUID, str]) -> None:
    envelope = example("get_data_status")
    data = {
        **envelope.data,
        "sources": [{"source_kind": "sr_report", "last_batch_at": None}],
        "missing_business_days": ["2026-10-05", "2026-10-06"],
        "stale_costs": 0,
    }
    reply = render("get_data_status", {}, envelope.model_copy(update={"data": data}), el_guero)
    assert reply.text == (
        "Todavía no hay reportes cargados.\n"
        "Faltan datos de: 5 de octubre, 6 de octubre.\n"
        "Cobertura de costos: 100.0%."
    )


def test_compare_locations(example: Any, el_guero: dict[UUID, str]) -> None:
    args = {"metric": "net_sales", "period": "last_week"}
    reply = render("compare_locations", args, example("compare_locations"), el_guero)
    assert reply.text == (
        "Ventas de la semana pasada por sucursal:\n"
        "1. Centro: $184,320.50\n"
        "2. Polanco: $160,920.80 (-$23,399.70 vs. Centro)"
    )


def test_compare_locations_food_cost_with_missing_locations(
    example: Any, el_guero: dict[UUID, str]
) -> None:
    envelope = example("compare_locations")
    rows = [
        {
            **envelope.data["rows"][0],
            "value": {"raw": 37.4569, "text": "37.5%"},
            "diff_vs_best": {"raw": 0, "text": "0.0 pts"},
        },
    ]
    envelope = envelope.model_copy(
        update={
            "data": {"metric": "food_cost_pct", "rows": rows},
            "flags": [Flag(code="missing_locations", message="Sin datos para: Polanco.")],
        }
    )
    args = {"metric": "food_cost_pct", "period": "yesterday"}
    reply = render("compare_locations", args, envelope, el_guero)
    assert (
        reply.text == "Food cost de ayer por sucursal:\n1. Centro: 37.5%\nSin datos para: Polanco."
    )


def test_compare_locations_without_rows(example: Any, el_guero: dict[UUID, str]) -> None:
    envelope = example("compare_locations")
    envelope = envelope.model_copy(update={"data": {"metric": "net_sales", "rows": []}})
    reply = render(
        "compare_locations", {"metric": "net_sales", "period": "today"}, envelope, el_guero
    )
    assert reply.text == "No hay ventas registradas hoy."


def test_payment_methods(example: Any, el_guero: dict[UUID, str]) -> None:
    args = {"period": "yesterday", "by": "payment_method", "location_id": CENTRO}
    reply = render("get_sales_breakdown", args, example("get_sales_breakdown"), el_guero)
    assert reply.text == (
        "Ventas de ayer en Centro por forma de pago:\n"
        "- Tarjeta: $17,781.15 (57.0%)\n"
        "- Efectivo: $11,230.20 (36.0%)\n"
        "- Transferencia: $2,183.65 (7.0%)"
    )


def test_payment_methods_unknown_key_partial_detail_and_no_rows(
    example: Any, el_guero: dict[UUID, str]
) -> None:
    envelope = example("get_sales_breakdown")
    row = {**envelope.data["rows"][0], "key": "vales"}
    message = "Solo 3 de 7 días con ventas tienen este detalle."
    partial = envelope.model_copy(
        update={
            "data": {"by": "payment_method", "rows": [row]},
            "flags": [Flag(code="partial_data", message=message)],
        }
    )
    args = {"period": "last_week", "by": "payment_method"}
    assert render("get_sales_breakdown", args, partial, el_guero).text == (
        "Ventas de la semana pasada en tus 2 sucursales por forma de pago:\n"
        "- vales: $17,781.15 (57.0%)\n" + message
    )
    empty = envelope.model_copy(update={"data": {"by": "payment_method", "rows": []}})
    assert render("get_sales_breakdown", args, empty, el_guero).text == (
        "No hay ventas registradas la semana pasada en tus 2 sucursales."
    )


@pytest.mark.parametrize(
    ("rpc", "args", "first_line"),
    [
        (
            "get_food_cost_pct",
            {"period": "last_month"},
            "Tu food cost del mes pasado en tus 2 sucursales fue 37.5% (meta: 32.0%).",
        ),
        (
            "compare_locations",
            {"metric": "net_sales", "period": "last_month"},
            "Ventas del mes pasado por sucursal:",
        ),
        (
            "get_sales_breakdown",
            {"period": "last_month", "by": "payment_method"},
            "Ventas del mes pasado en tus 2 sucursales por forma de pago:",
        ),
    ],
)
def test_de_el_is_contracted(
    rpc: str, args: dict[str, Any], first_line: str, example: Any, el_guero: dict[UUID, str]
) -> None:
    assert render(rpc, args, example(rpc), el_guero).text.splitlines()[0] == first_line


@pytest.mark.parametrize(
    ("rpc", "args", "text"),
    [
        ("get_sales_summary", {"period": "last_month"}, "No tengo datos del mes pasado todavía."),
        (
            "get_top_dishes",
            {"period": "last_month", "metric": "margin_pct"},
            "Todavía no tengo costos de tus platillos para calcular la ganancia del mes pasado.",
        ),
    ],
)
def test_no_data_contracts_de_el(rpc: str, args: dict[str, Any], text: str) -> None:
    assert no_data(rpc, args).text == text
