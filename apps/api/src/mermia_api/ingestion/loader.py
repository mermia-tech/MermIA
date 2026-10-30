"""Batch loader: validate a NormalizedBatch, stage its rows, apply it when clean (09 section 2.6).

Runs in the backend on a service-role connection (it writes facts, which clients cannot). The
tenant always comes from the source row, never from the caller. One call is one transaction:

1. Duplicate: the same raw file, or the same content for the same slice, returns the earlier
   batch and writes nothing ("ya lo había recibido", 09 section 2.6).
2. Checks the contract leaves to the loader (MR-10 spec 8.2, 03 B.5):
   - rejected: an unsupported grain, rows outside the period, totals that differ from the rows,
     no location, a value the database refuses;
   - needs_review: a correction of an applied slice, a period other than the expected day, a
     location hint that names another location, an error-level issue from the parser.
3. Stages the batch (status parsed / needs_review / rejected) with its issues and, unless
   rejected, its rows. New menu items and categories are created; existing ones are never
   changed by an import (the report does not know an item's kind, for example).
4. A clean batch is applied at once by app.apply_batch (the manager gets "Deshacer").
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from mermia_contracts.batch import Grain, IssueIn, NormalizedBatch
from mermia_contracts.db.models import IssueSeverity
from mermia_contracts.keys import normalize_name, slice_key

SUPPORTED = {Grain.item_daily: "item_sales", Grain.daily: "daily_sales"}
ROW_LISTS = ("menu_items", "item_sales", "daily_sales", "tickets", "purchases", "recipes")
OPEN = ("parsed", "needs_review", "applied")  # statuses a duplicate is found among
SLICE = r"^[^:]+:[^:]+:\d{4}-\d{2}-\d{2}:\d{4}-\d{2}-\d{2}$"  # as mermia_contracts.keys builds it


@dataclass(frozen=True)
class LoadResult:
    batch_id: UUID
    status: str  # applied, needs_review or rejected (or the earlier batch's, for a duplicate)
    duplicate: bool
    issues: tuple[IssueIn, ...]


def _issue(severity: IssueSeverity, code: str, message_es: str) -> IssueIn:
    return IssueIn(severity=severity, code=code, message_es=message_es)


def content_hash(batch: NormalizedBatch) -> str:
    return hashlib.sha256(batch.model_dump_json().encode()).hexdigest()


def load(
    conn: psycopg.Connection[Any],
    batch: NormalizedBatch,
    *,
    source_id: UUID,
    raw_file_id: UUID | None = None,
    expected_day: dt.date | None = None,
    auto_apply: bool = True,
) -> LoadResult:
    """Validates, stages and (when clean) applies one batch. `expected_day` is the business date a
    daily upload should cover (yesterday); None skips that check (history loads, MR-35)."""
    with conn.transaction():
        return _load(conn, batch, source_id, raw_file_id, expected_day, auto_apply)


def approve(conn: psycopg.Connection[Any], batch_id: UUID, actor_user_id: UUID) -> str:
    """A manager or owner applies a batch in needs_review (the database checks who may)."""
    with conn.transaction():
        row = conn.execute(
            "select (app.apply_batch(%s, %s)).status::text", (batch_id, actor_user_id)
        ).fetchone()
    assert row is not None
    return str(row[0])


def rollback(conn: psycopg.Connection[Any], batch_id: UUID, actor_user_id: UUID | None) -> str:
    """'Deshacer': the batch stops counting and the batch it superseded counts again."""
    with conn.transaction():
        row = conn.execute(
            "select (app.rollback_batch(%s, %s)).status::text", (batch_id, actor_user_id)
        ).fetchone()
    assert row is not None
    return str(row[0])


def _load(
    conn: psycopg.Connection[Any],
    batch: NormalizedBatch,
    source_id: UUID,
    raw_file_id: UUID | None,
    expected_day: dt.date | None,
    auto_apply: bool,
) -> LoadResult:
    src = conn.execute(
        "select tenant_id, location_id, kind::text from public.source where id = %s", (source_id,)
    ).fetchone()
    if src is None:
        raise ValueError(f"unknown source {source_id}")
    tenant_id, source_location, source_kind = src
    digest = content_hash(batch)
    issues = list(batch.issues)
    reject: list[IssueIn] = []
    review: list[IssueIn] = []

    location_id = _location(conn, tenant_id, source_location, batch.location_hint, reject, review)
    key = slice_key(location_id, batch.parser, batch.period) if location_id else None
    # one load per slice at a time: a file arriving twice at once (email and WhatsApp) must
    # meet the duplicate check, not the unique index on applied slices
    conn.execute(
        "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"{tenant_id}:{key or digest}",),
    )

    earlier = conn.execute(
        """select id, status::text from public.import_batch
           where tenant_id = %s and status::text = any(%s)
             and ((%s::uuid is not null and raw_file_id = %s)
                  or (slice_key = %s and stats ->> 'content_sha256' = %s))
           order by created_at limit 1""",
        (tenant_id, list(OPEN), raw_file_id, raw_file_id, key, digest),
    ).fetchone()
    if earlier is not None:
        return LoadResult(earlier[0], earlier[1], True, ())

    if source_kind != batch.source_kind.value:
        reject.append(
            _issue(
                IssueSeverity.error,
                "batch.source_kind",
                "El archivo no corresponde a la fuente por la que llegó.",
            )
        )
    _check_rows(batch, reject)
    # any applied batch of the same report, location and overlapping days: the views take the
    # latest applied batch per day, so this upload would replace numbers already in use
    if (
        location_id is not None
        and conn.execute(
            """select 1 from public.import_batch
               where tenant_id = %s and location_id = %s and status = 'applied'
                 and slice_key ~ %s
                 and split_part(slice_key, ':', 2) = %s
                 and split_part(slice_key, ':', 3)::date <= %s
                 and split_part(slice_key, ':', 4)::date >= %s""",
            (
                tenant_id,
                location_id,
                SLICE,
                batch.parser.split("@", 1)[0],
                batch.period.to,
                batch.period.from_,
            ),
        ).fetchone()
    ):
        review.append(
            _issue(
                IssueSeverity.warning,
                "batch.correction",
                "Ya tenía datos de este periodo: confirma que este archivo los corrige.",
            )
        )
    if expected_day is not None and (batch.period.from_, batch.period.to) != (
        expected_day,
        expected_day,
    ):
        review.append(
            _issue(
                IssueSeverity.warning,
                "period.unexpected",
                f"Esperaba el reporte del {expected_day:%d/%m/%Y} y este es del "
                f"{batch.period.from_:%d/%m/%Y} al {batch.period.to:%d/%m/%Y}.",
            )
        )
    if any(x.units < 0 or x.net < 0 for x in batch.item_sales) or any(
        d.net_sales < 0 for d in batch.daily_sales
    ):
        review.append(
            _issue(
                IssueSeverity.warning,
                "rows.negative",
                "Hay cantidades o importes negativos: confirma si son devoluciones.",
            )
        )
    if location_id is not None:
        for m in batch.menu_items:
            if _find_item(conn, tenant_id, location_id, m.external_id, m.name)[1] == "code":
                review.append(
                    _issue(
                        IssueSeverity.warning,
                        "item.code_name_mismatch",
                        f"La clave {m.external_id} ya es de otro platillo; «{m.name}» se dará "
                        "de alta aparte. Confirma que es correcto.",
                    )
                )
    if any(i.severity == IssueSeverity.error for i in batch.issues):
        review.append(
            _issue(
                IssueSeverity.warning,
                "batch.parser_errors",
                "El archivo tiene errores que conviene revisar antes de usarlo.",
            )
        )

    status = "rejected" if reject else "needs_review" if review else "parsed"
    batch_id = _insert_batch(
        conn, tenant_id, source_id, raw_file_id, location_id, key, status, batch, digest
    )
    if status != "rejected":
        try:
            with conn.transaction():  # a savepoint: a refused value rejects the batch, not the call
                _insert_rows(conn, tenant_id, location_id, source_id, batch_id, batch)
        except psycopg.errors.IntegrityError as e:
            reject.append(
                _issue(
                    IssueSeverity.error,
                    "batch.db_refused",
                    "Un valor del archivo no es válido; no lo cargué.",
                )
            )
            status = "rejected"
            conn.execute(
                """update public.import_batch set status = 'rejected', stats = stats || %s
                   where id = %s""",
                (Jsonb({"db_error": e.diag.message_primary}), batch_id),
            )
    all_issues = [*issues, *reject, *review]
    for i in all_issues:
        conn.execute(
            """insert into public.import_issue
                 (tenant_id, batch_id, severity, code, message_es, row_ref)
               values (%s, %s, %s, %s, %s, %s)""",
            (tenant_id, batch_id, i.severity.value, i.code, i.message_es, i.row_ref),
        )
    if status == "parsed" and auto_apply:
        row = conn.execute("select (app.apply_batch(%s)).status::text", (batch_id,)).fetchone()
        assert row is not None
        status = str(row[0])
    return LoadResult(batch_id, status, False, tuple(all_issues))


def _location(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    source_location: UUID | None,
    hint: str | None,
    reject: list[IssueIn],
    review: list[IssueIn],
) -> UUID | None:
    """The source's location; for a tenant-level source (email inbox), the one the hint names."""
    named = None
    if hint is not None:
        rows = conn.execute(
            "select id, name from public.location where tenant_id = %s", (tenant_id,)
        ).fetchall()
        named = next(
            (lid for lid, name in rows if normalize_name(name) == normalize_name(hint)), None
        )
    if source_location is not None:
        if hint is not None and named != source_location:
            review.append(
                _issue(
                    IssueSeverity.warning,
                    "location.mismatch",
                    f"El reporte dice «{hint}», pero llegó por la sucursal registrada "
                    "para esta fuente.",
                )
            )
        return source_location
    if named is None:
        reject.append(
            _issue(
                IssueSeverity.error, "location.unknown", "No sé de qué sucursal es este reporte."
            )
        )
    return named


def _check_rows(batch: NormalizedBatch, reject: list[IssueIn]) -> None:
    rows_name = SUPPORTED.get(batch.grain)
    if rows_name is None:
        reject.append(
            _issue(
                IssueSeverity.error,
                "batch.grain_unsupported",
                "Todavía no puedo cargar este tipo de reporte.",
            )
        )
        return
    extra = [n for n in ROW_LISTS if n not in (rows_name, "menu_items") and getattr(batch, n)]
    if extra:
        reject.append(
            _issue(
                IssueSeverity.error,
                "batch.grain_mismatch",
                "El archivo mezcla tipos de datos que no van juntos.",
            )
        )
    p = batch.period
    if batch.grain == Grain.item_daily:
        lines = len(batch.item_sales)
        net = sum(x.net for x in batch.item_sales)
        units: Decimal | None = sum((x.units for x in batch.item_sales), Decimal(0))
        outside = sum(1 for x in batch.item_sales if x.period_from < p.from_ or x.period_to > p.to)
        if any(x.period_from != x.period_to for x in batch.item_sales):
            reject.append(
                _issue(
                    IssueSeverity.error,
                    "batch.items_multi_day",
                    "Necesito los productos vendidos de un solo día por archivo; este reporte "
                    "cubre varios días.",
                )
            )
    else:
        lines = len(batch.daily_sales)
        net = sum(x.net_sales for x in batch.daily_sales)
        units = None
        outside = sum(1 for x in batch.daily_sales if not p.from_ <= x.business_date <= p.to)
    if outside:
        reject.append(
            _issue(
                IssueSeverity.error,
                "batch.rows_outside_period",
                "Hay filas con fechas fuera del periodo del reporte.",
            )
        )
    t = batch.totals
    if (
        t.lines != lines
        or (t.net_sales is not None and t.net_sales != net)
        or (t.units is not None and units is not None and t.units != units)
    ):
        reject.append(
            _issue(
                IssueSeverity.error,
                "batch.totals_mismatch",
                "Los totales del reporte no cuadran con sus renglones; no lo cargué.",
            )
        )


def _insert_batch(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    source_id: UUID,
    raw_file_id: UUID | None,
    location_id: UUID | None,
    key: str | None,
    status: str,
    batch: NormalizedBatch,
    digest: str,
) -> UUID:
    t = batch.totals
    stats = {
        "lines": t.lines,
        "net_sales": t.net_sales,
        "units": str(t.units) if t.units is not None else None,
        "content_sha256": digest,
    }
    row = conn.execute(
        """insert into public.import_batch
             (tenant_id, source_id, raw_file_id, location_id, parser, slice_key, status, stats,
              quality)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
        (
            tenant_id,
            source_id,
            raw_file_id,
            location_id,
            batch.parser,
            key or f"unsliced:{digest}",
            status,
            Jsonb(stats),
            batch.quality.value,
        ),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _insert_rows(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    location_id: UUID | None,
    source_id: UUID,
    batch_id: UUID,
    batch: NormalizedBatch,
) -> None:
    categories: dict[str, UUID] = {}
    items: dict[str, UUID] = {}
    for m in batch.menu_items:
        category_id = None
        if m.category is not None:
            if m.category not in categories:
                categories[m.category] = _category(
                    conn, tenant_id, location_id, source_id, batch_id, m.category
                )
            category_id = categories[m.category]
        found = _usable_item(conn, tenant_id, location_id, m.external_id, m.name)
        if found is None:
            row = conn.execute(
                """insert into public.menu_item
                     (tenant_id, source_id, batch_id, external_id, name, normalized_name,
                      category_id, kind)
                   values (%s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                (
                    tenant_id,
                    source_id,
                    batch_id,
                    m.external_id,
                    m.name,
                    normalize_name(m.name),
                    category_id,
                    m.kind.value,
                ),
            ).fetchone()
            assert row is not None
            found = UUID(str(row[0]))
        items[m.external_id or normalize_name(m.name)] = found

    for x in batch.item_sales:
        menu_item_id = items.get(x.item_external_id or normalize_name(x.item_name)) or _usable_item(
            conn, tenant_id, location_id, x.item_external_id, x.item_name
        )
        if menu_item_id is None:
            raise psycopg.errors.ForeignKeyViolation(
                f"item not in the batch catalog: {x.item_name}"
            )
        conn.execute(
            """insert into public.item_sales_agg
                 (tenant_id, location_id, source_id, external_id, batch_id, period_from, period_to,
                  menu_item_id, units, gross, discount, net)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                tenant_id,
                location_id,
                source_id,
                x.item_external_id,
                batch_id,
                x.period_from,
                x.period_to,
                menu_item_id,
                x.units,
                x.gross,
                x.discount,
                x.net,
            ),
        )
    for d in batch.daily_sales:
        conn.execute(
            """insert into public.daily_sales_agg
                 (tenant_id, location_id, source_id, batch_id, business_date, net_sales, tax,
                  tickets, guests, discounts, cancellations_amount, cancellations_count,
                  payment_mix, tips)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                tenant_id,
                location_id,
                source_id,
                batch_id,
                d.business_date,
                d.net_sales,
                d.tax,
                d.tickets,
                d.guests,
                d.discounts,
                d.cancellations_amount,
                d.cancellations_count,
                Jsonb({k.value: v for k, v in d.payment_mix.items()}),
                d.tips,
            ),
        )


def _category(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    location_id: UUID | None,
    source_id: UUID,
    batch_id: UUID,
    name: str,
) -> UUID:
    row = conn.execute(
        """select id from public.menu_category
           where tenant_id = %s and lower(name) = lower(%s)
             and (location_id is null or location_id = %s)
           order by location_id nulls first limit 1""",
        (tenant_id, name, location_id),
    ).fetchone()
    if row is None:
        row = conn.execute(
            """insert into public.menu_category (tenant_id, source_id, batch_id, name)
               values (%s, %s, %s, %s) returning id""",
            (tenant_id, source_id, batch_id, name),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _find_item(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    location_id: UUID | None,
    external_id: str | None,
    name: str,
) -> tuple[UUID | None, str | None]:
    """The catalog item an import line means, and how it matched: "code+name", "name", or
    "code" (same SR code, another name). SR codes are per install, so in a chain a code alone
    may be another location's dish: a "code" match is not used, the line gets its own item."""
    row = conn.execute(
        """select id, (%s::text is not null and external_id = %s),
                  normalized_name = %s
           from public.menu_item
           where tenant_id = %s and (location_id is null or location_id = %s)
             and ((%s::text is not null and external_id = %s) or normalized_name = %s)
           order by (normalized_name = %s) desc, (external_id = %s) desc nulls last,
                    location_id nulls last
           limit 1""",
        (
            external_id,
            external_id,
            normalize_name(name),
            tenant_id,
            location_id,
            external_id,
            external_id,
            normalize_name(name),
            normalize_name(name),
            external_id,
        ),
    ).fetchone()
    if row is None:
        return None, None
    by_code, by_name = bool(row[1]), bool(row[2])
    how = "code+name" if by_code and by_name else "name" if by_name else "code"
    return UUID(str(row[0])), how


def _usable_item(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    location_id: UUID | None,
    external_id: str | None,
    name: str,
) -> UUID | None:
    found, how = _find_item(conn, tenant_id, location_id, external_id, name)
    return found if how != "code" else None
