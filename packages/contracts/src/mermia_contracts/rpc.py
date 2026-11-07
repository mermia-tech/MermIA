"""C3: the 11 read RPCs (09 section 4.1) and the report RPCs: arguments, response data and the
shared envelope.

Wire format follows batch.py: snake_case JSON, unknown fields are an error, money is integer
centavos, percentages are percent points. Every number the agent may quote travels twice: a raw
value for charts and code, and the text the metric layer already formatted ("$184,320.50").
RPC names are the agent tool names (agent_tools.py builds C4 from RPCS). The report RPCs
(REPORT_RPCS: build_weekly_report, MR-34) are for code, not the agent: they are not tools, so the
prompt prefix and the tool budget stay as they are. ALL_RPCS is both, for the schemas and the mock.

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


def _check_food_cost(food_cost: Pct, cost: int, net: int) -> None:
    """food_cost = cost / net x 100 on the net price (without IVA), within centavo rounding."""
    # centavo rounding of cost and net_price moves a percentage by at most this much
    slack = Decimal("50") * (1 + abs(Decimal(cost) / net)) / net + _PCT_ROUNDING
    if abs(food_cost.raw - Decimal(cost) / net * 100) > slack:
        raise ValueError("food_cost must follow cost / net_price (net, without IVA)")


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
        _check_food_cost(self.food_cost, cost, net)
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


class SuggestionRationale(StrEnum):
    """Why a dish gets this suggestion (03 "Price-suggestion formula", MR-33 decision U4)."""

    raise_to_target = "raise_to_target"
    """A plowhorse: `suggested_price` reaches the target food cost."""
    raise_capped = "raise_capped"
    """A plowhorse: `suggested_price` is the +10 % cap; reaching the target needs `target_price`."""
    review_portion_cost = "review_portion_cost"
    """A puzzle or a dog: "revisa porción/costo" before any price; no suggested price."""


_RAISES = frozenset({SuggestionRationale.raise_to_target, SuggestionRationale.raise_capped})

SUGGESTION_MAX_STEP_PCT: Final = 10
"""U4: one suggestion raises a menu price by at most 10 % (`app.price_suggestion_settings()`)."""


class PriceSuggestion(Model):
    """A menu price suggestion for a dish at a location that breaches the target (MR-33).

    Every price here is a MENU price with IVA included, the price on the menu (settles MR-11 spec
    7.2): `current_price` is the menu price today, `target_price` the lowest price that reaches the
    target food cost (to the centavo, not rounded to a price point), `suggested_price` the price
    point to propose. `change` is suggested vs current; `new_food_cost` the food cost (on the net
    price, as everywhere) at the suggested price. A review (`review_portion_cost`) has no
    suggested price, change or new food cost. `confidence` is the cost's (confirmed: fresh CFDI
    prices and confirmed recipes). Stars and resale items (bottled drinks) never appear.
    "Cambiar precios" proposes a `menu_item_price.set` pending change for `location_id`.
    """

    menu_item_id: UUID
    location_id: UUID
    name: Text
    current_price: PositiveMoney
    target_price: PositiveMoney
    suggested_price: PositiveMoney | None
    change: Pct | None
    new_food_cost: Pct | None
    confidence: CostConfidence
    rationale_code: SuggestionRationale

    @model_validator(mode="after")
    def _consistent(self) -> PriceSuggestion:
        if self.confidence is CostConfidence.missing:
            raise ValueError("a suggestion needs a cost: confidence is confirmed or estimated")
        priced = (self.suggested_price, self.change, self.new_food_cost)
        if self.rationale_code not in _RAISES:
            if any(x is not None for x in priced):
                raise ValueError("a review has no suggested price, change or new food cost")
            return self
        if self.suggested_price is None or self.change is None or self.new_food_cost is None:
            raise ValueError("a raise needs suggested_price, change and new_food_cost")
        current, suggested = self.current_price.raw, self.suggested_price.raw
        if suggested <= current:
            raise ValueError("a suggestion never lowers the price")
        if 100 * suggested > (100 + SUGGESTION_MAX_STEP_PCT) * current:
            raise ValueError(f"a suggestion raises the price at most {SUGGESTION_MAX_STEP_PCT} %")
        reaches = suggested >= self.target_price.raw
        if reaches != (self.rationale_code is SuggestionRationale.raise_to_target):
            raise ValueError("raise_to_target reaches target_price; raise_capped stays under it")
        if abs(self.change.raw - Decimal(suggested - current) / current * 100) > _PCT_ROUNDING:
            raise ValueError("change must be suggested_price vs current_price")
        return self


COST_ALERTS_TOP_N: Final = 10
"""How many price moves, breaches and suggestions get_cost_alerts lists (`cost_alerts_top_n`)."""


class CostAlertsData(Model):
    """Ingredient price moves, dishes over target and price suggestions (MR-33).

    Doc 13 keeps tool results small (top N only): `price_moves` holds the 10 largest moves (by
    size, either way; listed by start day), `breaches` and `suggestions` the 10 highest food costs;
    the `*_total` fields count every row, so the agent can say how many more there are.
    """

    price_moves: Annotated[list[PriceMove], Field(max_length=COST_ALERTS_TOP_N)]
    price_moves_total: Count
    breaches: Annotated[list[TargetBreach], Field(max_length=COST_ALERTS_TOP_N)]
    breaches_total: Count
    suggestions: Annotated[list[PriceSuggestion], Field(max_length=COST_ALERTS_TOP_N)]
    suggestions_total: Count

    @model_validator(mode="after")
    def _top_of_total(self) -> CostAlertsData:
        for rows, total in (
            (self.price_moves, self.price_moves_total),
            (self.breaches, self.breaches_total),
            (self.suggestions, self.suggestions_total),
        ):
            if len(rows) != min(total, COST_ALERTS_TOP_N):
                raise ValueError(
                    f"a list is the top {COST_ALERTS_TOP_N} of its total:"
                    f" {len(rows)} rows, total {total}"
                )
        return self


class SourceStatus(Model):
    source_kind: SourceKind
    last_batch_at: AwareDatetime | None = None


class DataStatusData(Model):
    sources: list[SourceStatus]
    missing_business_days: list[dt.date]
    stale_costs: Count
    coverage: Pct


# --- the weekly report (MR-34) ---------------------------------------------------------------

WeekName = Literal["last_week", "prev_week"]

WEEKLY_TOP_DISHES: Final = 3
"""The weekly report lists the top 3 dishes by units (W4: the template names the first)."""


def _is_week(r: DateRange) -> bool:
    return r.from_.isoweekday() == 1 and r.to == r.from_ + dt.timedelta(days=6)


class BuildWeeklyReportArgs(Model):
    """The week to report: a named past week or an explicit Monday-to-Sunday {from, to} (W2).
    The SQL also refuses a week that has not ended yet (it knows the business date)."""

    period: WeekName | DateRange = "last_week"
    location_id: UUID | None = None

    @model_validator(mode="after")
    def _monday_to_sunday(self) -> BuildWeeklyReportArgs:
        if not isinstance(self.period, str) and not _is_week(self.period):
            raise ValueError("period must run Monday to Sunday")
        return self


class WeeklyBreachAt(Model):
    """One location where a dish of `[Ver márgenes]` is over target (W4, doc 12 1b: "*Costra de
    pastor* — costo $29.80, precio $89.00 → *38.8%*", then its suggestion).

    The figures are the dish's latest snapshot of the week at `location_id`: `cost`,
    `net_price` (without IVA; `food_cost` = cost / net_price) and `price_gross` (the menu price
    with IVA that day, the one to quote), with the cost's `confidence` ("Receta estimada").
    `suggestion` is that dish's suggestion at that location (one of `CostAlertsData.suggestions`
    or a lower-ranked one) only when it is priced on these figures: the dish's latest snapshot up
    to the report day has the same cost and net price, and the suggestion's current price is
    `price_gross`. Otherwise null (a resale item, a star, a cost not evaluated yet, or a cost or
    price that moved after Sunday: that suggestion is in `suggestions` only).
    """

    location_id: UUID
    cost: Money
    net_price: PositiveMoney
    price_gross: PositiveMoney
    food_cost: Pct
    confidence: CostConfidence
    suggestion: PriceSuggestion | None

    @model_validator(mode="after")
    def _priced(self) -> WeeklyBreachAt:
        if self.net_price.raw > self.price_gross.raw:
            raise ValueError("net_price must not exceed price_gross")
        _check_food_cost(self.food_cost, self.cost.raw, self.net_price.raw)
        s = self.suggestion
        if s is not None and s.location_id != self.location_id:
            raise ValueError("a breach's suggestion is for the same dish and location")
        if s is not None and s.current_price.raw != self.price_gross.raw:
            raise ValueError("a breach's suggestion is at the breach's menu price")
        return self


class WeeklyBreach(TargetBreach):
    """A dish over target as `[Ver márgenes]` shows it: one entry in `at` per location in scope
    where the dish's latest snapshot of the week is over target, worst first (at most 10).
    `food_cost` is the worst location's, as in get_cost_alerts, so `breaches_total` still counts
    dishes. The report's only: get_cost_alerts keeps the compact TargetBreach (doc 13 budget).
    """

    at: Annotated[list[WeeklyBreachAt], Field(min_length=1, max_length=COST_ALERTS_TOP_N)]

    @model_validator(mode="after")
    def _located(self) -> WeeklyBreach:
        if self.food_cost != self.at[0].food_cost:
            raise ValueError("a breach's food_cost is its worst location's")
        costs = [e.food_cost.raw for e in self.at]
        if costs != sorted(costs, reverse=True):
            raise ValueError("a breach lists its locations worst first")
        ids = [e.location_id for e in self.at]
        if len(set(ids)) != len(ids):
            raise ValueError("a breach lists each location once")
        if any(e.food_cost.raw <= self.target.raw for e in self.at):
            raise ValueError("a breach lists only locations over target")
        if any(e.suggestion and e.suggestion.menu_item_id != self.menu_item_id for e in self.at):
            raise ValueError("a breach's suggestion is for the same dish and location")
        return self


class WeeklyCostAlerts(CostAlertsData):
    """CostAlertsData with the `[Ver márgenes]` detail on each breach (WeeklyBreach)."""

    breaches: Annotated[list[WeeklyBreach], Field(max_length=COST_ALERTS_TOP_N)]  # type: ignore[assignment]


class WeeklyReportData(Model):
    """Everything the Monday report needs, for MR-38 to render (decisions W1-W4).

    Each section is the data of the read RPC of the same shape over `week`: `sales` is
    get_sales_summary (`change_vs_previous` is vs `previous_week`, W3), `top_dishes` get_top_dishes
    by units (top 3), `food_cost` get_food_cost_pct (null when the week has no costed sales),
    `stale_costs` get_data_status today. `missing_business_days` are the days of the week on which a
    location in scope has no sales data on a day it normally opens (W2: the report goes out and
    says so; a location's closed weekdays never count). `locations` are the locations in scope
    with their names, to label a breach or a suggestion ("Centro"). The envelope carries one
    confidence flag: `cost_estimated` when any cost figure in the report is estimated, else
    `cost_confirmed`.

    `cost_alerts` is get_cost_alerts' shape (top 10 of each list; dishes over target =
    `breaches_total`) with two differences. Price moves and breaches cover the week only, Monday to
    Sunday, so a price dated after Sunday never shows and the report built at 9:00 and at 12:00
    says the same. Suggestions are as of the day the report is built (open and fresh today, at
    today's menu price), as the owner would act on them. Each breach carries, per location over
    target, its cost, prices and the suggestion priced on those figures (WeeklyBreach), so
    `[Ver márgenes]` needs no other call. Breaches are every dish over target in the week's cost
    snapshots, counted once per dish: estimated ones too (marked by each line's `confidence`), and
    ones that already existed when the restaurant joined, whatever their alerts' urgency.
    """

    week: DateRange
    previous_week: DateRange
    locations: Annotated[list[LocationRef], Field(min_length=1)]
    sales: SalesSummaryData
    top_dishes: TopDishesData
    food_cost: FoodCostData | None
    cost_alerts: WeeklyCostAlerts
    missing_business_days: list[dt.date]
    stale_costs: Count

    @model_validator(mode="after")
    def _one_week(self) -> WeeklyReportData:
        if not _is_week(self.week):
            raise ValueError("week must run Monday to Sunday")
        week_before = dt.timedelta(days=7)
        if (self.previous_week.from_, self.previous_week.to) != (
            self.week.from_ - week_before,
            self.week.to - week_before,
        ):
            raise ValueError("previous_week must be the week before week")
        if self.top_dishes.metric != "units" or len(self.top_dishes.rows) > WEEKLY_TOP_DISHES:
            raise ValueError(f"top_dishes are the top {WEEKLY_TOP_DISHES} by units")
        if any(not self.week.from_ <= d <= self.week.to for d in self.missing_business_days):
            raise ValueError("missing_business_days must fall in the week")
        if self.missing_business_days != sorted(set(self.missing_business_days)):
            raise ValueError("missing_business_days are distinct and in order")
        ids = [loc.location_id for loc in self.locations]
        if len(set(ids)) != len(ids):
            raise ValueError("locations are distinct")
        alerts = self.cost_alerts
        placed = [e.location_id for b in alerts.breaches for e in b.at] + [
            s.location_id for s in alerts.suggestions
        ]
        if not set(placed) <= set(ids):
            raise ValueError("every breach and suggestion is at a location of the report")
        return self


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

REPORT_RPCS: dict[str, RpcSpec] = {
    "build_weekly_report": RpcSpec(BuildWeeklyReportArgs, WeeklyReportData),
}
"""RPCs for code (the report jobs, the dashboard), not agent tools: kept out of RPCS."""

ALL_RPCS: Final[dict[str, RpcSpec]] = RPCS | REPORT_RPCS
"""Every SQL RPC with a contract: the schemas and the mock serve these."""
