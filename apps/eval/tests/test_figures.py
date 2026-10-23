from pathlib import Path

from mermia_eval import figures
from mermia_eval.cases import load_cases
from mermia_eval.figures import derived_figures, peso


def not_derived(expected: list[str]) -> list[str]:
    known = set(derived_figures().values())
    return [f for f in expected if f not in known]


def test_peso_formats_centavos() -> None:
    assert peso(18432050) == "$184,320.50"
    assert peso(3119500) == "$31,195.00"
    assert (peso(5), peso(0), peso(-5)) == ("$0.05", "$0.00", "-$0.05")


def test_price_jump_is_two_decimals() -> None:
    d = derived_figures()
    assert d["price_jump.Carne al pastor (adobada).before"] == "$170.00"
    assert d["price_jump.Carne al pastor (adobada).after"] == "$195.00"


def test_derived_includes_weekly_total() -> None:
    assert "$184,320.50" in derived_figures().values()
    assert derived_figures()["L1.daily_net_sales.2026-10-11"] == "$31,195.00"


def test_derived_does_not_import_the_mock() -> None:
    assert "mermia_mock_rpc" not in Path(figures.__file__).read_text()


def test_expected_figures_of_cases_are_derived() -> None:
    for case in load_cases():
        assert not_derived(case.expected_figures) == [], case.id


def test_unknown_figure_is_reported() -> None:
    assert not_derived(["$1.23"]) == ["$1.23"]
