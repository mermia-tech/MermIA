"""C5: exactly five kinds, each payload checked against its kind."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mermia_contracts.db.models import IngredientPriceRow
from mermia_contracts.db.models import PendingChangeStatus as S
from mermia_contracts.pending import (
    TARGET_TYPE,
    ApplyCode,
    ApplyPendingChangeArgs,
    ApplyResult,
    ChangeProposal,
    IngredientPriceSet,
    PendingKind,
)

EXAMPLES = Path(__file__).parent / "examples" / "pending"
ADAPTER: TypeAdapter[Any] = TypeAdapter(ChangeProposal)
KINDS = [
    "ingredient_price.set",
    "recipe.upsert",
    "menu_item_price.set",
    "import_batch.approve",
    "import_batch.rollback",
]
TARGET = "0f7a1c52-3b6e-7c1a-9d33-000000000001"
DAY = "2026-10-19"
SEVEN_DP = Decimal("1.0000001")  # unit prices allow six decimals


def test_exactly_the_five_kinds() -> None:
    assert [k.value for k in PendingKind] == KINDS
    assert set(TARGET_TYPE) == set(PendingKind)


@pytest.mark.parametrize("kind", KINDS)
def test_valid_example_round_trips(kind: str) -> None:
    raw = (EXAMPLES / f"{kind}.json").read_text()
    parsed = ADAPTER.validate_json(raw)
    assert parsed.kind == kind
    assert ADAPTER.validate_json(ADAPTER.dump_json(parsed)) == parsed


def _doc(kind: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((EXAMPLES / f"{kind}.json").read_text())
    return doc


@pytest.mark.parametrize(
    "kind", ["ingredient_alias.confirm", "settings.update", "recipe.delete", ""]
)
def test_other_kinds_are_rejected(kind: str) -> None:
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({**_doc("import_batch.approve"), "kind": kind})


@pytest.mark.parametrize(
    "kind,patch",
    [
        ("ingredient_price.set", {"values": {"unit_price": "220", "effective_from": "2026-10-19"}}),
        ("ingredient_price.set", {"values": {"unit_price": 220, "effective_from": "mañana"}}),
        ("ingredient_price.set", {"values": {"unit_price": 220}}),
        (
            "ingredient_price.set",
            {"values": {"unit_price": 1.0000001, "effective_from": "2026-10-19"}},
        ),
        ("recipe.upsert", {"values": {"yield_qty": 1, "lines": []}}),
        ("menu_item_price.set", {"values": {"price_gross": 55.5, "effective_from": "2026-10-19"}}),
        (
            "menu_item_price.set",
            {"values": _doc("ingredient_price.set")["values"]},
        ),  # wrong kind's payload
        ("import_batch.approve", {"values": {"force": True}}),
        ("import_batch.rollback", {"target_id": "not-a-uuid"}),
        ("import_batch.rollback", {"reason": " "}),
        ("import_batch.rollback", {"surprise": 1}),
    ],
)
def test_bad_proposals_are_rejected(kind: str, patch: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({**_doc(kind), **patch})


def test_batch_kinds_need_no_values() -> None:
    parsed = ADAPTER.validate_python({"kind": "import_batch.approve", "target_id": TARGET})
    assert parsed.values.model_dump() == {}


PID = "0f7a1c52-3b6e-7c1a-9d55-000000000001"
ALLOWED = {
    "applied": {S.applied},
    "already_applied": {S.applied},
    "expired": {S.expired},
    "conflict": {S.conflict},
    "failed": {S.failed},
    "not_pending": {S.approved, S.rejected, S.expired, S.conflict, S.failed},
    "forbidden_role": set(S),
}


def test_apply_codes_are_exactly_the_documented_set() -> None:
    assert {c.value for c in ApplyCode} == {*ALLOWED, "not_found"}


@pytest.mark.parametrize("code", sorted(ALLOWED))
@pytest.mark.parametrize("status", list(S))
def test_apply_result_status_must_fit_the_code(code: str, status: S) -> None:
    doc = {"code": code, "pending_change_id": PID, "status": status}
    if status in ALLOWED[code]:
        assert ApplyResult.model_validate(doc).status == status
    else:
        with pytest.raises(ValidationError):
            ApplyResult.model_validate(doc)


@pytest.mark.parametrize("extra", [{"status": "pending"}, {"status": "applied"}, {"message": "x"}])
def test_not_found_reveals_nothing(extra: dict[str, Any]) -> None:
    assert (
        ApplyResult.model_validate({"code": "not_found", "pending_change_id": PID}).status is None
    )
    with pytest.raises(ValidationError):
        ApplyResult.model_validate({"code": "not_found", "pending_change_id": PID, **extra})


def test_apply_result_without_status_is_rejected_for_codes_that_need_one() -> None:
    with pytest.raises(ValidationError):
        ApplyResult.model_validate({"code": "applied", "pending_change_id": PID})


def test_ok_is_true_only_for_applied_and_already_applied() -> None:
    oks = {c for c in ApplyCode if c in ("applied", "already_applied")}
    for code in ApplyCode:
        status = None if code == ApplyCode.not_found else next(iter(ALLOWED.get(code, {S.pending})))
        result = ApplyResult(code=code, pending_change_id=PID, status=status)  # type: ignore[arg-type]
        assert result.ok == (code in oks)


def test_apply_args_need_two_uuids_and_nothing_else() -> None:
    ApplyPendingChangeArgs.model_validate({"id": PID, "user_id": PID})
    for bad in (
        {"id": PID},
        {"id": PID, "user_id": "x"},
        {"id": PID, "user_id": PID, "role": "owner"},
    ):
        with pytest.raises(ValidationError):
            ApplyPendingChangeArgs.model_validate(bad)


def test_ingredient_price_is_per_base_unit_like_the_database() -> None:
    contract = IngredientPriceSet.model_fields["unit_price"].description or ""
    column = IngredientPriceRow.model_fields["unit_price_net"].description or ""
    assert contract.startswith("unit=pesos_per_base_unit")
    assert column.startswith("unit=pesos_per_base_unit")
    assert "purchase" not in contract.replace("never per purchase unit", "")
