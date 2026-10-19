"""C5: exactly five kinds, each payload checked against its kind."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mermia_contracts.pending import TARGET_TYPE, ChangeProposal, PendingKind

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
