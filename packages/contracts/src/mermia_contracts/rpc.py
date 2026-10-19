"""C3: the 11 read RPCs (09 section 4.1): arguments, response data and the shared envelope.

Wire format follows batch.py: snake_case JSON, unknown fields are an error, money is integer
centavos, percentages are percent points. Every number the agent may quote travels twice: a raw
value for charts and code, and the text the metric layer already formatted ("$184,320.50").
RPC names are the agent tool names (agent_tools.py builds C4 from RPCS).

Choices not fixed by 09 (my calls, open to change before the freeze): the `error` field and its
closed code list, `Flag` carrying only a code and a message, and the ambiguous-dish answer being
a successful response (`match="ambiguous"`).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, NamedTuple
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from mermia_contracts.batch import Cents, Count, Model, Text
from mermia_contracts.batch import Period as DateRange
from mermia_contracts.db.models import BaseUnit, CostConfidence, SourceKind
from mermia_contracts.decimals import (
    ComputedPercent,
    FigureRaw,
    PositiveCents,
    PositiveUnitPricePerBaseUnit,
)

# --- shared pieces ---------------------------------------------------------------------------

PeriodName = Literal[
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "prev_week",
    "this_month",
    "last_month",
    "last_7d",
    "last_30d",
]
PeriodArg = PeriodName | DateRange
"""A named period or an explicit {from, to} (both inclusive)."""

CompareMetric = Literal["net_sales", "tickets", "avg_ticket", "guests", "food_cost_pct", "units"]
TopMetric = Literal["units", "revenue", "margin", "margin_pct"]
BreakdownBy = Literal["payment_method", "staff", "hour", "weekday", "channel", "category"]
CancellationKind = Literal["cancellations", "discounts"]


Unit = Literal["centavos", "count", "quantity", "percent_points"]

METRIC_UNIT: Final[dict[str, Unit]] = {
    "net_sales": "centavos",
    "avg_ticket": "centavos",
    "revenue": "centavos",
    "margin": "centavos",
    "tickets": "count",
    "guests": "count",
    "units": "quantity",
    "food_cost_pct": "percent_points",
    "margin_pct": "percent_points",
}
"""The unit of `Figure.raw` for each metric of compare_* and get_top_dishes.

`count` is a whole number (tickets, guests); `quantity` is a decimal with up to six places like
`item_sales_agg.units` (numeric(18,6)), so a dish sold by the kilo can be 12.5.

An amount of money is integer centavos everywhere, so `net_sales` has the same `raw` in
get_sales_summary (a Money) and in compare_periods (a Figure).
"""


_PCT_ROUNDING = Decimal("0.0001")  # a Pct keeps four decimals
_SCALE_ROUNDING: dict[Unit, Decimal] = {
    "centavos": Decimal(1),
    "count": Decimal(0),
    "quantity": Decimal(0),
    "percent_points": _PCT_ROUNDING,
}


def _check_scale(metric: str, **figures: Figure) -> None:
    unit = METRIC_UNIT[metric]
    for name, figure in figures.items():
        raw = figure.raw
        if unit == "centavos" and raw != raw.to_integral_value():
            raise ValueError(f"{name} of {metric} must be whole centavos, got {raw}")
        if unit == "count" and raw != raw.to_integral_value():
            raise ValueError(f"{name} of {metric} must be a whole number, got {raw}")
        if unit == "percent_points" and raw != raw.quantize(Decimal("0.0001")):
            raise ValueError(f"{name} of {metric} allows four decimals at most, got {raw}")


class Money(Model):
    raw: Cents
    text: Text


class PositiveMoney(Model):
    """Money greater than zero: a price a dish is sold at."""

    raw: PositiveCents
    text: Text


class Pct(Model):
    """A calculated percentage in percent points (+7.2 is 7.2 %), not a database column."""

    raw: ComputedPercent
    text: Text


class Figure(Model):
    """A number whose unit depends on the metric asked for (compare_*, top dishes).

    The unit is not a field: it follows from `metric` through METRIC_UNIT. Money is integer
    centavos (as Money.raw), counts are whole numbers, units sold are quantities with up to six
    decimals and percentages are percent points.
    """

    raw: FigureRaw
    text: Text


class Flag(Model):
    code: Text
    message: str | None = None


class Meta(Model):
    """`period_resolved` is the one range a single-period RPC answered for (null for none, and
    for compare_periods, which carries both ranges in its data)."""

    as_of: AwareDatetime
    coverage_pct: ComputedPercent | None = None
    period_resolved: DateRange | None = None


class RpcErrorCode(StrEnum):
    invalid_args = "invalid_args"
    not_found = "not_found"
    no_data = "no_data"
    forbidden = "forbidden"
    internal = "internal"


class RpcError(Model):
    code: RpcErrorCode
    message: str


class RpcEnvelope[T](Model):
    """{ok, data, error, flags[], meta}: `ok` decides which of `data` and `error` is present."""

    ok: bool
    data: T | None = None
    error: RpcError | None = None
    flags: list[Flag] = Field(default_factory=list)
    meta: Meta

    @model_validator(mode="after")
    def _ok_matches_payload(self) -> RpcEnvelope[T]:
        if self.ok and (self.data is None or self.error is not None):
            raise ValueError("ok=true needs data and no error")
        if not self.ok and (self.error is None or self.data is not None):
            raise ValueError("ok=false needs an error and no data")
        return self


# --- arguments -------------------------------------------------------------------------------


class GetSalesSummaryArgs(Model):
    period: PeriodArg
    location_id: UUID | None = None


class ComparePeriodsArgs(Model):
    metric: CompareMetric
    period_a: PeriodArg
    period_b: PeriodArg
    location_id: UUID | None = None


class CompareLocationsArgs(Model):
    metric: CompareMetric
    period: PeriodArg
    location_ids: list[UUID] | None = None


class GetTopDishesArgs(Model):
    period: PeriodArg
    metric: TopMetric
    order: Literal["asc", "desc"] = "desc"
    limit: Annotated[int, Field(strict=True, ge=1, le=10)] = 5
    location_id: UUID | None = None
    category: Text | None = None


class GetSalesBreakdownArgs(Model):
    period: PeriodArg
    by: BreakdownBy
    location_id: UUID | None = None


class GetCancellationsArgs(Model):
    period: PeriodArg
    kind: CancellationKind = "cancellations"
    location_id: UUID | None = None


class GetDishMarginArgs(Model):
    dish: Text  # a menu item id or a fuzzy name
    location_id: UUID | None = None


class GetFoodCostPctArgs(Model):
    period: PeriodArg
    location_id: UUID | None = None
    group_by: Literal["none", "category"] = "none"


class GetMenuEngineeringArgs(Model):
    period: PeriodArg
    location_id: UUID | None = None


class GetCostAlertsArgs(Model):
    since: PeriodArg = "last_7d"
    location_id: UUID | None = None


class GetDataStatusArgs(Model):
    location_id: UUID | None = None


# --- response data ---------------------------------------------------------------------------


class SalesSummaryData(Model):
    """Every figure but `net_sales` is null when the data does not report it: not reported is not
    zero (`daily_sales_agg` and `daily_location_metrics` allow null). The keys stay required, so a
    figure that is left out is an error. A real zero is 0."""

    net_sales: Money
    tickets: Count | None
    avg_ticket: Money | None
    guests: Count | None
    discounts: Money | None
    cancellations: Money | None
    change_vs_previous: Pct | None = None


class ComparePeriodsData(Model):
    """`a` against the base period `b`: abs_change = a - b and pct_change = (a - b) / b.

    `pct_change` is null when `b` is zero: the change is undefined, never 0 or infinite.
    `period_a` and `period_b` are the exact inclusive ranges that `a` and `b` cover. The
    envelope's `meta.period_resolved` holds a single range, so for compare_periods it is null.
    """

    metric: CompareMetric
    period_a: DateRange
    period_b: DateRange
    a: Figure
    b: Figure
    abs_change: Figure
    pct_change: Pct | None = None

    @model_validator(mode="after")
    def _no_change_over_a_zero_base(self) -> ComparePeriodsData:
        if self.b.raw == 0 and self.pct_change is not None:
            raise ValueError("pct_change must be null when the base period is zero")
        return self

    @model_validator(mode="after")
    def _figures_follow_the_metric_unit(self) -> ComparePeriodsData:
        _check_scale(self.metric, a=self.a, b=self.b, abs_change=self.abs_change)
        # each figure is rounded once from unrounded values: a - b can be one unit off
        if (
            abs(self.abs_change.raw - (self.a.raw - self.b.raw))
            > _SCALE_ROUNDING[METRIC_UNIT[self.metric]]
        ):
            raise ValueError("abs_change must equal a - b (within one unit of the scale)")
        return self


class LocationValue(Model):
    location_id: UUID
    name: Text
    value: Figure
    rank: Annotated[int, Field(strict=True, ge=1)]
    diff_vs_best: Figure


class CompareLocationsData(Model):
    metric: CompareMetric
    rows: list[LocationValue]

    @model_validator(mode="after")
    def _figures_follow_the_metric_unit(self) -> CompareLocationsData:
        for row in self.rows:
            _check_scale(self.metric, value=row.value, diff_vs_best=row.diff_vs_best)
        return self


class DishValue(Model):
    rank: Annotated[int, Field(strict=True, ge=1)]
    menu_item_id: UUID
    name: Text
    value: Figure


class TopDishesData(Model):
    metric: TopMetric
    rows: Annotated[list[DishValue], Field(max_length=10)]

    @model_validator(mode="after")
    def _values_follow_the_metric_unit(self) -> TopDishesData:
        for row in self.rows:
            _check_scale(self.metric, value=row.value)
        return self


class BreakdownRow(Model):
    key: Text
    net_sales: Money
    tickets: Count | None  # null when the source has no ticket count (item-level data has none)
    share: Pct


class SalesBreakdownData(Model):
    by: BreakdownBy
    rows: list[BreakdownRow]


class NamedAmount(Model):
    name: Text  # a dish, or a staff member's first name
    count: Count
    amount: Money


class CancellationsData(Model):
    kind: CancellationKind
    count: Count
    amount: Money
    top_items: list[NamedAmount]
    by_staff: list[NamedAmount]


class CostDriver(Model):
    ingredient: Text
    share: Pct


class DishMarginResolved(Model):
    """Margin and food cost on the NET price (without IVA), the basis of 03 and 09.

    margin = net_price - cost; margin_pct = margin / net_price x 100; food_cost = cost /
    net_price x 100, so margin_pct + food_cost = 100. `price_gross` is the menu price with IVA,
    only to quote it: no percentage here is on it. Cost and prices are rounded to the centavo,
    the percentages come from the unrounded values (they agree within that rounding).
    """

    match: Literal["resolved"]
    menu_item_id: UUID
    location_id: UUID  # prices and cost snapshots are per location: the margin is for this one
    name: Text
    cost: Money
    price_gross: PositiveMoney
    net_price: PositiveMoney
    margin: Money
    margin_pct: Pct
    food_cost: Pct
    confidence: CostConfidence
    cost_drivers: Annotated[list[CostDriver], Field(max_length=3)]

    @model_validator(mode="after")
    def _on_the_net_price(self) -> DishMarginResolved:
        net, cost = self.net_price.raw, self.cost.raw
        if net > self.price_gross.raw:
            raise ValueError("net_price must not exceed price_gross")
        if self.margin.raw != net - cost:
            raise ValueError("margin must equal net_price - cost")
        if abs(self.margin_pct.raw + self.food_cost.raw - 100) > _PCT_ROUNDING:
            raise ValueError("margin_pct and food_cost must add up to 100")
        # centavo rounding of cost and net_price moves a percentage by at most this much
        slack = Decimal("50") * (1 + abs(Decimal(cost) / net)) / net + _PCT_ROUNDING
        if abs(self.food_cost.raw - Decimal(cost) / net * 100) > slack:
            raise ValueError("food_cost must follow cost / net_price (net, without IVA)")
        return self


class DishCandidate(Model):
    menu_item_id: UUID
    name: Text


class DishMarginAmbiguous(Model):
    match: Literal["ambiguous"]
    candidates: Annotated[list[DishCandidate], Field(min_length=1, max_length=5)]


class LocationRef(Model):
    location_id: UUID
    name: Text


class DishMarginNeedsLocation(Model):
    """The dish is known but prices and costs differ by location and none was asked for (or can
    be told apart). No margin is given: the caller asks again with one of `locations`."""

    match: Literal["needs_location"]
    menu_item_id: UUID
    name: Text
    locations: Annotated[list[LocationRef], Field(min_length=2)]

    @model_validator(mode="after")
    def _distinct(self) -> DishMarginNeedsLocation:
        if len({ref.location_id for ref in self.locations}) != len(self.locations):
            raise ValueError("the locations to choose from must be distinct")
        return self


DishMarginData = Annotated[
    DishMarginResolved | DishMarginAmbiguous | DishMarginNeedsLocation, Field(discriminator="match")
]


class CategoryFoodCost(Model):
    category: Text
    food_cost: Pct


class FoodCostData(Model):
    theoretical: Pct
    target: Pct | None = None
    coverage: Pct
    by_category: list[CategoryFoodCost] = Field(default_factory=list)


class Quadrant(Model):
    name: Literal["star", "plowhorse", "puzzle", "dog"]
    count: Count
    top_items: Annotated[list[Text], Field(max_length=3)]


class MenuEngineeringData(Model):
    quadrants: Annotated[list[Quadrant], Field(min_length=4, max_length=4)]


class BasePrice(Model):
    """A price per BASE unit. `raw` is pesos per `base_unit` (g, ml or pza), never per pack, as
    ingredient_price.unit_price_net stores it. `text` is the amount in the unit the owner uses,
    formatted ("$220.00/kg"): quote it, do not convert `raw`."""

    raw: PositiveUnitPricePerBaseUnit
    base_unit: BaseUnit
    text: Text


class PriceMove(Model):
    ingredient: Text
    change: Pct
    new_unit_price: BasePrice


class TargetBreach(Model):
    menu_item_id: UUID
    name: Text
    food_cost: Pct
    target: Pct


class PriceSuggestion(Model):
    """`price_suggestion` has a free-text `subject` and no dish id or current price, so
    `menu_item_id` and `current_price` are present only when the subject resolves to a dish."""

    menu_item_id: UUID | None = None
    name: Text
    current_price: Money | None = None
    suggested_price: Money


class CostAlertsData(Model):
    price_moves: list[PriceMove]
    breaches: list[TargetBreach]
    suggestions: list[PriceSuggestion]


class SourceStatus(Model):
    source_kind: SourceKind
    last_batch_at: AwareDatetime | None = None


class DataStatusData(Model):
    sources: list[SourceStatus]
    missing_business_days: list[dt.date]
    stale_costs: Count
    coverage: Pct


# --- registry --------------------------------------------------------------------------------


class RpcSpec(NamedTuple):
    args: type[Model]
    data: Any  # a model class, or the DishMarginData union


RPCS: dict[str, RpcSpec] = {
    "get_sales_summary": RpcSpec(GetSalesSummaryArgs, SalesSummaryData),
    "compare_periods": RpcSpec(ComparePeriodsArgs, ComparePeriodsData),
    "compare_locations": RpcSpec(CompareLocationsArgs, CompareLocationsData),
    "get_top_dishes": RpcSpec(GetTopDishesArgs, TopDishesData),
    "get_sales_breakdown": RpcSpec(GetSalesBreakdownArgs, SalesBreakdownData),
    "get_cancellations": RpcSpec(GetCancellationsArgs, CancellationsData),
    "get_dish_margin": RpcSpec(GetDishMarginArgs, DishMarginData),
    "get_food_cost_pct": RpcSpec(GetFoodCostPctArgs, FoodCostData),
    "get_menu_engineering": RpcSpec(GetMenuEngineeringArgs, MenuEngineeringData),
    "get_cost_alerts": RpcSpec(GetCostAlertsArgs, CostAlertsData),
    "get_data_status": RpcSpec(GetDataStatusArgs, DataStatusData),
}
