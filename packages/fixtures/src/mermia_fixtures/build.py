"""Builds the fixture dataset: one list of rows per table, in load order.

Deterministic: ids are UUIDv5 of a stable key and the only randomness is a seeded generator,
so regenerating gives byte-identical output. Money is integer centavos; costs are computed in
exact Decimal pesos and rounded once, half away from zero (README, "Units, conversion and
rounding").

Sales are item-daily ("Productos vendidos", item_sales_agg) plus daily ("Ventas por día",
daily_sales_agg) for every location and day. A line's net is gross minus discount, IVA
included, and a day's net_sales is the sum of its item nets.
"""

from __future__ import annotations

import datetime as dt
import random
import uuid
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from mermia_fixtures import restaurant as r

Row = dict[str, Any]

NAMESPACE = uuid.UUID("6f3c1a52-2f43-4c1e-9d7b-0b6c9a1e5e10")
SEED = 20261012

PARSER_ITEMS = "sr.productos_vendidos@v1"
PARSER_DAILY = "sr.ventas_por_dia@v1"


def uid(*parts: object) -> str:
    return str(uuid.uuid5(NAMESPACE, ":".join(str(p) for p in parts)))


def cents(pesos: Decimal) -> int:
    """Pesos to centavos, half away from zero (ROUND_HALF_UP on Decimal is away from zero)."""
    return int((pesos * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def days() -> Iterator[dt.date]:
    d = r.FIRST_DAY
    while d <= r.LAST_DAY:
        yield d
        d += dt.timedelta(days=1)


def week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


# --- costing -----------------------------------------------------------------------------

INGREDIENTS = {i.key: i for i in r.INGREDIENTS}
MENU = {m.code: m for m in r.MENU}


def ingredient_price(key: str, on: dt.date) -> Decimal:
    """Pesos per purchase unit in effect on a date."""
    price = INGREDIENTS[key].price
    for k, since, new in r.PRICE_JUMPS:
        if k == key and on >= since:
            price = new
    return price


def base_unit_price(key: str, on: dt.date) -> Decimal:
    """Pesos per base unit (g, ml, pza), as stored in ingredient_price."""
    return ingredient_price(key, on) * INGREDIENTS[key].per_base


def salsa_cost_per_g(on: dt.date) -> Decimal:
    total = sum((line_cost(k, Decimal(q), on) for k, q in r.SALSA_VERDE_RECIPE), Decimal(0))
    return total / r.SALSA_VERDE_YIELD


def line_cost(key: str, qty: Decimal, on: dt.date) -> Decimal:
    """Cost in pesos of qty base units, grossed up by the ingredient's yield."""
    if key == r.SALSA_VERDE:
        return qty * salsa_cost_per_g(on)
    ing = INGREDIENTS[key]
    return qty * base_unit_price(key, on) * 100 / ing.yield_pct


def dish_cost(code: str, on: dt.date) -> int | None:
    """Cost of one unit of a menu item in centavos, or None when it has no recipe."""
    item = MENU[code]
    if not item.recipe:
        return None
    return cents(sum((line_cost(k, Decimal(q), on) for k, q in item.recipe), Decimal(0)))


def menu_price(code: str, location: r.Location) -> int:
    """Gross centavos, rounded to whole pesos as a menu would be."""
    pesos = Decimal(MENU[code].price) / 100 * location.price_factor
    return int(pesos.quantize(Decimal(1), rounding=ROUND_HALF_UP)) * 100


# --- sales -------------------------------------------------------------------------------


@dataclass
class ItemDay:
    location: str
    day: dt.date
    code: str
    units: int
    gross: int
    discount: int

    @property
    def net(self) -> int:
        return self.gross - self.discount


def _demand_scale() -> float:
    """Scales demand so an average Centro week lands near the eval's weekly figures."""
    loc = r.LOCATIONS[0]
    week = sum(m.base_units * f * menu_price(m.code, loc) for m in r.MENU for f in r.WEEKDAY_FACTOR)
    return 17_600_000 / week


def generate_sales() -> list[ItemDay]:
    """Item-daily sales for every location and day, with the target weeks exact.

    A first pass measures each target week; the second scales that week's demand to land just
    under its figure, so _calibrate only has a small gap to close.
    """
    natural = _generate({})
    week_scale = {}
    for (loc_key, monday), target in r.WEEK_TARGETS.items():
        total = sum(x.net for x in _week(natural, loc_key, monday))
        week_scale[(loc_key, monday)] = target * 0.985 / total
    rows = _generate(week_scale)
    _calibrate(rows)
    return rows


def _generate(week_scale: dict[tuple[str, dt.date], float]) -> list[ItemDay]:
    rng = random.Random(SEED)
    scale = _demand_scale()
    weeks = (r.LAST_DAY - r.FIRST_DAY).days // 7 + 1
    rows: list[ItemDay] = []
    for loc in r.LOCATIONS:
        for d in days():
            week_no = (d - r.FIRST_DAY).days // 7
            trend = 1 + 0.012 * (week_no - weeks / 2)  # slow growth over the 8 weeks
            factor = r.WEEKDAY_FACTOR[d.weekday()] * loc.unit_factor * trend * scale
            factor *= week_scale.get((loc.key, week_start(d)), 1.0)
            for m in r.MENU:
                expected = m.base_units * factor
                units = max(0, round(rng.gauss(expected, expected * 0.12)))
                price = menu_price(m.code, loc)
                gross = units * price
                discount = 0
                if d.weekday() == 1 and m.code == r.TUESDAY_PROMO[0]:
                    discount = cents(Decimal(gross) / 100 * r.TUESDAY_PROMO[1])
                rows.append(ItemDay(loc.key, d, m.code, units, gross, discount))
    return rows


def _week(rows: list[ItemDay], loc_key: str, monday: dt.date) -> list[ItemDay]:
    sunday = monday + dt.timedelta(days=6)
    return [x for x in rows if x.location == loc_key and monday <= x.day <= sunday]


def _calibrate(rows: list[ItemDay]) -> None:
    """Moves each target week onto its exact figure (13 H3 examples 1 and 2).

    The gap left by the second pass is about 1.5 %. It is closed one unit at a time, cycling
    through the week's best sellers so no single line jumps, and the last few pesos (less
    than the cheapest item) come off the Sunday pastor order as a small discount, after one
    more unit of the cheapest item steps the week just past its figure.
    """
    for (loc_key, monday), target in r.WEEK_TARGETS.items():
        week = _week(rows, loc_key, monday)
        busiest = sorted((x for x in week if x.units > 0), key=lambda x: (-x.units, x.day, x.code))
        cheapest = min(x.gross // x.units for x in busiest)
        n = 0
        while sum(x.net for x in week) > target:  # noise can still overshoot: take units back
            x = busiest[n % len(busiest)]
            if x.units > 1:
                x.gross -= x.gross // x.units
                x.units -= 1
            n += 1
        n = 0
        while target - sum(x.net for x in week) >= cheapest:
            x = busiest[n % len(busiest)]
            price = x.gross // x.units
            if price <= target - sum(y.net for y in week):
                x.units += 1
                x.gross += price
            n += 1
        if sum(x.net for x in week) < target:  # step just past it with the cheapest item
            low = min(busiest, key=lambda x: (x.gross // x.units, x.day, x.code))
            low.gross += low.gross // low.units
            low.units += 1
        sunday = monday + dt.timedelta(days=6)
        pastor = next(x for x in week if x.day == sunday and x.code == "P001")
        pastor.discount += sum(x.net for x in week) - target
        assert sum(x.net for x in week) == target


@dataclass
class Day:
    location: str
    day: dt.date
    net_sales: int
    tax: int
    tickets: int
    guests: int
    discounts: int
    cancellations_count: int
    cancellations_amount: int
    payment_mix: dict[str, int]
    tips: int


def daily_totals(items: list[ItemDay]) -> list[Day]:
    rng = random.Random(SEED + 1)
    by_day: dict[tuple[str, dt.date], list[ItemDay]] = defaultdict(list)
    for x in items:
        by_day[(x.location, x.day)].append(x)
    out: list[Day] = []
    for loc in r.LOCATIONS:
        for d in days():
            rows = by_day[(loc.key, d)]
            net = sum(x.net for x in rows)
            tax = cents(Decimal(net) / 100 * r.TAX_RATE / (1 + r.TAX_RATE))
            tickets = max(1, round(net / (loc.avg_ticket_pesos * 100) * rng.uniform(0.95, 1.05)))
            guests = round(tickets * rng.uniform(2.0, 2.4))
            if (loc.key, d) == r.CANCEL_SATURDAY:
                cancel_count, cancel_amount = 17, 289_000
            else:
                cancel_count = rng.choice((0, 0, 1, 1, 2, 3))
                cancel_amount = cancel_count * rng.randrange(4_500, 15_000, 500)
            card = cents(Decimal(net) / 100 * Decimal(str(round(rng.uniform(0.52, 0.6), 2))))
            transfer = cents(Decimal(net) / 100 * Decimal("0.07"))
            cash = net - card - transfer
            tips = cents(Decimal(card) / 100 * Decimal("0.08"))
            out.append(
                Day(
                    loc.key,
                    d,
                    net,
                    tax,
                    tickets,
                    guests,
                    sum(x.discount for x in rows),
                    cancel_count,
                    cancel_amount,
                    {"cash": cash, "card": card, "transfer": transfer},
                    tips,
                )
            )
    return out


# --- tables ------------------------------------------------------------------------------


def build() -> tuple[dict[str, list[Row]], list[ItemDay], list[Day]]:
    """All seed rows, keyed by table, in an order that satisfies the foreign keys.

    Also returns the sales it generated, so callers derive everything from one run.
    """
    t: dict[str, list[Row]] = {}
    tenant = uid("tenant")
    loc_id = {lo.key: uid("location", lo.key) for lo in r.LOCATIONS}
    owner = uid("app_user", "owner")

    t["tenant"] = [{"id": tenant, "name": r.TENANT_NAME, "rfc": "TEG190415MX2"}]
    t["location"] = [
        {
            "id": loc_id[lo.key],
            "tenant_id": tenant,
            "name": lo.name,
            "timezone": r.TIMEZONE,
            "address": lo.address,
            "sr_version": "12",
        }
        for lo in r.LOCATIONS
    ]
    t["app_user"] = [
        {"id": owner, "name": "Rodrigo", "phone_e164": "+525512345001"},
        {"id": uid("app_user", "L1"), "name": "Lupita", "phone_e164": "+525512345002"},
        {"id": uid("app_user", "L2"), "name": "Iván", "phone_e164": "+525512345003"},
    ]
    t["membership"] = [
        {
            "id": uid("membership", "owner"),
            "tenant_id": tenant,
            "user_id": owner,
            "role": "owner",
            "location_ids": None,
            "all_locations": True,
            "can_approve": [
                "ingredient_price.set",
                "recipe.upsert",
                "menu_item_price.set",
                "import_batch.approve",
                "import_batch.rollback",
            ],
        },
    ] + [
        {
            "id": uid("membership", lo.key),
            "tenant_id": tenant,
            "user_id": uid("app_user", lo.key),
            "role": "manager",
            "location_ids": [loc_id[lo.key]],
            "all_locations": False,
            "can_approve": ["import_batch.approve", "import_batch.rollback"],
        }
        for lo in r.LOCATIONS
    ]
    src = {
        (lo.key, kind): uid("source", lo.key, kind)
        for lo in r.LOCATIONS
        for kind in ("items", "daily")
    }
    t["source"] = [
        {
            "id": src[(lo.key, kind)],
            "tenant_id": tenant,
            "location_id": loc_id[lo.key],
            "kind": "sr_report",
            "config": {"report": report},
            "status": "active",
        }
        for lo in r.LOCATIONS
        for kind, report in (("items", "productos_vendidos"), ("daily", "ventas_por_dia"))
    ]

    items = generate_sales()
    days_ = daily_totals(items)

    batch: dict[tuple[str, str, dt.date], str] = {}
    t["import_batch"] = []
    for lo in r.LOCATIONS:
        for d in days():
            for kind, parser in (("items", PARSER_ITEMS), ("daily", PARSER_DAILY)):
                b = uid("import_batch", lo.key, kind, d)
                batch[(lo.key, kind, d)] = b
                lines = len(r.MENU) if kind == "items" else 1
                t["import_batch"].append(
                    {
                        "id": b,
                        "tenant_id": tenant,
                        "source_id": src[(lo.key, kind)],
                        "location_id": loc_id[lo.key],
                        "parser": parser,
                        "slice_key": f"{lo.key}:{kind}:{d.isoformat()}",
                        "status": "applied",
                        "stats": {"lines": lines},
                        "quality": "file",
                        "applied_by": owner,
                        "applied_at": f"{(d + dt.timedelta(days=1)).isoformat()}T09:00:00-06:00",
                    }
                )

    categories = sorted({m.category for m in r.MENU}, key=[m.category for m in r.MENU].index)
    cat_id = {c: uid("menu_category", c) for c in categories}
    t["menu_category"] = [{"id": cat_id[c], "tenant_id": tenant, "name": c} for c in categories]
    item_id = {m.code: uid("menu_item", m.code) for m in r.MENU}
    t["menu_item"] = [
        {
            "id": item_id[m.code],
            "tenant_id": tenant,
            "external_id": m.code,
            "name": m.name,
            "normalized_name": normalize(m.name),
            "category_id": cat_id[m.category],
            "kind": m.kind,
        }
        for m in r.MENU
    ]
    t["menu_item_price"] = [
        {
            "id": uid("menu_item_price", lo.key, m.code),
            "tenant_id": tenant,
            "location_id": loc_id[lo.key],
            "menu_item_id": item_id[m.code],
            "price_gross": menu_price(m.code, lo),
            "tax_rate": str(r.TAX_RATE.quantize(Decimal("0.0001"))),
            "effective_from": r.FIRST_DAY.isoformat(),
            "source": "manual",
        }
        for lo in r.LOCATIONS
        for m in r.MENU
    ]
    t["modifier_link"] = [
        {
            "id": uid("modifier_link", dish, mod),
            "tenant_id": tenant,
            "menu_item_id": item_id[dish],
            "modifier_item_id": item_id[mod],
            "price_delta": MENU[mod].price,
        }
        for dish, mod in r.MODIFIER_LINKS
    ]
    t["staff"] = [
        {
            "id": uid("staff", lo.key, name),
            "tenant_id": tenant,
            "location_id": loc_id[lo.key],
            "display_name": name,
            "role": "mesero",
        }
        for lo in r.LOCATIONS
        for name in lo.staff
    ]
    t["item_sales_agg"] = [
        {
            "id": uid("item_sales_agg", x.location, x.day, x.code),
            "tenant_id": tenant,
            "location_id": loc_id[x.location],
            "source_id": src[(x.location, "items")],
            "external_id": x.code,
            "batch_id": batch[(x.location, "items", x.day)],
            "period_from": x.day.isoformat(),
            "period_to": x.day.isoformat(),
            "menu_item_id": item_id[x.code],
            "units": f"{x.units}.000000",
            "gross": x.gross,
            "discount": x.discount,
            "net": x.net,
        }
        for x in items
    ]
    t["daily_sales_agg"] = [
        {
            "id": uid("daily_sales_agg", x.location, x.day),
            "tenant_id": tenant,
            "location_id": loc_id[x.location],
            "source_id": src[(x.location, "daily")],
            "batch_id": batch[(x.location, "daily", x.day)],
            "business_date": x.day.isoformat(),
            "net_sales": x.net_sales,
            "tax": x.tax,
            "tickets": x.tickets,
            "guests": x.guests,
            "discounts": x.discounts,
            "cancellations_amount": x.cancellations_amount,
            "cancellations_count": x.cancellations_count,
            "payment_mix": x.payment_mix,
            "tips": x.tips,
        }
        for x in days_
    ]

    _costing(t, tenant)
    return t, items, days_


def _costing(t: dict[str, list[Row]], tenant: str) -> None:
    sup_id = {s.key: uid("supplier", s.key) for s in r.SUPPLIERS}
    t["supplier"] = [
        {"id": sup_id[s.key], "tenant_id": tenant, "name": s.name, "rfc": s.rfc, "kind": s.kind}
        for s in r.SUPPLIERS
    ]
    ing_id = {i.key: uid("ingredient", i.key) for i in r.INGREDIENTS}
    ing_id[r.SALSA_VERDE] = uid("ingredient", r.SALSA_VERDE)
    t["ingredient"] = [
        {
            "id": ing_id[i.key],
            "tenant_id": tenant,
            "name": i.name,
            "base_unit": i.base_unit,
            "category": i.category,
            "default_yield_pct": f"{i.yield_pct:.4f}",
            "yield_source": "default" if i.yield_pct == 100 else "measured",
        }
        for i in r.INGREDIENTS
    ] + [
        {
            "id": ing_id[r.SALSA_VERDE],
            "tenant_id": tenant,
            "name": r.SALSA_VERDE_NAME,
            "base_unit": "g",
            "category": "preparados",
            "default_yield_pct": "100.0000",
            "yield_source": "default",
        }
    ]
    t["unit_conversion"] = [
        {
            "id": uid("unit_conversion", f, to),
            "tenant_id": tenant,
            "ingredient_id": None,
            "from_unit": f,
            "to_unit": to,
            "factor": "1000.0000000000",
        }
        for f, to in (("kg", "g"), ("l", "ml"))
    ]

    # One purchase document per supplier per price period, so every price has a source.
    t["purchase_doc"], t["purchase_line"], t["ingredient_price"] = [], [], []
    t["ingredient_alias"] = []
    periods: dict[str, list[tuple[dt.date, dt.date | None]]] = {}
    for i in r.INGREDIENTS:
        starts = [r.FIRST_DAY - dt.timedelta(days=16)] + [
            since for k, since, _ in r.PRICE_JUMPS if k == i.key
        ]
        periods[i.key] = [
            (s, starts[n + 1] - dt.timedelta(days=1) if n + 1 < len(starts) else None)
            for n, s in enumerate(starts)
        ]
    docs: dict[tuple[str, dt.date], list[str]] = defaultdict(list)
    for i in r.INGREDIENTS:
        for start, _ in periods[i.key]:
            docs[(i.supplier, start)].append(i.key)
    for (sup, start), keys in sorted(docs.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        supplier = next(s for s in r.SUPPLIERS if s.key == sup)
        doc = uid("purchase_doc", sup, start)
        lines = []
        for k in keys:
            ing = INGREDIENTS[k]
            qty = Decimal(10) if ing.unit != "pza" else Decimal(48)
            lines.append(
                {
                    "id": uid("purchase_line", sup, start, k),
                    "tenant_id": tenant,
                    "purchase_doc_id": doc,
                    "description": ing.name.upper(),
                    "qty": f"{qty:.6f}",
                    "unit": ing.unit.upper(),
                    "unit_price_net": f"{ingredient_price(k, start):.6f}",
                    "ingredient_id": ing_id[k],
                }
            )
        subtotal = sum(cents(Decimal(x["qty"]) * Decimal(x["unit_price_net"])) for x in lines)
        t["purchase_doc"].append(
            {
                "id": doc,
                "tenant_id": tenant,
                "supplier_id": sup_id[sup],
                "kind": "cfdi" if supplier.kind == "cfdi" else "nota_photo",
                "cfdi_uuid": uid("cfdi", sup, start).upper() if supplier.kind == "cfdi" else None,
                "issued_at": f"{start.isoformat()}T08:30:00-06:00",
                "subtotal": subtotal,
                "total": subtotal
                + (cents(Decimal(subtotal) / 100 * r.TAX_RATE) if supplier.kind == "cfdi" else 0),
            }
        )
        t["purchase_line"].extend(lines)
    for i in r.INGREDIENTS:
        t["ingredient_alias"].append(
            {
                "id": uid("ingredient_alias", i.key),
                "tenant_id": tenant,
                "supplier_id": sup_id[i.supplier],
                "source_text": i.name.upper(),
                "ingredient_id": ing_id[i.key],
            }
        )
        for start, end in periods[i.key]:
            vendor = next(s for s in r.SUPPLIERS if s.key == i.supplier)
            t["ingredient_price"].append(
                {
                    "id": uid("ingredient_price", i.key, start),
                    "tenant_id": tenant,
                    "ingredient_id": ing_id[i.key],
                    "unit_price_net": f"{base_unit_price(i.key, start):.6f}",
                    "effective_from": start.isoformat(),
                    "effective_to": end.isoformat() if end else None,
                    "source": "cfdi" if vendor.kind == "cfdi" else "nota",
                    "source_ref": uid("purchase_doc", i.supplier, start),
                    "confidence": "confirmed",
                }
            )

    item_id = {m.code: uid("menu_item", m.code) for m in r.MENU}
    t["recipe"] = [
        {
            "id": uid("recipe", r.SALSA_VERDE),
            "tenant_id": tenant,
            "produces_ingredient_id": ing_id[r.SALSA_VERDE],
            "recipe_version": 1,
            "effective_from": r.FIRST_DAY.isoformat(),
            "yield_qty": f"{r.SALSA_VERDE_YIELD:.6f}",
            "status": "confirmed",
        }
    ]
    t["recipe_line"] = [
        {
            "id": uid("recipe_line", r.SALSA_VERDE, k),
            "tenant_id": tenant,
            "recipe_id": uid("recipe", r.SALSA_VERDE),
            "ingredient_id": ing_id[k],
            "qty_base": f"{Decimal(q):.6f}",
        }
        for k, q in r.SALSA_VERDE_RECIPE
    ]
    for m in r.MENU:
        if not m.recipe:
            continue
        rec = uid("recipe", m.code)
        t["recipe"].append(
            {
                "id": rec,
                "tenant_id": tenant,
                "menu_item_id": item_id[m.code],
                "recipe_version": 1,
                "effective_from": r.FIRST_DAY.isoformat(),
                "yield_qty": "1.000000",
                "status": "confirmed",
            }
        )
        for k, q in m.recipe:
            line: Row = {
                "id": uid("recipe_line", m.code, k),
                "tenant_id": tenant,
                "recipe_id": rec,
                "qty_base": f"{Decimal(q):.6f}",
            }
            if k == r.SALSA_VERDE:
                line["sub_recipe_id"] = uid("recipe", r.SALSA_VERDE)
            else:
                line["ingredient_id"] = ing_id[k]
            t["recipe_line"].append(line)


def normalize(name: str) -> str:
    import unicodedata

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(plain.lower().replace("(", " ").replace(")", " ").split())
