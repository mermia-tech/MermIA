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
- An unknown ingredient that comes in two units in one file holds every recipe that uses it.
- A recipe equal to the recipe of record (same lines and yield_qty) is not proposed, nor is one
  identical to a pending proposal. Otherwise a pending_change row and its audit_log row are
  written together. Matched ids live in `diff` (the payload contract has no field for them).
- The newest proposal wins: filing one expires every other pending recipe.upsert of the dish
  (resolved_via 'superseded', the schema has no such status yet) with an audit_log row.
- Recipes are tenant-wide: a change to a recipe that came from another location's file (or, when
  that cannot be traced, any change in a tenant with several locations) is a warning. A batch
  without a location (a template for the whole tenant) is matched against the shared menu, on
  Mexico City's date, and gets no such warning.
- A MermIA template is a copy of the recipes of its date: a dish whose recipe of record took
  effect after that date is held (plantilla.recipe_changed_since), so an old template never
  undoes a newer recipe. The other dishes load.
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
from mermia_api.ingestion.parsers import mermia_recetas
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
TENANT_TIMEZONE = "America/Mexico_City"  # "today" for a batch or template of the whole tenant
SUPERSEDED = "superseded"  # resolved_via of a pending change a newer proposal replaced
# the parsers' issue for a recipe they did not pass on (SR Recetas, MermIA template)
PARSER_HELD = ("sr.recipe_held", "plantilla.recipe_held")
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


def _override(pct: Decimal | None, default: Decimal, sub_recipe: bool) -> Decimal | None:
    """A sub-recipe's yield is in its own recipe; the default needs no override."""
    return None if sub_recipe or pct == default else pct


def _listed(names: list[str]) -> str:
    quoted = [f"«{n}»" for n in names]
    return quoted[0] if len(quoted) == 1 else f"{', '.join(quoted[:-1])} y {quoted[-1]}"


def propose_recipes(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    location_id: UUID | None,
    batch_id: UUID,
    batch: NormalizedBatch,
    proposed_by: UUID | None,
) -> Proposals:
    """Files a recipe.upsert pending change for every recipe of `batch` that differs from the
    recipe of record. Runs inside the loader's transaction. `location_id` is None for a batch of
    the whole tenant."""
    day = _today(conn, location_id)
    ingredients = _ingredients(conn, tenant_id, day)
    new = _new_ingredients(batch.recipes, ingredients)
    issues = _code_name_warnings(batch.recipes)
    dishes: list[_Dish] = []
    template = batch.parser == mermia_recetas.PARSER
    for recipe in batch.recipes:
        try:
            dishes.append(
                _resolve(conn, tenant_id, location_id, recipe, ingredients, new, template)
            )
        except _Held as e:
            issues.append(e.issue)
    per_item = Counter(d.menu_item_id for d in dishes)
    counts: Counter[str] = Counter()
    ids: list[UUID] = []
    warned: set[UUID] = set()
    chain: list[str] = []
    several = _locations(conn, tenant_id) > 1
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
        filed = _propose(conn, tenant_id, batch_id, batch, d, day, proposed_by)
        if filed.newer_pending is not None:
            issues.append(_newer_pending_issue(d.name, filed.newer_pending))
            continue
        if filed.changed_since is not None:
            issues.append(_changed_since_issue(d.name, filed.changed_since, batch.period.to))
            continue
        counts[filed.outcome] += 1
        if filed.replaced:
            issues.append(_replaced_note(d.name, kept_current=filed.change_id is None))
        if filed.change_id is None:
            continue
        ids.append(filed.change_id)
        if location_id is not None and filed.other_location(location_id, several):
            chain.append(d.name)
    if chain:
        issues.append(_chain_warning(chain))
    parser_held = sum(1 for i in batch.issues if i.code in PARSER_HELD)
    return Proposals(
        pending_change_ids=tuple(ids),
        proposed=counts["proposed"],
        unchanged=counts["unchanged"],
        already_pending=counts["already_pending"],
        held=len(batch.recipes) - sum(counts.values()) + parser_held,
        issues=tuple(issues),
    )


def _replaced_note(name: str, kept_current: bool) -> IssueIn:
    instead = (
        "lo descarté porque este archivo trae la receta actual."
        if kept_current
        else "lo reemplacé por el de este archivo."
    )
    return _issue(
        IssueSeverity.info,
        "recipe.pending_replaced",
        f"Ya había un cambio pendiente para la receta de «{name}»; {instead}",
    )


def _newer_pending_issue(name: str, report_date: dt.date) -> IssueIn:
    return _issue(
        IssueSeverity.warning,
        "recipe.newer_pending",
        f"Ya hay un cambio pendiente para «{name}» de un reporte más reciente "
        f"({report_date:%d/%m/%Y}); no lo reemplacé.",
    )


def _changed_since_issue(name: str, changed: dt.date, template_day: dt.date) -> IssueIn:
    return _issue(
        IssueSeverity.warning,
        "plantilla.recipe_changed_since",
        f"La receta de «{name}» cambió el {changed:%d/%m}, después de esta plantilla "
        f"({template_day:%d/%m}); descarga una plantilla nueva.",
    )


def _chain_warning(dishes: list[str]) -> IssueIn:
    return _issue(
        IssueSeverity.warning,
        "recipe.chain_location_differs",
        f"Las recetas son las mismas en todas tus sucursales: si apruebas el cambio de "
        f"{_listed(dishes)}, también cambia en las demás. La receta actual puede venir de otra "
        "sucursal; revisa que sirva para todas.",
    )


def _locations(conn: psycopg.Connection[Any], tenant_id: UUID) -> int:
    row = conn.execute(
        "select count(*) from public.location where tenant_id = %s", (tenant_id,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def _today(conn: psycopg.Connection[Any], location_id: UUID | None) -> dt.date:
    """The location's business date (Mexico City's for the whole tenant): recipes are compared
    with the recipe in effect today."""
    if location_id is None:
        row = conn.execute("select (now() at time zone %s)::date", (TENANT_TIMEZONE,)).fetchone()
    else:
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


@dataclass(frozen=True)
class _NewIngredients:
    """The batch's unknown ingredients, by normalized name."""

    clashes: dict[str, list[str]]  # the ones that come in more than one base unit, with them
    spelling: dict[str, str]  # the name as first given: every recipe proposes it under that one


def _new_ingredients(
    recipes: list[RecipeIn], ingredients: dict[str, list[_Ingredient]]
) -> _NewIngredients:
    units: dict[str, dict[str, None]] = {}  # an ordered set
    spelling: dict[str, str] = {}
    for recipe in recipes:
        for line in recipe.lines:
            key = normalize_name(line.ingredient_name)
            if key not in ingredients and line.unit in BASE_UNITS:
                units.setdefault(key, {})[line.unit] = None
                spelling.setdefault(key, line.ingredient_name)
    return _NewIngredients(
        {key: list(found) for key, found in units.items() if len(found) > 1}, spelling
    )


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
    location_id: UUID | None,
    recipe: RecipeIn,
    ingredients: dict[str, list[_Ingredient]],
    new: _NewIngredients,
    template: bool,
) -> _Dish:
    dish = recipe.menu_item_name
    item_id, how = find_item(conn, tenant_id, location_id, recipe.menu_item_external_id, dish)
    if item_id is None:
        check = (
            "Solo tomo recetas de los platillos de la lista; revisa que el nombre no haya cambiado."
            if template
            else "Revisa que el nombre sea el mismo que en Soft Restaurant."
        )
        raise _held(
            "recipe.item_unknown",
            f"No encontré «{dish}» en tu menú, así que no tomé su receta. {check}",
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
    lines = tuple(_resolve_line(dish, line, ingredients, new) for line in recipe.lines)
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
    dish: str,
    line: RecipeLineIn,
    ingredients: dict[str, list[_Ingredient]],
    new: _NewIngredients,
) -> _Line:
    name, unit = line.ingredient_name, line.unit
    if unit not in BASE_UNITS:
        raise _held(
            "recipe.unit_unknown",
            f"En la receta de «{dish}», la unidad «{unit}» de {name} no es g, ml ni pza; no tomé "
            "la receta.",
        )
    key = normalize_name(name)
    candidates = ingredients.get(key, [])
    if len(candidates) > 1:
        raise _held(
            "recipe.ingredient_ambiguous",
            f"En la receta de «{dish}», tu catálogo tiene {len(candidates)} insumos llamados "
            f"«{name}» y no sé cuál es; no tomé la receta.",
        )
    if key in new.clashes:
        units = " y ".join(new.clashes[key])
        raise _held(
            "recipe.new_ingredient_units",
            f"En la receta de «{dish}», {name} es un insumo nuevo y el archivo lo trae en {units}; "
            "no tomé la receta. Usa la misma unidad en todas las recetas que lo llevan.",
        )
    if not candidates:  # decision 1: proposed as a new ingredient, created by MR-32 on approval
        return _Line(
            f"new:{key}",
            new.spelling[key],  # one spelling for the whole batch, so one ingredient is created
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
    pct = _override(
        line.yield_override_pct, found.default_yield_pct, found.sub_recipe_id is not None
    )
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
    effective_from: dt.date | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "recipe_id": str(self.recipe_id),
            "recipe_version": self.recipe_version,
            "yield_qty": _qty(self.yield_qty),
            "lines": [x.as_json() for x in self.lines],
        }


def current_recipe(
    conn: psycopg.Connection[Any], menu_item_id: UUID, day: dt.date
) -> _Current | None:
    """The dish's recipe of record today, with its lines."""
    row = conn.execute(
        """select r.id, r.recipe_version, coalesce(r.yield_qty, 1), r.effective_from
           from public.recipe r
           where r.id = app.recipe_of_record(%s, null, %s)""",
        (menu_item_id, day),
    ).fetchone()
    if row is None:
        return None
    lines = conn.execute(
        """select coalesce(rl.ingredient_id, sr.produces_ingredient_id), i.name, i.base_unit::text,
                  rl.sub_recipe_id, rl.qty_base, rl.yield_override_pct, i.default_yield_pct
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
        tuple(
            _Line(
                str(x[0]),
                x[1],
                None,
                x[0],
                x[3],
                x[2],
                x[4],
                _override(x[5], x[6], x[3] is not None),
            )
            for x in lines
        ),
        row[3],
    )


def _match(
    before: tuple[_Line, ...], after: tuple[_Line, ...]
) -> tuple[list[_Line], list[_Line], list[tuple[_Line, _Line]]]:
    """(added, removed, changed as (before, after)), matching lines by ingredient. A stored
    recipe may list one ingredient twice: an identical stored line is paired first, and the
    other one is removed."""
    used: set[int] = set()
    added: list[_Line] = []
    changed: list[tuple[_Line, _Line]] = []
    for x in after:
        free = [i for i, o in enumerate(before) if o.key == x.key and i not in used]
        if not free:
            added.append(x)
            continue
        i = next((i for i in free if before[i].same() == x.same()), free[0])
        used.add(i)
        if before[i].same() != x.same():
            changed.append((before[i], x))
    return added, [o for i, o in enumerate(before) if i not in used], changed


def _diff(
    batch_id: UUID, batch: NormalizedBatch, d: _Dish, before: _Current | None, after: dict[str, Any]
) -> dict[str, Any]:
    added, removed, changed = _match(before.lines if before else (), d.lines)
    return {
        "batch_id": str(batch_id),
        "parser": batch.parser,
        "report_date": batch.period.to.isoformat(),  # what _newer_pending compares
        "menu_item": {"id": str(d.menu_item_id), "name": d.name, "external_id": d.external_id},
        "before": before.as_json() if before else None,
        "after": after,
        "added": [x.name for x in added],
        "removed": [x.name for x in removed],
        "changed": [
            {
                "ingredient": x.name,
                "before": {
                    "qty_base": _qty(o.qty_base),
                    "yield_override_pct": _pct(o.yield_override_pct),
                },
                "after": {
                    "qty_base": _qty(x.qty_base),
                    "yield_override_pct": _pct(x.yield_override_pct),
                },
            }
            for o, x in changed
        ],
    }


@dataclass(frozen=True)
class _Filed:
    """What _propose did with one dish."""

    outcome: str  # "unchanged" | "already_pending" | "proposed"
    change_id: UUID | None = None
    replaced: tuple[UUID | None, ...] = ()  # the superseded proposals' file locations
    origin: UUID | None = None  # the file location of the recipe of record, if traceable
    has_recipe: bool = False
    newer_pending: dt.date | None = None  # report date of a pending change that blocks this one
    changed_since: dt.date | None = None  # a template's recipe took effect after its date then

    def other_location(self, location_id: UUID, several: bool) -> bool:
        """Whether this change may undo another location's recipe (tenant-wide recipes)."""
        traced = [x for x in (*self.replaced, self.origin) if x is not None]
        if any(x != location_id for x in traced):
            return True
        return self.has_recipe and self.origin is None and several


def _propose(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    batch_id: UUID,
    batch: NormalizedBatch,
    d: _Dish,
    day: dt.date,
    proposed_by: UUID | None,
) -> _Filed:
    before = current_recipe(conn, d.menu_item_id, day)
    if (
        before is not None
        and before.yield_qty == d.recipe.yield_qty
        and Counter(x.same() for x in before.lines) == Counter(x.same() for x in d.lines)
    ):
        # The file confirms the recipe of record, so an older proposal for the dish is stale.
        if _newer_pending(conn, tenant_id, d.menu_item_id, batch.period.to) is not None:
            return _Filed("unchanged")
        replaced = _supersede(conn, tenant_id, batch_id, d.menu_item_id, None, proposed_by)
        return _Filed("unchanged", replaced=replaced)
    stale = _changed_after(before, batch) if batch.parser == mermia_recetas.PARSER else None
    if stale is not None:
        return _Filed("changed_since", changed_since=stale)
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
    newer = _newer_pending(conn, tenant_id, d.menu_item_id, batch.period.to)
    if newer is not None:
        return _Filed("newer_pending", newer_pending=newer)
    if conn.execute(
        """select 1 from public.pending_change
           where tenant_id = %s and kind = %s and target_id = %s and status = 'pending'
             and (expires_at is null or expires_at > now())
             and base_version is not distinct from %s and payload = %s""",
        (tenant_id, KIND.value, d.menu_item_id, base_version, Jsonb(payload)),
    ).fetchone():
        return _Filed("already_pending")
    after = {
        "yield_qty": _qty(d.recipe.yield_qty),
        "lines": [x.as_json() for x in d.lines],
    }
    diff = _diff(batch_id, batch, d, before, after)
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
    _audit(
        conn,
        tenant_id,
        proposed_by,
        "pending_change.propose",
        (TARGET_TYPE[KIND], d.menu_item_id),
        None if before is None else diff["before"],
        after,
        change_id,
        batch_id,
    )
    replaced = _supersede(conn, tenant_id, batch_id, d.menu_item_id, change_id, proposed_by)
    origin = _origin(conn, tenant_id, d.menu_item_id) if before is not None else None
    return _Filed("proposed", change_id, replaced, origin, before is not None)


def _changed_after(before: _Current | None, batch: NormalizedBatch) -> dt.date | None:
    """When the recipe of record took effect after the template's date (its Fecha): the
    template was filled from an older recipe, so proposing it would undo the newer one."""
    if before is None or before.effective_from is None:
        return None
    return before.effective_from if before.effective_from > batch.period.to else None


def _newer_pending(
    conn: psycopg.Connection[Any], tenant_id: UUID, menu_item_id: UUID, report_date: dt.date
) -> dt.date | None:
    """The report date of the latest live pending recipe.upsert of the dish that comes from a
    later report than `report_date` (None when there is none). The date is the end of the
    report's period, kept in the diff (a batch with no location has no dated slice_key)."""
    row = conn.execute(
        """select max((pc.diff ->> 'report_date')::date)
           from public.pending_change pc
           where pc.tenant_id = %s and pc.kind = %s and pc.target_id = %s
             and pc.status = 'pending' and (pc.expires_at is null or pc.expires_at > now())
             and (pc.diff ->> 'report_date')::date > %s""",
        (tenant_id, KIND.value, menu_item_id, report_date),
    ).fetchone()
    return None if row is None else row[0]


def _supersede(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    batch_id: UUID,
    menu_item_id: UUID,
    change_id: UUID | None,
    proposed_by: UUID | None,
) -> tuple[UUID | None, ...]:
    """The newest proposal wins: every other pending recipe.upsert of the dish expires (the
    schema has no 'superseded' status yet; resolved_via says why). `change_id` is None when the
    newest file equals the recipe of record. Gives the location of the file each one came from
    (None when it came from no file)."""
    rows = conn.execute(
        """update public.pending_change pc
           set status = 'expired', resolved_at = now(), resolved_via = %s
           where tenant_id = %s and kind = %s and target_id = %s and status = 'pending'
             and (expires_at is null or expires_at > now()) and id is distinct from %s
           returning id, (select b.location_id from public.import_batch b
                          where b.tenant_id = pc.tenant_id
                            and b.id::text = pc.diff ->> 'batch_id')""",
        (SUPERSEDED, tenant_id, KIND.value, menu_item_id, change_id),
    ).fetchall()
    for old_id, _ in rows:
        _audit(
            conn,
            tenant_id,
            proposed_by,
            "pending_change.supersede",
            ("pending_change", old_id),
            {"status": "pending"},
            {
                "status": "expired",
                "resolved_via": SUPERSEDED,
                "superseded_by": None if change_id is None else str(change_id),
            },
            old_id,
            batch_id,
        )
    return tuple(location for _, location in rows)


def _origin(conn: psycopg.Connection[Any], tenant_id: UUID, menu_item_id: UUID) -> UUID | None:
    """The location of the file the recipe of record came from: that of the last applied
    recipe.upsert of the dish (None when there is none, or it came from no file)."""
    row = conn.execute(
        """select b.location_id from public.pending_change pc
           left join public.import_batch b
             on b.tenant_id = pc.tenant_id and b.id::text = pc.diff ->> 'batch_id'
           where pc.tenant_id = %s and pc.kind = %s and pc.target_id = %s
             and pc.status = 'applied'
           order by pc.resolved_at desc nulls last, pc.created_at desc limit 1""",
        (tenant_id, KIND.value, menu_item_id),
    ).fetchone()
    return None if row is None else row[0]


def _audit(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    actor: UUID | None,
    action: str,
    entity: tuple[str, UUID],
    before: dict[str, Any] | None,
    after: dict[str, Any],
    change_id: UUID,
    batch_id: UUID,
) -> None:
    conn.execute(
        """insert into public.audit_log
             (tenant_id, actor_user_id, actor_kind, action, entity_type, entity_id, before, after,
              pending_change_id, batch_id)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            tenant_id,
            actor,
            "user" if actor is not None else "system",
            action,
            *entity,
            None if before is None else Jsonb(before),
            Jsonb(after),
            change_id,
            batch_id,
        ),
    )
