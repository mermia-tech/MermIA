"""Every sample file must parse to its golden NormalizedBatch.

- fixtures/sr/<version>/: SR exports. The synthetic ones come from the fixture generator (MR-12).
  When a pilot's real export arrives (MR-5), drop it under fixtures/sr/<version>/ next to its
  .golden.json and it is picked up here.
- fixtures/templates/: the MermIA recipe template, written from the seed by its CLI
  (`uv run python -m mermia_api.ingestion.templates.recetas ... --golden`), never by hand.
- fixtures/cfdi/<origin>/: CFDI 4.0 supplier invoices (XML). `synthetic/` is written by hand and
  its golden checked by hand; a real anonymized invoice goes in its own folder with its golden.
"""

from pathlib import Path

import pytest

from mermia_api.ingestion.registry import XLSX_PARSERS, XML_PARSERS, parse_file
from mermia_contracts.batch import NormalizedBatch

FIXTURES = Path(__file__).parents[4] / "fixtures"
SAMPLES = (
    sorted(FIXTURES.glob("sr/*/*.xlsx"))
    + sorted(FIXTURES.glob("templates/*.xlsx"))
    + sorted(FIXTURES.glob("cfdi/*/*.xml"))
)


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
    names = {p.name for p in XLSX_PARSERS} | {p.name for p in XML_PARSERS}
    assert names <= parsers
