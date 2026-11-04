"""MR-26: replies copy the figures the RPC formatted; nothing is computed (spec: Rendering)."""

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from mermia_api.agent.templates import render
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
