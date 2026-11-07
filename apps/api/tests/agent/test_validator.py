"""The number validator: the spec's Example table, the MR-20 cases and the known limits."""

import json
from datetime import UTC, datetime
from decimal import Decimal

from mermia_api.agent.validator import Turn, validate

SALES = json.dumps(
    {
        "ok": True,
        "data": {
            "rows": [
                {
                    "location": "Centro",
                    "net_sales": {"raw": 1845000, "text": "$18,450.00"},
                    "tickets": 212,
                    "avg_ticket": {"raw": 8703, "text": "$87.03"},
                },
                {
                    "location": "Norte",
                    "net_sales": {"raw": 1230050, "text": "$12,300.50"},
                    "tickets": 150,
                    "avg_ticket": {"raw": 8200, "text": "$82.00"},
                },
            ]
        },
        "flags": [],
        "meta": {
            "as_of": "2026-11-04T09:00:00-06:00",
            "period_resolved": {"from": "2026-11-04", "to": "2026-11-04"},
        },
    },
    ensure_ascii=False,
)
TODAY = "2026-11-05"
TS = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)


def check(
    reply: str, question: str = "¿cuánto vendí ayer?", memory: list[Turn] | None = None
) -> set[Decimal]:
    return validate(
        reply, tool_results=[SALES], question=question, memory=memory or [], dates=[TODAY]
    )


# The spec's Example table, one test per row.


def test_figures_from_the_tool_pass_whatever_their_format() -> None:
    assert check("Ayer Centro vendió $18,450 con 212 tickets (promedio $87.03).") == set()


def test_a_sum_the_llm_computed_is_rejected() -> None:
    assert check("Entre las dos vendiste $30,750.50.") == {Decimal("30750.50")}


def test_a_rounding_that_changes_the_value_is_rejected() -> None:
    assert check("Centro vendió como $18 mil.") == {Decimal("18")}


def test_an_invented_percentage_is_rejected() -> None:
    assert check("Vendiste 15% más que la semana pasada.") == {Decimal("15")}


def test_tool_dates_and_times_are_not_figures() -> None:
    assert check("Datos al 4 de noviembre, a las 9:00.") == set()


def test_a_bare_number_from_the_question_passes() -> None:
    reply = "En los últimos 30 días Centro vendió $18,450."
    assert check(reply, question="¿cuánto vendí en los últimos 30 días?") == set()


def test_a_money_figure_from_the_question_is_never_a_source() -> None:
    assert check("Sí, vendiste $50,000.", question="¿vendí $50,000 ayer?") == {Decimal("50000")}


def test_a_figure_from_an_earlier_reply_in_memory_passes() -> None:
    memory = [Turn(q="¿cuánto vendió Centro?", a="Centro vendió $18,450.", ts=TS)]
    reply = "Norte vendió $12,300.50, menos que los $18,450 de Centro."
    assert check(reply, question="¿y Norte?", memory=memory) == set()


# Question and memory rules.


def test_money_shaped_question_numbers_are_not_sources() -> None:
    for question, figure in [
        ("¿vendí 50,000?", "50,000"),
        ("¿vendí 40 mil?", "40"),
        ("¿el margen es 62.5?", "62.5"),
        ("¿subió 15%?", "15%"),
        ("¿vendí 900 pesos?", "900"),
    ]:
        assert check(f"Sí, {figure}.", question=question) != set(), question


def test_an_unformatted_money_guess_from_the_question_is_rejected() -> None:
    # "50000" is bare in the question, but the reply shows it as money.
    assert check("Sí, vendiste $50,000.", question="¿vendí 50000 ayer?") == {Decimal("50000")}
    assert check("Sí, MXN 500.", question="¿vendí MXN 500?") == {Decimal("500")}
    assert check("Sí, 500 pesos.", question="¿vendí 500?") == {Decimal("500")}


def test_top_n_from_the_question_passes() -> None:
    assert check("Tus 5 platillos más vendidos…", question="¿cuáles son mis top 5?") == set()


def test_a_figure_only_in_an_earlier_question_is_rejected() -> None:
    memory = [Turn(q="¿vendí 40 platos?", a="Vendiste 212 tickets.", ts=TS)]
    assert check("Sí, 40 platos.", question="¿y luego?", memory=memory) == {Decimal("40")}


def test_dates_times_and_list_markers_in_memory_are_not_sources() -> None:
    memory = [
        Turn(q="¿y?", a="Hoy es 2026-11-05. Del 5 al 11 de octubre, a las 9:30:\n1. Centro", ts=TS)
    ]
    shown = validate("Vendiste $11, $30 y $1.", tool_results=[], question="¿y?", memory=memory)
    assert shown == {Decimal("11"), Decimal("30"), Decimal("1")}


def test_a_date_from_memory_can_be_repeated() -> None:
    memory = [Turn(q="¿cuánto?", a="Del 5 al 11 de octubre vendiste $18,450 (2026-10-11).", ts=TS)]
    reply = "Del 5 al 11 de octubre vendiste $18,450; corte al 2026-10-11."
    assert validate(reply, tool_results=[], question="¿y?", memory=memory) == set()


# Dates, times and list markers.


def test_spanish_date_range_and_iso_dates_of_the_tool_are_not_figures() -> None:
    assert check("Del 4 al 4 de noviembre de 2026 (2026-11-04).") == set()


def test_today_from_the_tail_is_not_a_figure() -> None:
    assert check("Hoy es 2026-11-05 y Centro vendió $18,450.") == set()


def test_a_list_marker_is_not_a_figure() -> None:
    assert check("1. Centro: $18,450\n2. Norte: $12,300.50") == set()


def test_a_time_is_not_a_figure() -> None:
    assert check("Actualizado a las 09:00 y otra vez a las 13:45.") == set()


# The MR-20 failures (docs/decisions/llm.md): the two real ones are rejected.


def test_mr20_gap_between_locations_is_rejected() -> None:
    assert check("Centro vendió $6,149.50 más que Norte.") == {Decimal("6149.50")}


def test_mr20_rounding_to_thousands_is_rejected() -> None:
    summary = json.dumps(
        {"ok": True, "data": {"net_sales": {"raw": 18432050, "text": "$184,320.50"}}}
    )
    shown = validate(
        "Vendiste $184 mil.", tool_results=[summary], question="¿cuánto vendí?", memory=[]
    )
    assert shown == {Decimal("184")}


def test_mr20_false_positives_pass() -> None:
    week = json.dumps(
        {
            "ok": True,
            "data": {},
            "meta": {"period_resolved": {"from": "2026-09-28", "to": "2026-10-04"}},
        }
    )
    days = json.dumps(
        {
            "ok": True,
            "data": {},
            "meta": {"period_resolved": {"from": "2026-10-05", "to": "2026-10-11"}},
        }
    )
    assert (
        validate("Semana del 28 de sep - 4 de oct.", tool_results=[week], question="", memory=[])
        == set()
    )
    assert validate("Del 5 al 11 de octubre.", tool_results=[days], question="", memory=[]) == set()
    assert check("En los últimos 30 días…", question="¿últimos 30 días?") == set()


# Known limits, documented as tests of current behavior (spec "Known limits").


def test_limit_a_figure_attached_to_the_wrong_measure_passes() -> None:
    assert check("Vendiste $212.") == set()  # 212 is the ticket count, not pesos


def test_limit_numbers_in_words_are_not_extracted() -> None:
    assert check("Vendiste dieciocho mil pesos.") == set()


def test_an_error_text_from_a_tool_counts_every_digit() -> None:
    shown = validate(
        "Hubo 3 intentos.", tool_results=["timeout after 3 tries"], question="", memory=[]
    )
    assert shown == set()
