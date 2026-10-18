"""Types that depend on unverified report formats say so (spec 10.1)."""

import inspect

from mermia_contracts import batch

PROVISIONAL = {"MenuItemIn", "ItemSalesIn", "DailySalesIn", "RecipeIn", "RecipeLineIn"}


def input_types() -> dict[str, type]:
    return {
        name: cls
        for name, cls in vars(batch).items()
        if inspect.isclass(cls)
        and name.endswith("In")
        and cls.__module__ == batch.__name__
    }


def test_exactly_the_documented_types_are_provisional() -> None:
    marked = {
        name
        for name, cls in input_types().items()
        if (inspect.getdoc(cls) or "").startswith("PROVISIONAL:")
    }
    assert marked == PROVISIONAL


def test_every_input_type_exists() -> None:
    assert set(input_types()) >= PROVISIONAL | {
        "TicketIn",
        "StaffIn",
        "TicketLineIn",
        "PaymentIn",
        "PurchaseIn",
        "SupplierIn",
        "PurchaseLineIn",
        "IssueIn",
    }
