"""NormalizedBatch: the output of every parser (09 section 3, spec 10.1).

Wire format is JSON with snake_case names. Money is integer centavos, quantities and unit
prices are exact decimals, instants carry a time zone, and unknown fields are an error.
Enums are the generated database enums, so the contract cannot drift from the schema.

Types marked PROVISIONAL depend on report formats that are still unverified (Corte Z,
"Productos vendidos", "Recetas"); they may change until the first real parser lands
(MR-15, MR-23). Each field's docstring-free mapping to a table column is checked by
tests/test_batch_matches_db.py.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from mermia_contracts.db.models import (
    BatchQuality,
    FiscalStatus,
    IssueSeverity,
    MenuItemKind,
    PaymentMethod,
    PurchaseDocKind,
    SaleChannel,
    SourceKind,
    SupplierKind,
    TicketStatus,
)

# Strict types: no float, no string, no bool where a number is expected (spec 10.1).
Cents = Annotated[int, Field(strict=True, description="unit=centavos")]
Count = Annotated[int, Field(strict=True, ge=0)]
Quantity = Annotated[
    Decimal,
    Field(strict=True, max_digits=18, decimal_places=6, description="unit=quantity"),
]
UnitPrice = Annotated[
    Decimal,
    Field(
        strict=True,
        max_digits=20,
        decimal_places=6,
        description="unit=pesos_per_purchase_unit",
    ),
]
PercentPoints = Annotated[
    Decimal,
    Field(
        strict=True,
        max_digits=7,
        decimal_places=4,
        description="unit=percent_points",
    ),
]
Fraction = Annotated[
    Decimal,
    Field(
        strict=True,
        ge=0,
        le=1,
        max_digits=5,
        decimal_places=4,
        description="unit=fraction",
    ),
]
# Required text is never blank, as in the database (spec 5.1). The value is kept as given.
Text = Annotated[str, Field(pattern=r"\S")]


class Grain(StrEnum):
    """What one row of the batch means (09 section 3)."""

    ticket = "ticket"
    item_daily = "item_daily"
    daily = "daily"
    purchase = "purchase"
    catalog = "catalog"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Period(Model):
    """Business dates covered by the batch, both inclusive."""

    from_: dt.date = Field(alias="from")
    to: dt.date

    @model_validator(mode="after")
    def _ordered(self) -> Period:
        if self.from_ > self.to:
            raise ValueError("period.from must not be after period.to")
        return self


class Totals(Model):
    """Figures the loader checks against the rows (03 B.5)."""

    net_sales: Cents | None = None
    units: Quantity | None = None
    lines: Count


class MenuItemIn(Model):
    """PROVISIONAL: which report supplies menu prices and categories is unverified.

    Columns: menu_item (external_id, name, kind), menu_category.name (category),
    menu_item_price (price_gross, tax_rate).
    """

    external_id: Text | None = None
    name: Text
    category: Text | None = None
    kind: MenuItemKind = MenuItemKind.dish
    price_gross: Cents | None = None
    tax_rate: Fraction | None = None


class ItemSalesIn(Model):
    """PROVISIONAL: "Productos vendidos" columns for SR 10-12 are unverified.

    Columns: item_sales_agg. The item is resolved to menu_item_id by the loader.
    """

    item_external_id: Text | None = None
    item_name: Text
    period_from: dt.date
    period_to: dt.date
    units: Quantity
    gross: Cents
    discount: Cents
    net: Cents

    @model_validator(mode="after")
    def _ordered(self) -> ItemSalesIn:
        if self.period_from > self.period_to:
            raise ValueError("period_from must not be after period_to")
        return self


class DailySalesIn(Model):
    """PROVISIONAL: the Corte Z / "Ventas por dia" format is unverified.

    Columns: daily_sales_agg. A figure the report does not give stays None ("not
    reported" is not zero).
    """

    business_date: dt.date
    net_sales: Cents
    tax: Cents | None = None
    tickets: Count | None = None
    guests: Count | None = None
    discounts: Cents | None = None
    cancellations_amount: Cents | None = None
    cancellations_count: Count | None = None
    payment_mix: dict[PaymentMethod, Cents] = Field(default_factory=dict)
    tips: Cents | None = None


class StaffIn(Model):
    """Columns: staff. First name only (09 section 2.3)."""

    external_id: Text | None = None
    display_name: Text
    role: Text | None = None


class TicketLineIn(Model):
    """Columns: sale_line. The item is resolved to menu_item_id by the loader."""

    item_external_id: Text | None = None
    item_name: Text
    parent_line_index: Annotated[int, Field(strict=True, ge=0)] | None = None
    qty: Quantity
    unit_price: Cents
    discount: Cents = 0
    tax: Cents = 0
    net: Cents
    is_void: bool = False
    void_reason: Text | None = None


class PaymentIn(Model):
    """Columns: payment."""

    method: PaymentMethod
    amount: Cents
    tip: Cents = 0
    provider: Text | None = None
    provider_ref: Text | None = None


class TicketIn(Model):
    """Columns: sale_ticket (ticket grain; the ERP/PMS push payload, Phase 1b)."""

    external_id: Text
    business_date: dt.date
    opened_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None
    channel: SaleChannel | None = None
    area: Text | None = None
    table_label: Text | None = None
    guests: Count | None = None
    staff: StaffIn | None = None
    subtotal: Cents
    discount: Cents = 0
    tax: Cents = 0
    tip: Cents = 0
    total: Cents
    status: TicketStatus
    fiscal_status: FiscalStatus = FiscalStatus.none
    lines: list[TicketLineIn] = Field(default_factory=list)
    payments: list[PaymentIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _closed_after_opened(self) -> TicketIn:
        if self.opened_at and self.closed_at and self.closed_at < self.opened_at:
            raise ValueError("closed_at must not be before opened_at")
        return self


class SupplierIn(Model):
    """Columns: supplier."""

    name: Text
    rfc: Text | None = None
    kind: SupplierKind


class PurchaseLineIn(Model):
    """Columns: purchase_line. unit_price_net is pesos per purchase unit."""

    description: Text
    qty: Quantity
    unit: Text
    unit_price_net: UnitPrice
    ingredient_name: Text | None = None


class PurchaseIn(Model):
    """Columns: purchase_doc (CFDI 4.0 fields in 03 C.3 are still to validate)."""

    supplier: SupplierIn
    kind: PurchaseDocKind
    cfdi_uuid: UUID | None = None
    issued_at: AwareDatetime
    subtotal: Cents
    total: Cents
    lines: list[PurchaseLineIn] = Field(default_factory=list)


class RecipeLineIn(Model):
    """PROVISIONAL: whether the "Recetas" export carries costs and yields is unverified.

    Columns: recipe_line. The ingredient is resolved by the loader.
    """

    ingredient_name: Text
    ingredient_external_id: Text | None = None
    qty_base: Quantity
    unit: Text
    yield_override_pct: PercentPoints | None = None


class RecipeIn(Model):
    """PROVISIONAL: whether the "Recetas" export carries costs and yields is unverified.

    Columns: recipe. Never applied directly: the loader turns it into a pending_change
    (09 section 3).
    """

    menu_item_external_id: Text | None = None
    menu_item_name: Text
    yield_qty: Quantity
    lines: Annotated[list[RecipeLineIn], Field(min_length=1)]


class IssueIn(Model):
    """Columns: import_issue. message_es is shown to the manager in Spanish."""

    severity: IssueSeverity
    code: Annotated[str, Field(pattern=r"^[a-z0-9_.]+$")]
    message_es: Text
    row_ref: Text | None = None


class NormalizedBatch(Model):
    """One parsed file, ready to validate and load (09 section 3)."""

    contract_version: Literal[1] = 1
    parser: Annotated[str, Field(pattern=r"^[a-z0-9_.]+@v[0-9]+$")]
    source_kind: SourceKind
    quality: BatchQuality = BatchQuality.file
    location_hint: Text | None = None
    period: Period
    grain: Grain
    totals: Totals
    menu_items: list[MenuItemIn] = Field(default_factory=list)
    item_sales: list[ItemSalesIn] = Field(default_factory=list)
    daily_sales: list[DailySalesIn] = Field(default_factory=list)
    tickets: list[TicketIn] = Field(default_factory=list)
    purchases: list[PurchaseIn] = Field(default_factory=list)
    recipes: list[RecipeIn] = Field(default_factory=list)
    issues: list[IssueIn] = Field(default_factory=list)
