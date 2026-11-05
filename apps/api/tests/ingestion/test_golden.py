"""Every SR sample under fixtures/sr/<version>/ must parse to its golden NormalizedBatch.

The synthetic exports come from the fixture generator (MR-12). When a pilot's real export arrives
(MR-5), drop it under fixtures/sr/<version>/ next to its .golden.json and it is picked up here.
"""

from pathlib import Path

import pytest

from mermia_api.ingestion.registry import XLSX_PARSERS, parse_file
from mermia_contracts.batch import NormalizedBatch

SR = Path(__file__).parents[4] / "fixtures" / "sr"
SAMPLES = sorted(SR.glob("*/*.xlsx"))


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_golden(path: Path) -> None:
    golden = path.with_name(path.stem + ".golden.json")
    expected = NormalizedBatch.model_validate_json(golden.read_text())
    assert parse_file(path.read_bytes()) == expected


def test_every_parser_has_a_sample() -> None:
    parsers = {
        NormalizedBatch.model_validate_json(p.with_name(p.stem + ".golden.json").read_text()).parser
        for p in SAMPLES
    }
    assert {p.name for p in XLSX_PARSERS} <= parsers
