"""Enums, JSON shape and contract rules of NormalizedBatch (spec 10.3)."""

import datetime as dt
import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from mermia_contracts.batch import DailySalesIn, Grain, IssueIn, NormalizedBatch, Period
from mermia_contracts.db import models

D = dt.date(2026, 10, 12)


def make(**over: Any) -> NormalizedBatch:
    base = {
        "parser": "sr.example@v1",
        "source_kind": "sr_report",
        "period": {"from": D, "to": D},
        "grain": "daily",
        "totals": {"lines": 0},
    }
    return NormalizedBatch(**{**base, **over})


def test_database_enums_are_reused_not_redefined() -> None:
    assert NormalizedBatch.model_fields["source_kind"].annotation is models.SourceKind
    assert NormalizedBatch.model_fields["quality"].annotation is models.BatchQuality
    assert IssueIn.model_fields["severity"].annotation is models.IssueSeverity


def test_grain_values_follow_the_architecture() -> None:
    assert [g.value for g in Grain] == [
        "ticket",
        "item_daily",
        "daily",
        "purchase",
        "catalog",
    ]


@pytest.mark.parametrize(
    "field,bad", [("source_kind", "excel"), ("grain", "weekly"), ("quality", "scan")]
)
def test_unknown_enum_values_are_rejected(field: str, bad: str) -> None:
    with pytest.raises(ValidationError):
        make(**{field: bad})


def test_every_database_enum_value_round_trips() -> None:
    for kind in models.SourceKind:
        assert make(source_kind=kind.value).source_kind is kind
    for quality in models.BatchQuality:
        assert make(quality=quality.value).quality is quality


def test_payment_mix_is_keyed_by_payment_method() -> None:
    row = DailySalesIn(business_date=D, net_sales=1, payment_mix={"cash": 1})  # type: ignore[dict-item]
    assert list(row.payment_mix) == [models.PaymentMethod.cash]
    with pytest.raises(ValidationError):
        DailySalesIn(business_date=D, net_sales=1, payment_mix={"bitcoin": 1})  # type: ignore[dict-item]
    with pytest.raises(ValidationError):
        DailySalesIn(business_date=D, net_sales=1, payment_mix={"cash": 1.5})  # type: ignore[dict-item]


def test_contract_version_is_pinned_to_one() -> None:
    assert make().contract_version == 1
    with pytest.raises(ValidationError):
        make(contract_version=2)


@pytest.mark.parametrize(
    "bad",
    ["Not A Parser", "sr.report", "sr.report@v", "SR.report@v1", "sr report@v1", ""],
)
def test_parser_must_look_like_name_at_version(bad: str) -> None:
    with pytest.raises(ValidationError):
        make(parser=bad)


def test_period_is_ordered_and_serialises_with_the_from_alias() -> None:
    with pytest.raises(ValidationError):
        Period(**{"from": dt.date(2026, 10, 13), "to": D})
    assert Period(from_=D, to=D).from_ == D  # type: ignore[call-arg]  # by field name too
    data = json.loads(make().model_dump_json(by_alias=True))
    assert data["period"] == {"from": "2026-10-12", "to": "2026-10-12"}


def test_unknown_fields_are_rejected_everywhere() -> None:
    with pytest.raises(ValidationError):
        make(surprise=1)
    with pytest.raises(ValidationError):
        DailySalesIn(business_date=D, net_sales=1, surprise=1)  # type: ignore[call-arg]


def test_batches_are_immutable() -> None:
    batch = make()
    with pytest.raises(ValidationError):
        batch.parser = "other@v1"


def test_issue_code_format_and_severity() -> None:
    IssueIn(severity=models.IssueSeverity.info, code="period_mismatch", message_es="Aviso")
    with pytest.raises(ValidationError):
        IssueIn(severity=models.IssueSeverity.info, code="Bad Code", message_es="Aviso")
    with pytest.raises(ValidationError):
        IssueIn(severity="fatal", code="ok", message_es="Aviso")  # type: ignore[arg-type]


def test_json_numbers_for_decimals_are_exact() -> None:
    text = (
        '{"parser":"sr.x@v1","source_kind":"sr_report","period":{"from":"2026-10-12","to":"2026-10-12"},'
        '"grain":"item_daily","totals":{"lines":1},"item_sales":[{"item_name":"a",'
        '"period_from":"2026-10-12","period_to":"2026-10-12","units":0.1,"gross":1,"discount":0,"net":1}]}'
    )
    batch = NormalizedBatch.model_validate_json(text)
    assert batch.item_sales[0].units == Decimal("0.1")


def test_default_dump_uses_the_wire_names() -> None:
    batch = make()
    assert json.loads(batch.model_dump_json())["period"] == {
        "from": "2026-10-12",
        "to": "2026-10-12",
    }
    assert batch.model_dump()["period"] == {"from": D, "to": D}
    assert NormalizedBatch.model_validate_json(batch.model_dump_json()) == batch
