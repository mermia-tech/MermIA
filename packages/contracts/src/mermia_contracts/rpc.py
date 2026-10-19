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
from mermia_contracts.db.models import CostConfidence, SourceKind
from mermia_contracts.decimals import ComputedPercent, FigureRaw, UnitPricePerBaseUnit

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


Unit = Literal["centavos", "count", "percent_points"]

METRIC_UNIT: Final[dict[str, Unit]] = {
    "net_sales": "centavos",
    "avg_ticket": "centavos",
    "revenue": "centavos",
    "margin": "centavos",
    "tickets": "count",
    "guests": "count",
    "units": "count",
    "food_cost_pct": "percent_points",
    "margin_pct": "percent_points",
}
"""The unit of `Figure.raw` for each metric of compare_* and get_top_dishes.

An amount of money is integer centavos everywhere, so `net_sales` has the same `raw` in
get_sales_summary (a Money) and in compare_periods (a Figure).
"""


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


class Pct(Model):
    """A calculated percentage in percent points (+7.2 is 7.2 %), not a database column."""

    raw: ComputedPercent
    text: Text


class Figure(Model):
    """A number whose unit depends on the metric asked for (compare_*, top dishes).

    The unit is not a field: it follows from `metric` through METRIC_UNIT. Money is integer
    centavos (as Money.raw), counts are whole numbers and percentages are percent points.
    """

    raw: FigureRaw
    text: Text


class Flag(Model):
    code: Text
    message: str | None = None


class Meta(Model):
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
    net_sales: Money
    tickets: Count
    avg_ticket: Money
    guests: Count
    discounts: Money
    cancellations: Money
    change_vs_previous: Pct | None = None


class ComparePeriodsData(Model):
    """`a` against the base period `b`: abs_change = a - b and pct_change = (a - b) / b.

    `pct_change` is null when `b` is zero: the change is undefined, never 0 or infinite.
    """

    metric: CompareMetric
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
        if self.abs_change.raw != self.a.raw - self.b.raw:
            raise ValueError("abs_change must equal a - b")
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
    tickets: Count
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
    match: Literal["resolved"]
    menu_item_id: UUID
    name: Text
    cost: Money
    net_price: Money
    margin: Money
    food_cost: Pct
    confidence: CostConfidence
    cost_drivers: Annotated[list[CostDriver], Field(max_length=3)]


class DishCandidate(Model):
    menu_item_id: UUID
    name: Text


class DishMarginAmbiguous(Model):
    match: Literal["ambiguous"]
    candidates: Annotated[list[DishCandidate], Field(min_length=1, max_length=5)]


DishMarginData = Annotated[DishMarginResolved | DishMarginAmbiguous, Field(discriminator="match")]


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


class PriceMove(Model):
    ingredient: Text
    change: Pct
    new_unit_price: UnitPricePerBaseUnit  # per g, ml or pza of the ingredient, not per pack


class TargetBreach(Model):
    menu_item_id: UUID
    name: Text
    food_cost: Pct
    target: Pct


class PriceSuggestion(Model):
    menu_item_id: UUID
    name: Text
    current_price: Money
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
