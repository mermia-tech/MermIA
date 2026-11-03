"""Recipe batches become recipe.upsert pending changes (MR-25; 09 section 3).

Nothing here writes recipe or recipe_line: a person approves each change and MR-32 applies it.
For every recipe of a catalog batch:

- Dish: matched with items.find_item. A code-and-name or name match is used; a match by code
  only (another dish under that SR code) or no match holds the recipe. Menu items are never
  created, and two recipes for one dish in the same file are both held.
- Ingredients: matched by normalized name across the tenant. Two ingredients with that name hold
  the recipe; an unknown one is proposed with new_ingredient (MR-32 creates it on approval). One
  ingredient code under several names in the file is a warning.
- An ingredient another recipe produces (salsa verde) becomes a sub-recipe line, without a yield.
- The unit must be g, ml or pza and equal the ingredient's base unit; otherwise the recipe is held,
  so a line is never costed in the wrong unit. A yield override equal to the ingredient's default
  is stored as null, so a later change to the default reaches the line.
- A recipe equal to the recipe of record (same lines and yield_qty) is not proposed, nor is one
  identical to a pending proposal. Otherwise a pending_change row and its audit_log row are
  written together. Matched ids live in `diff` (the payload contract has no field for them).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from mermia_api.ingestion.items import find_item
from mermia_contracts.batch import IssueIn, NormalizedBatch, RecipeIn, RecipeLineIn
from mermia_contracts.db.models import IssueSeverity
from mermia_contracts.keys import normalize_name
from mermia_contracts.pending import (
    TARGET_TYPE,
    PendingKind,
    RecipeLine,
    RecipeUpsert,
    RecipeUpsertProposal,
)

KIND = PendingKind.recipe_upsert
BASE_UNITS = ("g", "ml", "pza")
REQUIRED_ROLE = "manager"  # MR-32 keeps it; only the owner can approve recipe.upsert in the seed
TTL = dt.timedelta(hours=24)
QTY_PLACES = Decimal("0.000001")
YIELD_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class Proposals:
    pending_change_ids: tuple[UUID, ...]
    proposed: int
    unchanged: int
    already_pending: int  # identical to a pending proposal: not filed again
    held: int
    issues: tuple[IssueIn, ...]


@dataclass(frozen=True)
class _Ingredient:
    id: UUID
    name: str
    base_unit: str
    default_yield_pct: Decimal
    sub_recipe_id: UUID | None  # the recipe of record that produces it, if any


@dataclass(frozen=True)
class _Line:
    """One recipe line, resolved against the catalog (or read from the recipe of record)."""

    key: str  # the ingredient: its id, or "new:<normalized name>"
    name: str
    external_id: str | None
    ingredient_id: UUID | None  # for a sub-recipe line, the ingredient its recipe produces
    sub_recipe_id: UUID | None
    unit: str
    qty_base: Decimal
    yield_override_pct: Decimal | None

    def same(self) -> tuple[Any, ...]:
        return (self.key, self.qty_base, self.yield_override_pct, self.sub_recipe_id is not None)

    def as_json(self) -> dict[str, Any]:
        return {
            "ingredient_name": self.name,
            "ingredient_external_id": self.external_id,
            "ingredient_id": _str(self.ingredient_id),
            "sub_recipe_id": _str(self.sub_recipe_id),
            "new_ingredient": self.ingredient_id is None,
            "qty_base": _qty(self.qty_base),
            "unit": self.unit,
            "yield_override_pct": _pct(self.yield_override_pct),
        }


@dataclass(frozen=True)
class _Dish:
    menu_item_id: UUID
    name: str
    external_id: str | None
    recipe: RecipeIn
    lines: tuple[_Line, ...]


class _Held(Exception):
    def __init__(self, issue: IssueIn) -> None:
        super().__init__(issue.message_es)
        self.issue = issue


NO_PROPOSALS = Proposals((), 0, 0, 0, 0, ())


def _str(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def _qty(value: Decimal) -> str:
    return str(value.quantize(QTY_PLACES))


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(YIELD_PLACES))


def _issue(severity: IssueSeverity, code: str, message_es: str) -> IssueIn:
    return IssueIn(severity=severity, code=code, message_es=message_es)


def _held(code: str, message_es: str) -> _Held:
    return _Held(_issue(IssueSeverity.error, code, message_es))


def propose_recipes(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    location_id: UUID,
    batch_id: UUID,
    batch: NormalizedBatch,
    proposed_by: UUID | None,
) -> Proposals:
    """Files a recipe.upsert pending change for every recipe of `batch` that differs from the
    recipe of record. Runs inside the loader's transaction."""
    day = _today(conn, location_id)
    ingredients = _ingredients(conn, tenant_id, day)
    issues = _code_name_warnings(batch.recipes)
    dishes: list[_Dish] = []
    for recipe in batch.recipes:
        try:
            dishes.append(_resolve(conn, tenant_id, location_id, recipe, ingredients))
        except _Held as e:
            issues.append(e.issue)
    per_item = Counter(d.menu_item_id for d in dishes)
    counts: Counter[str] = Counter()
    ids: list[UUID] = []
    warned: set[UUID] = set()
    for d in dishes:
        if per_item[d.menu_item_id] > 1:
            if d.menu_item_id in warned:
                continue
            warned.add(d.menu_item_id)
            issues.append(
                _held(
                    "recipe.item_repeated",
                    f"El archivo trae más de una receta para «{d.name}»; no tomé ninguna. "
                    "Envíame una sola receta por platillo.",
                ).issue
            )
            continue
        outcome, change_id = _propose(conn, tenant_id, batch_id, batch.parser, d, day, proposed_by)
        counts[outcome] += 1
        if change_id is not None:
            ids.append(change_id)
    return Proposals(
        pending_change_ids=tuple(ids),
        proposed=counts["proposed"],
        unchanged=counts["unchanged"],
        already_pending=counts["already_pending"],
        held=len(batch.recipes) - sum(counts.values()),
        issues=tuple(issues),
    )


def _today(conn: psycopg.Connection[Any], location_id: UUID) -> dt.date:
    """The location's business date: recipes are compared with the recipe in effect today."""
    row = conn.execute(
        "select (now() at time zone timezone)::date from public.location where id = %s",
        (location_id,),
    ).fetchone()
    assert row is not None and isinstance(row[0], dt.date)
    return row[0]


def _ingredients(
    conn: psycopg.Connection[Any], tenant_id: UUID, day: dt.date
) -> dict[str, list[_Ingredient]]:
    """The tenant's ingredients by normalized name (a list: two may share a name)."""
    found: dict[str, list[_Ingredient]] = {}
    for row in conn.execute(
        """select id, name, base_unit::text, default_yield_pct, app.recipe_of_record(null, id, %s)
           from public.ingredient where tenant_id = %s order by name, id""",
        (day, tenant_id),
    ).fetchall():
        ingredient = _Ingredient(row[0], row[1], row[2], row[3], row[4])
        found.setdefault(normalize_name(ingredient.name), []).append(ingredient)
    return found


def _code_name_warnings(recipes: list[RecipeIn]) -> list[IssueIn]:
    names: dict[str, dict[str, str]] = {}  # ingredient code -> normalized name -> name as given
    for recipe in recipes:
        for line in recipe.lines:
            if line.ingredient_external_id is not None:
                by_name = names.setdefault(line.ingredient_external_id, {})
                by_name.setdefault(normalize_name(line.ingredient_name), line.ingredient_name)
    return [
        _issue(
            IssueSeverity.warning,
            "recipe.ingredient_code_names",
            f"La clave de insumo {code} aparece con varios nombres: "
            f"{', '.join(f'«{n}»' for n in by_name.values())}. Tomé cada uno por su nombre; "
            "revisa que sean el insumo correcto.",
        )
        for code, by_name in names.items()
        if len(by_name) > 1
    ]


def _resolve(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    location_id: UUID,
    recipe: RecipeIn,
    ingredients: dict[str, list[_Ingredient]],
) -> _Dish:
    dish = recipe.menu_item_name
    item_id, how = find_item(conn, tenant_id, location_id, recipe.menu_item_external_id, dish)
    if item_id is None:
        raise _held(
            "recipe.item_unknown",
            f"No encontré «{dish}» en tu menú, así que no tomé su receta. Revisa que el nombre "
            "sea el mismo que en Soft Restaurant.",
        )
    if how == "code":
        raise _held(
            "recipe.item_code_mismatch",
            f"La clave {recipe.menu_item_external_id} es de otro platillo de tu menú, no de "
            f"«{dish}», así que no tomé su receta. Revisa la clave o el nombre.",
        )
    row = conn.execute(
        "select name, external_id from public.menu_item where id = %s", (item_id,)
    ).fetchone()
    assert row is not None
    lines = tuple(_resolve_line(dish, line, ingredients) for line in recipe.lines)
    repeated = [k for k, n in Counter(x.key for x in lines).items() if n > 1]
    if repeated:
        name = next(x.name for x in lines if x.key == repeated[0])
        raise _held(
            "recipe.ingredient_repeated",
            f"La receta de «{dish}» trae «{name}» más de una vez; no la tomé. Deja una sola fila "
            "por insumo.",
        )
    return _Dish(item_id, row[0], row[1], recipe, lines)


def _resolve_line(
    dish: str, line: RecipeLineIn, ingredients: dict[str, list[_Ingredient]]
) -> _Line:
    name, unit = line.ingredient_name, line.unit
    if unit not in BASE_UNITS:
        raise _held(
            "recipe.unit_unknown",
            f"En la receta de «{dish}», la unidad «{unit}» de {name} no es g, ml ni pza; no tomé "
            "la receta.",
        )
    candidates = ingredients.get(normalize_name(name), [])
    if len(candidates) > 1:
        raise _held(
            "recipe.ingredient_ambiguous",
            f"En la receta de «{dish}», tu catálogo tiene {len(candidates)} insumos llamados "
            f"«{name}» y no sé cuál es; no tomé la receta.",
        )
    if not candidates:  # decision 1: proposed as a new ingredient, created by MR-32 on approval
        return _Line(
            f"new:{normalize_name(name)}",
            name,
            line.ingredient_external_id,
            None,
            None,
            unit,
            line.qty_base,
            line.yield_override_pct,
        )
    (found,) = candidates
    if unit != found.base_unit:
        raise _held(
            "recipe.unit_mismatch",
            f"En la receta de «{dish}», {found.name} viene en {unit}, pero en tu catálogo se mide "
            f"en {found.base_unit}; no tomé la receta. Corrige la unidad.",
        )
    pct = line.yield_override_pct
    if found.sub_recipe_id is not None or pct == found.default_yield_pct:
        pct = None  # a sub-recipe's yield is in its own recipe; the default needs no override
    return _Line(
        str(found.id),
        found.name,
        line.ingredient_external_id,
        found.id,
        found.sub_recipe_id,
        unit,
        line.qty_base,
        pct,
    )


@dataclass(frozen=True)
class _Current:
    recipe_id: UUID
    recipe_version: int
    yield_qty: Decimal
    lines: tuple[_Line, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "recipe_id": str(self.recipe_id),
            "recipe_version": self.recipe_version,
            "yield_qty": _qty(self.yield_qty),
            "lines": [x.as_json() for x in self.lines],
        }


def _current(conn: psycopg.Connection[Any], menu_item_id: UUID, day: dt.date) -> _Current | None:
    """The dish's recipe of record today, with its lines."""
    row = conn.execute(
        """select r.id, r.recipe_version, coalesce(r.yield_qty, 1) from public.recipe r
           where r.id = app.recipe_of_record(%s, null, %s)""",
        (menu_item_id, day),
    ).fetchone()
    if row is None:
        return None
    lines = conn.execute(
        """select coalesce(rl.ingredient_id, sr.produces_ingredient_id), i.name, i.base_unit::text,
                  rl.sub_recipe_id, rl.qty_base, rl.yield_override_pct
           from public.recipe_line rl
           left join public.recipe sr on sr.id = rl.sub_recipe_id
           join public.ingredient i on i.id = coalesce(rl.ingredient_id, sr.produces_ingredient_id)
           where rl.recipe_id = %s
           order by rl.created_at, rl.id""",
        (row[0],),
    ).fetchall()
    return _Current(
        row[0],
        row[1],
        row[2],
        tuple(_Line(str(x[0]), x[1], None, x[0], x[3], x[2], x[4], x[5]) for x in lines),
    )


def _diff(
    batch_id: UUID, parser: str, d: _Dish, before: _Current | None, after: dict[str, Any]
) -> dict[str, Any]:
    old = {x.key: x for x in before.lines} if before else {}
    new = {x.key: x for x in d.lines}
    return {
        "batch_id": str(batch_id),
        "parser": parser,
        "menu_item": {"id": str(d.menu_item_id), "name": d.name, "external_id": d.external_id},
        "before": before.as_json() if before else None,
        "after": after,
        "added": [x.name for x in d.lines if x.key not in old],
        "removed": [x.name for x in old.values() if x.key not in new],
        "changed": [
            {
                "ingredient": x.name,
                "before": {
                    "qty_base": _qty(old[x.key].qty_base),
                    "yield_override_pct": _pct(old[x.key].yield_override_pct),
                },
                "after": {
                    "qty_base": _qty(x.qty_base),
                    "yield_override_pct": _pct(x.yield_override_pct),
                },
            }
            for x in d.lines
            if x.key in old and x.same() != old[x.key].same()
        ],
    }


def _propose(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    batch_id: UUID,
    parser: str,
    d: _Dish,
    day: dt.date,
    proposed_by: UUID | None,
) -> tuple[str, UUID | None]:
    """("unchanged" | "already_pending" | "proposed", the new pending_change id)."""
    before = _current(conn, d.menu_item_id, day)
    if (
        before is not None
        and before.yield_qty == d.recipe.yield_qty
        and sorted(x.same() for x in before.lines) == sorted(x.same() for x in d.lines)
    ):
        return "unchanged", None
    proposal = RecipeUpsertProposal(
        kind=PendingKind.recipe_upsert,
        target_id=d.menu_item_id,
        values=RecipeUpsert(
            yield_qty=d.recipe.yield_qty,
            lines=[
                RecipeLine(
                    ingredient_name=x.name,
                    ingredient_external_id=x.external_id,
                    qty_base=x.qty_base,
                    unit=x.unit,
                    yield_override_pct=x.yield_override_pct,
                )
                for x in d.lines
            ],
        ),
    )
    payload = proposal.model_dump(mode="json")
    base_version = before.recipe_version if before else None
    if conn.execute(
        """select 1 from public.pending_change
           where tenant_id = %s and kind = %s and target_id = %s and status = 'pending'
             and (expires_at is null or expires_at > now())
             and base_version is not distinct from %s and payload = %s""",
        (tenant_id, KIND.value, d.menu_item_id, base_version, Jsonb(payload)),
    ).fetchone():
        return "already_pending", None
    after = {
        "yield_qty": _qty(d.recipe.yield_qty),
        "lines": [x.as_json() for x in d.lines],
    }
    diff = _diff(batch_id, parser, d, before, after)
    row = conn.execute(
        """insert into public.pending_change
             (tenant_id, kind, target_type, target_id, base_version, payload, diff,
              proposed_by_user, proposed_via, required_role, expires_at)
           values (%s, %s, %s, %s, %s, %s, %s, %s, 'import', %s, now() + %s) returning id""",
        (
            tenant_id,
            KIND.value,
            TARGET_TYPE[KIND],
            d.menu_item_id,
            base_version,
            Jsonb(payload),
            Jsonb(diff),
            proposed_by,
            REQUIRED_ROLE,
            TTL,
        ),
    ).fetchone()
    assert row is not None
    change_id = UUID(str(row[0]))
    conn.execute(
        """insert into public.audit_log
             (tenant_id, actor_user_id, actor_kind, action, entity_type, entity_id, before, after,
              pending_change_id, batch_id)
           values (%s, %s, %s, 'pending_change.propose', %s, %s, %s, %s, %s, %s)""",
        (
            tenant_id,
            proposed_by,
            "user" if proposed_by is not None else "system",
            TARGET_TYPE[KIND],
            d.menu_item_id,
            None if before is None else Jsonb(diff["before"]),
            Jsonb(after),
            change_id,
            batch_id,
        ),
    )
    return "proposed", change_id
