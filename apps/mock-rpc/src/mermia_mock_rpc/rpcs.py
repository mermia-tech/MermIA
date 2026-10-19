"""The 11 read RPCs, answered once each from the fixture restaurant.

Every RPC has one canonical query (`CANONICAL`); the answer does not change with the request. The
answers are plain dicts in the C3 envelope, validated with the C3 models before they are sent
(app.py) and in the tests. Variants: `error` on every RPC, plus a few special cases.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from mermia_mock_rpc import data

Answer = dict[str, Any]
L1, L2 = data.LOCATIONS["L1"], data.LOCATIONS["L2"]
AS_OF = "2026-10-12T08:00:00-06:00"
FOUR = Decimal("0.0001")

# --- periods ---------------------------------------------------------------------------------


def named_period(name: str) -> tuple[dt.date, dt.date]:
    """The inclusive range of a C3 named period, relative to `data.TODAY` (a Monday)."""
    t, day = data.TODAY, dt.timedelta(days=1)
    monday = t - dt.timedelta(days=t.weekday())
    first = t.replace(day=1)
    ranges = {
        "today": (t, t),
        "yesterday": (t - day, t - day),
        "this_week": (monday, t),
        "last_week": (monday - 7 * day, monday - day),
        "prev_week": (monday - 14 * day, monday - 8 * day),
        "this_month": (first, t),
        "last_month": ((first - day).replace(day=1), first - day),
        "last_7d": (t - 7 * day, t - day),
        "last_30d": (t - 30 * day, t - day),
    }
    return ranges[name]


def _span(period: tuple[dt.date, dt.date]) -> dict[str, str]:
    return {"from": period[0].isoformat(), "to": period[1].isoformat()}


def _daily(loc: str | None, period: tuple[dt.date, dt.date]) -> list[dict[str, Any]]:
    a, b = (d.isoformat() for d in period)
    return [
        r
        for r in data.table("daily_sales_agg")
        if a <= r["business_date"] <= b and loc in (None, r["location_id"])
    ]


def _sum(loc: str | None, period: tuple[dt.date, dt.date], field: str) -> int:
    return sum(r[field] for r in _daily(loc, period))


def _coverage(loc: str | None, period: tuple[dt.date, dt.date]) -> Decimal:
    """Share of the period's business days that have a daily row (100 when none is missing)."""
    days = {r["business_date"] for r in _daily(loc, period)}
    return Decimal(100 * len(days) / ((period[1] - period[0]).days + 1)).quantize(Decimal("0.1"))


# --- pieces of a response --------------------------------------------------------------------


def money(cents: int) -> Answer:
    return {"raw": cents, "text": data.money(cents)}


def pct(value: Decimal, *, signed: bool = False) -> Answer:
    return {
        "raw": value.quantize(FOUR, rounding=ROUND_HALF_UP),
        "text": data.pct(value, signed=signed),
    }


def ratio(part: int | Decimal, whole: int | Decimal) -> Decimal:
    return Decimal(part) / Decimal(whole) * 100


def _envelope(
    body: Answer,
    *,
    period: tuple[dt.date, dt.date] | None = None,
    loc: str | None = None,
    covered: bool = True,
    flags: list[Answer] | None = None,
) -> Answer:
    meta: Answer = {"as_of": AS_OF}
    if period is not None:
        meta["period_resolved"] = _span(period)
        if covered:
            meta["coverage_pct"] = _coverage(loc, period)
    return {"ok": True, "data": body, "flags": flags or [], "meta": meta}


def _error() -> Answer:
    error = {"code": "no_data", "message": "Mock: the forced `error` variant"}
    return {"ok": False, "error": error, "flags": [], "meta": {"as_of": AS_OF}}


def _location_name(loc: str) -> str:
    return str(next(r["name"] for r in data.table("location") if r["id"] == loc))


def _item(code: str) -> dict[str, Any]:
    return next(r for r in data.table("menu_item") if r["external_id"] == code)


# --- sales -----------------------------------------------------------------------------------


def _sales_summary(loc: str, period: tuple[dt.date, dt.date], *, nulls: bool = False) -> Answer:
    net = _sum(loc, period, "net_sales")
    previous = named_period("prev_week")
    flags: list[Answer] = []
    if nulls:
        # SYNTHETIC: the fixtures report every figure on every day, so this variant blanks them.
        body: Answer = {"net_sales": money(net), "tickets": None, "avg_ticket": None}
        body |= {"guests": None, "discounts": None, "cancellations": None}
        body["change_vs_previous"] = None
        message = "Mock: synthetic variant, the fixtures have no partially reported day."
        flags.append({"code": "partial_data", "message": message})
    else:
        tickets = _sum(loc, period, "tickets")
        avg = (Decimal(net) / tickets).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        before = _sum(loc, previous, "net_sales")
        body = {
            "net_sales": money(net),
            "tickets": tickets,
            "avg_ticket": money(int(avg)),
            "guests": _sum(loc, period, "guests"),
            "discounts": money(_sum(loc, period, "discounts")),
            "cancellations": money(_sum(loc, period, "cancellations_amount")),
            "change_vs_previous": pct(ratio(net - before, before), signed=True),
        }
    return _envelope(body, period=period, loc=loc, flags=flags)


def get_sales_summary() -> Answer:
    return _sales_summary(L1, named_period("last_week"))


def get_sales_summary_nulls() -> Answer:
    return _sales_summary(L1, named_period("yesterday"), nulls=True)


def compare_periods() -> Answer:
    a, b = (
        _sum(L1, named_period("last_week"), "net_sales"),
        _sum(L1, named_period("prev_week"), "net_sales"),
    )
    body = {
        "metric": "net_sales",
        "period_a": _span(named_period("last_week")),
        "period_b": _span(named_period("prev_week")),
        "a": money(a),
        "b": money(b),
        "abs_change": money(a - b),
        "pct_change": pct(ratio(a - b, b), signed=True),
    }
    return _envelope(body)


def compare_locations() -> Answer:
    period = named_period("last_week")
    values = sorted(((_sum(loc, period, "net_sales"), loc) for loc in (L1, L2)), reverse=True)
    rows = [
        {
            "location_id": loc,
            "name": _location_name(loc),
            "value": money(value),
            "rank": rank,
            "diff_vs_best": money(value - values[0][0]),
        }
        for rank, (value, loc) in enumerate(values, start=1)
    ]
    return _envelope({"metric": "net_sales", "rows": rows}, period=period, covered=False)


def get_top_dishes() -> Answer:
    period = named_period("this_month")
    top = data.expected()["top_dishes_this_month_by_units"]["all"][:5]
    rows = [
        {
            "rank": rank,
            "menu_item_id": _item(r["code"])["id"],
            "name": r["name"],
            "value": {"raw": r["units"], "text": f"{r['units']:,}"},
        }
        for rank, r in enumerate(top, start=1)
    ]
    return _envelope({"metric": "units", "rows": rows}, period=period)


def _shares(totals: dict[str, int], *, tickets: int | None = None) -> list[Answer]:
    whole = sum(totals.values())
    ordered = sorted(totals.items(), key=lambda kv: -kv[1])
    return [
        {"key": key, "net_sales": money(v), "tickets": tickets, "share": pct(ratio(v, whole))}
        for key, v in ordered
    ]


def get_sales_breakdown() -> Answer:
    period = named_period("yesterday")
    totals: dict[str, int] = defaultdict(int)
    for row in _daily(L1, period):
        for method, amount in row["payment_mix"].items():
            totals[method] += amount
    return _envelope({"by": "payment_method", "rows": _shares(totals)}, period=period, loc=L1)


def get_sales_breakdown_no_tickets() -> Answer:
    period = named_period("yesterday")
    day = period[0].isoformat()
    category = {r["id"]: r["name"] for r in data.table("menu_category")}
    of_item = {r["id"]: category[r["category_id"]] for r in data.table("menu_item")}
    totals: dict[str, int] = defaultdict(int)
    for r in data.table("item_sales_agg"):
        if r["location_id"] == L1 and r["period_from"] == day:
            totals[of_item[r["menu_item_id"]]] += r["net"]
    return _envelope({"by": "category", "rows": _shares(totals)}, period=period, loc=L1)


def get_cancellations() -> Answer:
    period = (dt.date(2026, 10, 10), dt.date(2026, 10, 10))  # the cancellation-heavy Saturday
    day = period[0].isoformat()
    staff = {r["id"]: r["display_name"] for r in data.table("staff")}
    tickets = [
        t
        for t in data.table("sale_ticket")
        if t["location_id"] == L1 and t["business_date"] == day and t["status"] == "cancelled"
    ]
    by_staff: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for t in tickets:
        by_staff[staff[t["staff_id"]]][0] += 1
        by_staff[staff[t["staff_id"]]][1] += t["total"]
    ids = {t["id"] for t in tickets}
    name = {r["id"]: r["name"] for r in data.table("menu_item")}
    by_item: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for line in data.table("sale_line"):
        if line["ticket_id"] in ids and line["is_void"]:
            by_item[name[line["menu_item_id"]]][0] += int(Decimal(line["qty"]))
            by_item[name[line["menu_item_id"]]][1] += line["net"]

    def named(groups: dict[str, list[int]]) -> list[Answer]:
        ranked = sorted(groups.items(), key=lambda kv: -kv[1][1])[:5]
        return [{"name": n, "count": c, "amount": money(a)} for n, (c, a) in ranked]

    body = {
        "kind": "cancellations",
        "count": _sum(L1, period, "cancellations_count"),
        "amount": money(_sum(L1, period, "cancellations_amount")),
        "top_items": named(by_item),
        "by_staff": named(by_staff),
    }
    return _envelope(body, period=period, loc=L1)


# --- costs -----------------------------------------------------------------------------------


def _price(ingredient_id: str) -> dict[str, Any]:
    today = data.TODAY.isoformat()
    return next(
        p
        for p in data.table("ingredient_price")
        if p["ingredient_id"] == ingredient_id
        and p["effective_from"] <= today
        and (p["effective_to"] is None or p["effective_to"] >= today)
    )


def _line_costs(recipe: dict[str, Any], used: list[dict[str, Any]]) -> dict[str, Decimal]:
    """Pesos per ingredient of one recipe at today's prices; a sub-recipe counts as one name."""
    ingredient = {r["id"]: r for r in data.table("ingredient")}
    costs: dict[str, Decimal] = defaultdict(Decimal)
    for line in (r for r in data.table("recipe_line") if r["recipe_id"] == recipe["id"]):
        qty = Decimal(line["qty_base"])
        if "sub_recipe_id" in line:
            sub = next(r for r in data.table("recipe") if r["id"] == line["sub_recipe_id"])
            per_unit = sum(_line_costs(sub, used).values()) / Decimal(sub["yield_qty"])
            costs[ingredient[sub["produces_ingredient_id"]]["name"]] += qty * per_unit
            continue
        item = ingredient[line["ingredient_id"]]
        price = _price(item["id"])
        used.append(price)
        costs[item["name"]] += (
            qty * Decimal(price["unit_price_net"]) * 100 / Decimal(item["default_yield_pct"])
        )
    return costs


def get_dish_margin() -> Answer:
    code, item = "P001", _item("P001")  # Tacos al pastor, at Centro
    row = next(
        r
        for r in data.expected()["dish_costs_today"]
        if r["code"] == code and r["location"] == "L1"
    )
    cost, net = row["cost"], row["net_price"]
    used: list[dict[str, Any]] = []
    recipe = next(r for r in data.table("recipe") if r.get("menu_item_id") == item["id"])
    parts = _line_costs(recipe, used)
    drivers = [
        {"ingredient": name, "share": pct(ratio(v, sum(parts.values())))}
        for name, v in sorted(parts.items(), key=lambda kv: -kv[1])[:3]
    ]
    order = ["confirmed", "estimated", "missing"]
    confidence = max((p["confidence"] for p in used), key=order.index)
    food = ratio(cost, net).quantize(FOUR, rounding=ROUND_HALF_UP)
    body = {
        "match": "resolved",
        "menu_item_id": item["id"],
        "location_id": L1,
        "name": item["name"],
        "cost": money(cost),
        "price_gross": money(row["price_gross"]),
        "net_price": money(net),
        "margin": money(row["margin"]),
        "margin_pct": pct(100 - food),
        "food_cost": pct(food),
        "confidence": confidence,
        "cost_drivers": drivers,
    }
    return _envelope(body)


def get_dish_margin_ambiguous() -> Answer:
    items = [r for r in data.table("menu_item") if "pastor" in r["name"].lower()]
    candidates = [{"menu_item_id": r["id"], "name": r["name"]} for r in items][:5]
    return _envelope({"match": "ambiguous", "candidates": candidates})


def get_dish_margin_needs_location() -> Answer:
    item = _item("P001")
    locations = [{"location_id": loc, "name": _location_name(loc)} for loc in (L1, L2)]
    body = {"match": "needs_location", "menu_item_id": item["id"], "name": item["name"]}
    return _envelope(body | {"locations": locations})


def get_food_cost_pct() -> Answer:
    period = named_period("yesterday")
    day = data.expected()["food_cost_yesterday"]["L1"]
    body = {
        "theoretical": pct(ratio(day["numerator_cost"], day["denominator_net_ex_iva"])),
        "coverage": pct(ratio(day["covered_net"], day["day_net"])),
    }
    return _envelope(body, period=period, loc=L1)


def get_menu_engineering() -> Answer:
    """Kasavana-Smith (03): popular = at least 70 % of an equal share of units sold; high margin
    = contribution margin at or above the units-weighted average."""
    period = named_period("last_30d")
    a, b = (d.isoformat() for d in period)
    costed = [r for r in data.expected()["dish_costs_today"] if r["location"] == "L1"]
    units: dict[str, Decimal] = defaultdict(Decimal)
    for r in data.table("item_sales_agg"):
        if r["location_id"] == L1 and a <= r["period_from"] <= b:
            units[r["external_id"]] += Decimal(r["units"])
    sold = sum(units[r["code"]] for r in costed)
    average = sum(units[r["code"]] * (r["net_price"] - r["cost"]) for r in costed) / sold
    groups: dict[str, list[tuple[Decimal, str]]] = {
        k: [] for k in ("star", "plowhorse", "puzzle", "dog")
    }
    for r in costed:
        popular = units[r["code"]] >= Decimal("0.7") * sold / len(costed)
        high = r["net_price"] - r["cost"] >= average
        key = {(1, 1): "star", (1, 0): "plowhorse", (0, 1): "puzzle", (0, 0): "dog"}[
            (popular, high)
        ]
        groups[key].append((units[r["code"]], r["name"]))
    quadrants = [
        {"name": k, "count": len(v), "top_items": [n for _, n in sorted(v, reverse=True)[:3]]}
        for k, v in groups.items()
    ]
    return _envelope({"quadrants": quadrants}, period=period, loc=L1)


def get_cost_alerts() -> Answer:
    """Price moves only: the fixtures define no food-cost target and no price suggestion."""
    moves = []
    for jump in data.expected()["price_jumps"]:
        ingredient = next(r for r in data.table("ingredient") if r["name"] == jump["ingredient"])
        assert (jump["unit"], ingredient["base_unit"]) == ("kg", "g")
        before, after = Decimal(jump["before"]), Decimal(jump["after"])
        new_price = {"raw": after / 1000, "base_unit": "g", "text": f"${after}/kg"}
        move = {"change": pct(ratio(after - before, before), signed=True)}
        moves.append({"ingredient": ingredient["name"]} | move | {"new_unit_price": new_price})
    body = {"price_moves": moves, "breaches": [], "suggestions": []}
    return _envelope(body, period=named_period("last_30d"), covered=False)


def get_data_status() -> Answer:
    """`stale_costs` is 0: the fixtures define no rule for a stale cost."""
    kind = {r["id"]: r["kind"] for r in data.table("source")}
    last: dict[str, str] = {}
    for batch in data.table("import_batch"):
        k = kind[batch["source_id"]]
        last[k] = max(last.get(k, ""), batch["applied_at"])
    present = defaultdict(set)
    for r in data.table("daily_sales_agg"):
        present[r["location_id"]].add(r["business_date"])
    every = {
        d.isoformat()
        for d in _dates(min(min(s) for s in present.values()), data.TODAY - dt.timedelta(days=1))
    }
    missing = sorted(every - set.intersection(*present.values()))
    body = {
        "sources": [{"source_kind": k, "last_batch_at": at} for k, at in sorted(last.items())],
        "missing_business_days": missing,
        "stale_costs": 0,
        "coverage": pct(ratio(len(every) - len(missing), len(every))),
    }
    return _envelope(body)


def _dates(first: str, last: dt.date) -> list[dt.date]:
    start = dt.date.fromisoformat(first)
    return [start + dt.timedelta(days=i) for i in range((last - start).days + 1)]


# --- registry --------------------------------------------------------------------------------

CANONICAL: dict[str, Answer] = {
    "get_sales_summary": {"period": "last_week", "location_id": L1},
    "compare_periods": {
        "metric": "net_sales",
        "period_a": "last_week",
        "period_b": "prev_week",
        "location_id": L1,
    },
    "compare_locations": {"metric": "net_sales", "period": "last_week"},
    "get_top_dishes": {"period": "this_month", "metric": "units", "limit": 5},
    "get_sales_breakdown": {"period": "yesterday", "by": "payment_method", "location_id": L1},
    "get_cancellations": {"period": {"from": "2026-10-10", "to": "2026-10-10"}, "location_id": L1},
    "get_dish_margin": {"dish": "Tacos al pastor", "location_id": L1},
    "get_food_cost_pct": {"period": "yesterday", "location_id": L1},
    "get_menu_engineering": {"period": "last_30d", "location_id": L1},
    "get_cost_alerts": {"since": "last_30d"},
    "get_data_status": {},
}

ANSWERS: dict[str, Callable[[], Answer]] = {
    "get_sales_summary": get_sales_summary,
    "compare_periods": compare_periods,
    "compare_locations": compare_locations,
    "get_top_dishes": get_top_dishes,
    "get_sales_breakdown": get_sales_breakdown,
    "get_cancellations": get_cancellations,
    "get_dish_margin": get_dish_margin,
    "get_food_cost_pct": get_food_cost_pct,
    "get_menu_engineering": get_menu_engineering,
    "get_cost_alerts": get_cost_alerts,
    "get_data_status": get_data_status,
}

SPECIAL: dict[tuple[str, str], Callable[[], Answer]] = {
    ("get_sales_summary", "nulls"): get_sales_summary_nulls,
    ("get_sales_breakdown", "no_tickets"): get_sales_breakdown_no_tickets,
    ("get_dish_margin", "ambiguous"): get_dish_margin_ambiguous,
    ("get_dish_margin", "needs_location"): get_dish_margin_needs_location,
}

VARIANTS: dict[str, tuple[str, ...]] = {
    name: ("error", *(v for (n, v) in SPECIAL if n == name)) for name in ANSWERS
}


def build(name: str, variant: str | None = None) -> Answer:
    """The envelope of RPC `name`; `variant` must be one of `VARIANTS[name]` or None."""
    if variant is None:
        return ANSWERS[name]()
    if variant not in VARIANTS[name]:
        raise KeyError(variant)
    return _error() if variant == "error" else SPECIAL[(name, variant)]()
