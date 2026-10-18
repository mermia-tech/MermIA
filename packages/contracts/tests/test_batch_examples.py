"""Example batches: valid ones round-trip, invalid ones fail for the labelled reason."""

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from mermia_contracts.batch import NormalizedBatch

EXAMPLES = Path(__file__).parent / "examples"
SNAPSHOT = EXAMPLES / "normalized_batch.schema.json"

VALID = sorted(EXAMPLES.glob("*_valid.json"))
INVALID_REASON = {
    "invalid_period_reversed.json": "period",
    "invalid_float_money.json": "int_type",
    "invalid_string_money.json": "int_type",
    "invalid_unknown_field.json": "extra_forbidden",
    "invalid_version_2.json": "literal_error",
    "invalid_bad_enum.json": "enum",
    "invalid_bad_parser.json": "string_pattern_mismatch",
    "invalid_blank_name.json": "string_pattern_mismatch",
    "invalid_too_many_decimals.json": "decimal_max_places",
    "invalid_bad_severity.json": "enum",
    "invalid_negative_lines.json": "greater_than_equal",
}


def test_every_invalid_example_is_covered() -> None:
    on_disk = {p.name for p in EXAMPLES.glob("invalid_*.json")}
    assert on_disk == set(INVALID_REASON)


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_valid_examples_round_trip(path: Path) -> None:
    batch = NormalizedBatch.model_validate_json(path.read_text())
    dumped = batch.model_dump_json(by_alias=True)
    assert NormalizedBatch.model_validate_json(dumped) == batch
    assert json.loads(dumped)["period"]["from"] == batch.period.from_.isoformat()


@pytest.mark.parametrize("name,reason", sorted(INVALID_REASON.items()))
def test_invalid_examples_fail_for_the_labelled_reason(name: str, reason: str) -> None:
    with pytest.raises(ValidationError) as info:
        NormalizedBatch.model_validate_json((EXAMPLES / name).read_text())
    kinds = " ".join(e["type"] for e in info.value.errors())
    messages = " ".join(e["msg"] for e in info.value.errors())
    assert reason in kinds or reason in messages, (kinds, messages)


def test_json_schema_snapshot() -> None:
    schema = (
        json.dumps(
            NormalizedBatch.model_json_schema(by_alias=True), indent=2, sort_keys=True
        )
        + "\n"
    )
    if os.environ.get("UPDATE_SNAPSHOT") or not SNAPSHOT.exists():
        SNAPSHOT.write_text(schema)
    assert schema == SNAPSHOT.read_text(), (
        "schema changed: review it, then UPDATE_SNAPSHOT=1 pytest"
    )
