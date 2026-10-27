"""Figures derived from the El Güero seed (fixtures/el_guero/expected.json), never from the mock."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Final

EXPECTED: Final = Path(__file__).resolve().parents[4] / "fixtures" / "el_guero" / "expected.json"


def peso(centavos: int) -> str:
    sign = "-" if centavos < 0 else ""
    q, r = divmod(abs(centavos), 100)
    return f"{sign}${q:,}.{r:02d}"


def pct_change(new: int, old: int) -> str:
    return f"{(Decimal(new - old) / old * 100):+.1f}%"


def derived_figures() -> dict[str, str]:
    d = json.loads(EXPECTED.read_text())
    out: dict[str, str] = {}
    sales = {k: {**d[k], "all": {}} for k in ("weekly_net_sales", "daily_net_sales")}
    for kind, by_loc in sales.items():
        for day in d[kind]["L1"]:  # "all": the tenant, what an RPC without location_id answers
            by_loc["all"][day] = sum(d[kind][loc][day] for loc in d[kind])
        for loc, days in by_loc.items():
            for day, centavos in days.items():
                out[f"{loc}.{kind}.{day}"] = peso(centavos)
    for loc, days in sales["daily_net_sales"].items():
        for month in {day[:7] for day in days}:
            total = sum(c for day, c in days.items() if day.startswith(month))
            out[f"{loc}.month_net_sales.{month}"] = peso(total)  # to the last day with data
    for loc, weeks in sales["weekly_net_sales"].items():
        new, old = weeks["2026-10-05"], weeks["2026-09-28"]
        out[f"{loc}.week_vs_previous.delta"] = f"{'+' if new >= old else ''}{peso(new - old)}"
        out[f"{loc}.week_vs_previous.pct"] = pct_change(new, old)
    for loc, dishes in d["top_dishes_this_month_by_units"].items():
        for dish in dishes:
            out[f"{loc}.top_units.{dish['code']}"] = f"{dish['units']:,}"
    for c in d["dish_costs_today"]:
        key = f"{c['location']}.dish.{c['code']}"
        out[f"{key}.cost"] = peso(c["cost"])
        out[f"{key}.price_gross"] = peso(c["price_gross"])
        out[f"{key}.net_price"] = peso(c["net_price"])
        out[f"{key}.margin"] = peso(c["margin"])
        out[f"{key}.margin_pct"] = f"{c['margin_pct']}%"
        out[f"{key}.food_cost_pct"] = f"{c['food_cost_pct']}%"
    for j in d["price_jumps"]:
        out[f"price_jump.{j['ingredient']}.before"] = f"${Decimal(j['before']):,.2f}"
        out[f"price_jump.{j['ingredient']}.after"] = f"${Decimal(j['after']):,.2f}"
        before, after = Decimal(j["before"]), Decimal(j["after"])
        out[f"price_jump.{j['ingredient']}.pct"] = f"{(after - before) / before * 100:+.1f}%"
    cancel = d["cancellation_saturday"]
    out["cancellation_saturday.count"] = str(cancel["count"])
    out["cancellation_saturday.amount"] = peso(cancel["amount"])
    for waiter, n in cancel["by_waiter"].items():
        out[f"cancellation_saturday.{waiter}"] = str(n)
    fc = d["food_cost_yesterday"]
    for loc in ("L1", "L2"):
        if loc in fc:
            out[f"{loc}.food_cost_yesterday.pct"] = f"{fc[loc]['pct']}%"
            out[f"{loc}.food_cost_yesterday.coverage_pct"] = f"{fc[loc]['coverage_pct']}%"
            out[f"{loc}.food_cost_yesterday.numerator_cost"] = peso(fc[loc]["numerator_cost"])
    return out
