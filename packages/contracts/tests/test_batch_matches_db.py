"""Each input field that claims a table column maps to a real column with the same unit.

The loader (MR-16) fills tenant_id, batch_id, source_id and location_id; fields without a
column of their own are listed as LOADER_ONLY with the reason.
"""

import enum
import types
import typing

import pytest

from mermia_contracts import batch
from mermia_contracts.db import models

# input type -> (row model, {input field: column})
MAP: dict[type, tuple[type, dict[str, str]]] = {
    batch.MenuItemIn: (
        models.MenuItemRow,
        {"external_id": "external_id", "name": "name", "kind": "kind"},
    ),
    batch.ItemSalesIn: (
        models.ItemSalesAggRow,
        {
            "period_from": "period_from",
            "period_to": "period_to",
            "units": "units",
            "gross": "gross",
            "discount": "discount",
            "net": "net",
        },
    ),
    batch.DailySalesIn: (
        models.DailySalesAggRow,
        {
            "business_date": "business_date",
            "net_sales": "net_sales",
            "tax": "tax",
            "tickets": "tickets",
            "guests": "guests",
            "discounts": "discounts",
            "cancellations_amount": "cancellations_amount",
            "cancellations_count": "cancellations_count",
            "payment_mix": "payment_mix",
            "tips": "tips",
        },
    ),
    batch.TicketIn: (
        models.SaleTicketRow,
        {
            "external_id": "external_id",
            "business_date": "business_date",
            "opened_at": "opened_at",
            "closed_at": "closed_at",
            "channel": "channel",
            "area": "area",
            "table_label": "table_label",
            "guests": "guests",
            "subtotal": "subtotal",
            "discount": "discount",
            "tax": "tax",
            "tip": "tip",
            "total": "total",
            "status": "status",
            "fiscal_status": "fiscal_status",
        },
    ),
    batch.TicketLineIn: (
        models.SaleLineRow,
        {
            "qty": "qty",
            "unit_price": "unit_price",
            "discount": "discount",
            "tax": "tax",
            "net": "net",
            "is_void": "is_void",
            "void_reason": "void_reason",
        },
    ),
    batch.PaymentIn: (
        models.PaymentRow,
        {
            "method": "method",
            "amount": "amount",
            "tip": "tip",
            "provider": "provider",
            "provider_ref": "provider_ref",
        },
    ),
    batch.StaffIn: (
        models.StaffRow,
        {"external_id": "external_id", "display_name": "display_name", "role": "role"},
    ),
    batch.SupplierIn: (
        models.SupplierRow,
        {"name": "name", "rfc": "rfc", "kind": "kind"},
    ),
    batch.PurchaseIn: (
        models.PurchaseDocRow,
        {
            "kind": "kind",
            "cfdi_uuid": "cfdi_uuid",
            "issued_at": "issued_at",
            "subtotal": "subtotal",
            "total": "total",
        },
    ),
    batch.PurchaseLineIn: (
        models.PurchaseLineRow,
        {
            "description": "description",
            "qty": "qty",
            "unit": "unit",
            "unit_price_net": "unit_price_net",
        },
    ),
    batch.RecipeIn: (models.RecipeRow, {"yield_qty": "yield_qty"}),
    batch.RecipeLineIn: (
        models.RecipeLineRow,
        {"qty_base": "qty_base", "yield_override_pct": "yield_override_pct"},
    ),
    batch.IssueIn: (
        models.ImportIssueRow,
        {
            "severity": "severity",
            "code": "code",
            "message_es": "message_es",
            "row_ref": "row_ref",
        },
    ),
}

# fields that name something the loader resolves to an id, or that live in another table
LOADER_ONLY = {
    batch.MenuItemIn: {
        "category",
        "price_gross",
        "tax_rate",
    },  # menu_category / menu_item_price
    batch.ItemSalesIn: {"item_external_id", "item_name"},  # resolved to menu_item_id
    batch.TicketIn: {"staff", "lines", "payments"},
    batch.TicketLineIn: {"item_external_id", "item_name", "parent_line_index"},
    batch.PurchaseIn: {"supplier", "lines"},
    batch.PurchaseLineIn: {"ingredient_name"},
    batch.RecipeIn: {"menu_item_external_id", "menu_item_name", "lines"},
    batch.RecipeLineIn: {"ingredient_name", "ingredient_external_id", "unit"},
}


def optional(annotation: object) -> bool:
    return type(None) in typing.get_args(annotation) or (
        isinstance(annotation, types.UnionType) and type(None) in annotation.__args__
    )


def unit(annotation: object) -> str | None:
    text = str(annotation or "")
    return text.split("unit=")[1].split("'")[0].split(")")[0] if "unit=" in text else None


def enum_of(annotation: object) -> object:
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    return args[0] if args else annotation


@pytest.mark.parametrize(
    "input_type", sorted(MAP, key=lambda t: t.__name__), ids=lambda t: t.__name__
)
def test_input_fields_map_to_columns(input_type: type) -> None:
    row, mapping = MAP[input_type]
    fields = input_type.model_fields
    allowed = LOADER_ONLY.get(input_type, set())
    assert set(fields) == set(mapping) | allowed, "every field is mapped or explained"
    for name, column in mapping.items():
        assert column in row.model_fields, f"{row.__name__}.{column} does not exist"
        in_field, col_field = fields[name], row.model_fields[column]
        # money, quantities and percentages carry the same unit on both sides
        in_unit = unit(in_field.annotation) or unit(in_field.description)
        col_unit = unit(col_field.annotation) or unit(col_field.description)
        if in_unit and col_unit:
            assert in_unit == col_unit, f"{input_type.__name__}.{name}: {in_unit} vs {col_unit}"
        # enums are the generated ones
        col_enum = enum_of(col_field.annotation)
        if isinstance(col_enum, type) and issubclass(col_enum, enum.StrEnum):
            assert enum_of(in_field.annotation) is col_enum, f"{input_type.__name__}.{name}"
        # a field the database requires cannot be optional on the input side
        if (
            not optional(col_field.annotation)
            and col_field.is_required()
            and name not in {"external_id"}
        ):
            assert not optional(in_field.annotation), (
                f"{input_type.__name__}.{name} is optional but {column} is required"
            )
