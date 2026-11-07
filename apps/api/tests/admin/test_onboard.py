"""MR-30: onboarding a tenant on the local database, and what its users then see under RLS.

Each test runs in one transaction that is rolled back, on the postgres connection the script
uses. Needs MERMIA_DB_URL and the seed (supabase db start / db reset load it). The RLS checks
compute the claims from `membership` the way the issuer will (MR-10 spec 7.5.5) and read as
`authenticated`, like the pgTAP tests.
"""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest

from mermia_api.admin import cli
from mermia_api.admin.onboard import OnboardingError, Summary, onboard
from mermia_api.admin.spec import OnboardingSpec

pytestmark = pytest.mark.db

EL_GUERO = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")
EL_GUERO_CENTRO = "705e8e51-376b-5785-adbb-405eff4e2a22"
RODRIGO_PHONE = "+525512345001"  # El Güero's owner in the seed
OPERATOR = "test-operator"

SPEC: dict[str, Any] = {
    "tenant": {"name": "Taquería La Prueba", "rfc": "TLP200101AB1"},
    "locations": [
        {"name": "Centro", "address": "Calle 1"},
        {"name": "Roma", "sr_version": "11"},
    ],
    "users": [
        {"name": "Rosa", "phone": "+525500000001", "role": "owner", "email": "rosa@example.com"},
        {"name": "Beto", "phone": "+525500000002", "role": "manager", "locations": ["Roma"]},
        {"name": "Ana", "phone": "+525500000003", "role": "admin"},
    ],
}


def make(**over: Any) -> OnboardingSpec:
    return OnboardingSpec.model_validate({**SPEC, **over})


def again(first: Summary, **over: Any) -> OnboardingSpec:
    """The spec of a rerun: the tenant pinned by the id the first run printed."""
    return make(tenant={**SPEC["tenant"], "id": str(first.tenant_id)}, **over)


def apply(conn: psycopg.Connection[Any], spec: OnboardingSpec) -> Summary:
    return onboard(conn, spec, operator=OPERATOR)


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    return url


@pytest.fixture
def conn(db_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(db_url) as c, c.transaction(force_rollback=True):
        yield c


def actions(summary: Summary) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in summary.changes:
        out[c.action] = out.get(c.action, 0) + 1
    return out


def one(conn: psycopg.Connection[Any], sql: str, *args: Any) -> Any:
    row = conn.execute(sql, args).fetchone()
    assert row is not None
    return row[0]


def user_id(conn: psycopg.Connection[Any], phone: str) -> UUID:
    return one(conn, "select id from public.app_user where phone_e164 = %s", phone)  # type: ignore[no-any-return]


@contextmanager
def as_member(conn: psycopg.Connection[Any], tenant: UUID, phone: str) -> Iterator[None]:
    """Reads as `authenticated` with the claims an issuer derives from the membership."""
    row = conn.execute(
        """select m.role::text, m.all_locations, m.location_ids from public.membership m
           join public.app_user u on u.id = m.user_id
           where m.tenant_id = %s and u.phone_e164 = %s""",
        (tenant, phone),
    ).fetchone()
    assert row is not None
    role, all_locations, location_ids = row
    claims = {
        "role": "authenticated",
        "tenant_id": str(tenant),
        "app_role": role,
        "location_ids": None if all_locations else [str(x) for x in location_ids],
    }
    conn.execute("set local role authenticated")
    conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))
    try:
        yield
    finally:
        conn.execute("reset role")
        conn.execute("select set_config('request.jwt.claims', '', true)")


def test_onboard_creates_the_tenant_locations_users_and_sources(
    conn: psycopg.Connection[Any],
) -> None:
    s = apply(conn, make())
    t = s.tenant_id
    assert one(conn, "select name from public.tenant where id = %s", t) == "Taquería La Prueba"
    locs = dict(conn.execute("select name, id from public.location where tenant_id = %s", (t,)))
    assert set(locs) == {"Centro", "Roma"}
    assert one(conn, "select address from public.location where id = %s", locs["Centro"]) == (
        "Calle 1"
    )
    rows = conn.execute(
        """select u.name, m.role::text, m.all_locations, m.location_ids, m.can_approve
           from public.membership m join public.app_user u on u.id = m.user_id
           where m.tenant_id = %s order by u.name""",
        (t,),
    ).fetchall()
    assert rows == [
        ("Ana", "admin", True, None, ["ingredient_price.set", "menu_item_price.set"]),
        ("Beto", "manager", False, [locs["Roma"]],
         ["import_batch.approve", "import_batch.rollback"]),
        ("Rosa", "owner", True, None, [
            "ingredient_price.set", "recipe.upsert", "menu_item_price.set",
            "import_batch.approve", "import_batch.rollback",
        ]),
    ]  # fmt: skip
    sources = conn.execute(
        "select location_id, kind::text, status from public.source where tenant_id = %s", (t,)
    ).fetchall()
    assert sorted((str(lo), k, st) for lo, k, st in sources) == sorted(
        (str(lo), k, "active") for lo in locs.values() for k in ("sr_report", "manual")
    )
    assert actions(s) == {"created": 1 + 2 + 4 + 3 * 3}  # tenant, locations, sources, 3 per user


def test_the_whatsapp_identity_is_verified_and_keyed_by_wa_id(
    conn: psycopg.Connection[Any],
) -> None:
    apply(conn, make())
    row = conn.execute(
        """select ci.channel::text, ci.external_id, ci.verified_at is not null
           from public.channel_identity ci where ci.user_id = %s""",
        (user_id(conn, "+525500000002"),),
    ).fetchall()
    assert row == [("whatsapp", "525500000002", True)]


def test_a_whatsapp_linked_to_another_user_is_refused(conn: psycopg.Connection[Any]) -> None:
    other = one(
        conn,
        """insert into public.app_user (name, phone_e164) values ('Otro', '+525599990010')
           returning id""",
    )
    conn.execute(
        """insert into public.channel_identity (user_id, channel, external_id, verified_at)
           values (%s, 'whatsapp', '525500000001', now())""",
        (other,),
    )
    with pytest.raises(OnboardingError, match=r"WhatsApp \+52\*{6}0001 is linked to another user"):
        apply(conn, make())
    owner = "select user_id from public.channel_identity where external_id = '525500000001'"
    assert one(conn, owner) == other


def test_a_rerun_verifies_an_unverified_whatsapp_and_audits_it(
    conn: psycopg.Connection[Any],
) -> None:
    first = apply(conn, make())
    rosa = user_id(conn, "+525500000001")
    conn.execute(
        "update public.channel_identity set verified_at = null where user_id = %s", (rosa,)
    )
    s = apply(conn, again(first))
    assert ("whatsapp", "Rosa", "updated") in {(c.entity, c.label, c.action) for c in s.changes}
    verified = "select verified_at is not null from public.channel_identity where user_id = %s"
    assert one(conn, verified, rosa)
    rows = conn.execute(
        """select before::text, after::text from public.audit_log
           where tenant_id = %s and entity_type = 'channel_identity' and action like '%%update'""",
        (first.tenant_id,),
    ).fetchall()
    assert len(rows) == 1 and "5500000" not in rows[0][0] + rows[0][1], rows


def test_a_rerun_creates_nothing_and_audits_nothing(conn: psycopg.Connection[Any]) -> None:
    first = apply(conn, make())
    audit = one(conn, "select count(*) from public.audit_log where tenant_id = %s", first.tenant_id)
    counts = [
        one(conn, f"select count(*) from public.{table}")
        for table in ("tenant", "location", "app_user", "membership", "channel_identity", "source")
    ]
    second = apply(conn, again(first))
    assert second.tenant_id == first.tenant_id
    assert actions(second) == {"unchanged": len(first.changes)}
    assert counts == [
        one(conn, f"select count(*) from public.{table}")
        for table in ("tenant", "location", "app_user", "membership", "channel_identity", "source")
    ]
    assert audit == one(
        conn, "select count(*) from public.audit_log where tenant_id = %s", first.tenant_id
    )


def test_every_created_row_is_audited_without_phone_numbers(
    conn: psycopg.Connection[Any],
) -> None:
    s = apply(conn, make())
    rows = conn.execute(
        """select action, entity_type, actor_kind::text, request_id, after::text
           from public.audit_log where tenant_id = %s""",
        (s.tenant_id,),
    ).fetchall()
    assert len(rows) == len(s.changes) == s.audit_rows
    assert {r[2] for r in rows} == {"system"}
    assert {r[3] for r in rows} == {f"mermia_api.admin:{OPERATOR}:{s.run_id}"}
    assert ("admin.tenant.create", "tenant") in {(r[0], r[1]) for r in rows}
    assert not any("5500000" in r[4] for r in rows), "no phone or wa_id in the audit trail"


def test_a_changed_spec_updates_in_place(conn: psycopg.Connection[Any]) -> None:
    first = apply(conn, make())
    users = [
        SPEC["users"][0],
        {**SPEC["users"][1], "locations": ["Centro", "Roma"], "name": "BETO"},
        {**SPEC["users"][2], "role": "manager", "locations": ["Centro"]},
    ]
    locations = [{**SPEC["locations"][0], "address": "Calle 2"}, SPEC["locations"][1]]
    second = apply(conn, again(first, users=users, locations=locations))
    assert second.tenant_id == first.tenant_id
    updated = {(c.entity, c.label) for c in second.changes if c.action == "updated"}
    assert updated == {
        ("location", "Centro"),
        ("user", "BETO"),
        ("membership", "BETO"),
        ("membership", "Ana"),
    }
    beto = user_id(conn, "+525500000002")
    assert one(conn, "select name from public.app_user where id = %s", beto) == "BETO"
    scope = one(
        conn,
        "select cardinality(location_ids) from public.membership where user_id = %s",
        beto,
    )
    assert scope == 2
    assert one(
        conn,
        "select count(*) from public.audit_log where tenant_id = %s and action like '%%update'",
        first.tenant_id,
    ) == len(updated)


def test_a_member_left_out_of_the_spec_is_kept_and_reported(
    conn: psycopg.Connection[Any],
) -> None:
    first = apply(conn, make())
    s = apply(conn, again(first, users=SPEC["users"][:1]))
    assert any("Beto" in n and "keeps their access" in n for n in s.notes), s.notes
    assert (
        one(conn, "select count(*) from public.membership where tenant_id = %s", s.tenant_id) == 3
    )


def test_a_rerun_without_the_tenant_id_is_refused(conn: psycopg.Connection[Any]) -> None:
    first = apply(conn, make())
    hint = f"add tenant.id: {first.tenant_id}"
    assert hint in cli.render(first, "db", dry_run=False)
    assert hint not in cli.render(first, "db", dry_run=True), "a dry run's id is discarded"
    with pytest.raises(OnboardingError, match=f"already exists.*{first.tenant_id}"):
        apply(conn, make(tenant={"name": "taqueria la prueba"}))


def test_a_new_restaurant_named_like_an_existing_tenant_is_refused(
    conn: psycopg.Connection[Any],
) -> None:
    """Skeptic probe h1.yaml: a name match must not hand El Güero to a stranger."""
    spec = OnboardingSpec.model_validate(
        {
            "tenant": {"name": "TAQUERIA el guero", "rfc": "XYZ200101AB1"},
            "locations": [{"name": "Sucursal Nueva"}],
            "users": [{"name": "Extraño", "phone": "+525599990001", "role": "owner"}],
        }
    )
    with pytest.raises(OnboardingError, match="already exists"):
        apply(conn, spec)
    assert one(conn, "select rfc from public.tenant where id = %s", EL_GUERO) == "TEG190415MX2"
    assert one(conn, "select count(*) from public.membership where tenant_id = %s", EL_GUERO) == 3


def test_a_pinned_id_renames_the_tenant(conn: psycopg.Connection[Any]) -> None:
    first = apply(conn, make())
    renamed = apply(conn, make(tenant={"id": str(first.tenant_id), "name": "La Prueba 2"}))
    assert renamed.tenant_id == first.tenant_id
    assert one(conn, "select name from public.tenant where id = %s", first.tenant_id) == (
        "La Prueba 2"
    )


def test_a_pinned_id_that_does_not_exist_is_refused(conn: psycopg.Connection[Any]) -> None:
    with pytest.raises(OnboardingError, match="no tenant with id"):
        apply(conn, make(tenant={"id": "0193f000-0000-7000-8000-000000000000", "name": "X"}))


def test_two_tenants_with_the_same_name_need_a_pinned_id(conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        "insert into public.tenant (name) values ('Taquería La Prueba'), ('TAQUERIA LA PRUEBA')"
    )
    with pytest.raises(OnboardingError, match="already exists"):
        apply(conn, make())


def test_a_phone_of_another_tenants_user_with_another_name_is_refused(
    conn: psycopg.Connection[Any],
) -> None:
    users = [{"name": "Rosa", "phone": RODRIGO_PHONE, "role": "owner"}]
    with pytest.raises(OnboardingError, match=r"\+52\*{6}5001 already belongs to"):
        apply(conn, make(users=users))
    assert one(conn, "select name from public.app_user where phone_e164 = %s", RODRIGO_PHONE) == (
        "Rodrigo"
    )


def test_a_phone_of_another_tenants_user_with_the_same_name_needs_existing_user(
    conn: psycopg.Connection[Any],
) -> None:
    """Skeptic probe h2.yaml: a typo that hits another 'Rodrigo' must not go through."""
    users = [
        {"name": "Rodrigo", "phone": RODRIGO_PHONE, "role": "owner", "email": "otro@example.com"}
    ]
    with pytest.raises(OnboardingError, match="existing_user: true"):
        apply(conn, make(users=users))


def test_a_phone_with_another_name_is_refused_even_without_another_tenant(
    conn: psycopg.Connection[Any],
) -> None:
    conn.execute(
        "insert into public.app_user (name, phone_e164) values ('Huérfano', '+525599990002')"
    )
    users = [{"name": "Rosa", "phone": "+525599990002", "role": "owner"}]
    with pytest.raises(OnboardingError, match="already belongs to"):
        apply(conn, make(users=users))


def test_existing_user_for_an_unknown_phone_is_refused(conn: psycopg.Connection[Any]) -> None:
    users = [{"name": "Rosa", "phone": "+525599990003", "role": "owner", "existing_user": True}]
    with pytest.raises(OnboardingError, match="no user has"):
        apply(conn, make(users=users))


def test_a_shared_users_name_and_email_are_never_changed(conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        "update public.app_user set email = 'rodrigo@elguero.mx' where phone_e164 = %s",
        (RODRIGO_PHONE,),
    )
    users = [
        {"name": "RODRIGO", "phone": RODRIGO_PHONE, "role": "owner", "existing_user": True,
         "email": "otro@example.com"},
    ]  # fmt: skip
    s = apply(conn, make(users=users))
    row = conn.execute(
        "select name, email from public.app_user where phone_e164 = %s", (RODRIGO_PHONE,)
    ).fetchone()
    assert row == ("Rodrigo", "rodrigo@elguero.mx")
    assert ("user", "unchanged") in {(c.entity, c.action) for c in s.changes}
    assert any("email" in n and "not changed" in n for n in s.notes), s.notes
    assert (
        one(
            conn,
            """select count(*) from public.audit_log
               where tenant_id = %s and entity_type = 'app_user'""",
            EL_GUERO,
        )
        == 0
    ), "nothing about El Güero's user is written to El Güero's audit"


def test_the_same_person_can_join_a_second_tenant(conn: psycopg.Connection[Any]) -> None:
    users = [{"name": "Rodrigo", "phone": RODRIGO_PHONE, "role": "owner", "existing_user": True}]
    s = apply(conn, make(users=users))
    rodrigo = user_id(conn, RODRIGO_PHONE)
    tenants = {
        r[0]
        for r in conn.execute(
            "select tenant_id from public.membership where user_id = %s", (rodrigo,)
        )
    }
    assert tenants == {EL_GUERO, s.tenant_id}
    assert any("other tenant" in n for n in s.notes)


def test_a_location_of_another_tenant_cannot_be_pinned(conn: psycopg.Connection[Any]) -> None:
    with pytest.raises(OnboardingError, match="no location with id"):
        apply(
            conn, make(locations=[{"id": EL_GUERO_CENTRO, "name": "Centro"}, SPEC["locations"][1]])
        )


def test_a_mexican_phone_with_the_old_1_finds_the_same_user(conn: psycopg.Connection[Any]) -> None:
    """Skeptic probe m1.yaml: +52 1 55... is Rodrigo, not a second app_user."""
    users = [{"name": "Pepe", "phone": "+52 1 55 1234 5001", "role": "owner"}]
    with pytest.raises(OnboardingError, match="already belongs to 'Rodrigo'"):
        apply(conn, make(users=users))


def test_two_spec_locations_resolving_to_one_row_are_refused(
    conn: psycopg.Connection[Any],
) -> None:
    """Skeptic probe m2.yaml: renaming Centro to Norte and listing Centro again."""
    spec = OnboardingSpec.model_validate(
        {
            "tenant": {"id": str(EL_GUERO), "name": "Taquería El Güero"},
            "locations": [
                {"id": EL_GUERO_CENTRO, "name": "Norte"},
                {"name": "Centro"},
                {"name": "Polanco"},
            ],
            "users": [{"name": "Rodrigo", "phone": RODRIGO_PHONE, "role": "owner"}],
        }
    )
    with pytest.raises(OnboardingError, match="same location"):
        apply(conn, spec)


def test_leaving_the_timezone_out_keeps_the_stored_one(conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        "update public.location set timezone = 'America/Cancun' where id = %s", (EL_GUERO_CENTRO,)
    )
    spec = OnboardingSpec.model_validate(
        {
            "tenant": {"id": str(EL_GUERO), "name": "Taquería El Güero"},
            "locations": [{"name": "Centro"}, {"name": "Polanco"}, {"name": "Nueva"}],
            "users": [{"name": "Rodrigo", "phone": RODRIGO_PHONE, "role": "owner"}],
        }
    )
    apply(conn, spec)
    zones = dict(
        conn.execute("select name, timezone from public.location where tenant_id = %s", (EL_GUERO,))
    )
    assert zones["Centro"] == "America/Cancun"
    assert zones["Nueva"] == "America/Mexico_City", "the default applies to a new location"


def test_the_audit_says_an_email_changed_without_the_email(conn: psycopg.Connection[Any]) -> None:
    first = apply(conn, make())
    users = [{**SPEC["users"][0], "email": "rosa2@example.com"}, *SPEC["users"][1:]]
    apply(conn, again(first, users=users))
    rows = conn.execute(
        """select before::text, after::text, after ->> 'email_changed' from public.audit_log
           where tenant_id = %s and entity_type = 'app_user' order by ts, id""",
        (first.tenant_id,),
    ).fetchall()
    assert not any("example.com" in (b or "") + a for b, a, _ in rows), rows
    assert [r[2] for r in rows if r[2]] == ["true", "true"], "Rosa created with one, then changed"


def test_onboarding_el_guero_again_changes_nothing_but_adds_sources_and_identities(
    conn: psycopg.Connection[Any],
) -> None:
    """The seed's restaurant as a spec: tenant, locations, users and memberships all match."""
    el_guero = OnboardingSpec.model_validate(
        {
            "tenant": {"id": str(EL_GUERO), "name": "Taquería El Güero"},
            "locations": [{"name": "Centro"}, {"name": "Polanco"}],
            "users": [
                {"name": "Rodrigo", "phone": RODRIGO_PHONE, "role": "owner"},
                {"name": "Lupita", "phone": "+525512345002", "role": "manager",
                 "locations": ["Centro"]},
                {"name": "Iván", "phone": "+525512345003", "role": "manager",
                 "locations": ["Polanco"]},
            ],
        }
    )  # fmt: skip
    s = apply(conn, el_guero)
    assert s.tenant_id == EL_GUERO
    changed = {(c.entity, c.action) for c in s.changes if c.action != "unchanged"}
    assert changed == {("whatsapp", "created"), ("source", "created")}, (
        "the seed has no manual sources"
    )


def test_owner_sees_only_the_new_tenant_and_all_its_locations(
    conn: psycopg.Connection[Any],
) -> None:
    s = apply(conn, make())
    with as_member(conn, s.tenant_id, "+525500000001"):
        assert [r[0] for r in conn.execute("select id from public.tenant")] == [s.tenant_id]
        assert {r[0] for r in conn.execute("select name from public.location")} == {
            "Centro",
            "Roma",
        }
        assert one(conn, "select count(*) from public.source") == 4
        assert one(conn, "select count(*) from public.audit_log") == s.audit_rows
        assert one(conn, "select count(*) from public.daily_sales_agg") == 0, "no El Güero data"


def test_manager_sees_only_their_location(conn: psycopg.Connection[Any]) -> None:
    s = apply(conn, make())
    with as_member(conn, s.tenant_id, "+525500000002"):
        assert [r[0] for r in conn.execute("select id from public.tenant")] == [s.tenant_id]
        assert [r[0] for r in conn.execute("select name from public.location")] == ["Roma"]
        sources = conn.execute("select kind::text from public.source").fetchall()
        assert sorted(r[0] for r in sources) == ["manual", "sr_report"]
        assert one(conn, "select count(*) from public.audit_log") == 0, "audit needs full scope"


def test_identity_tables_stay_hidden_from_the_new_owner(conn: psycopg.Connection[Any]) -> None:
    s = apply(conn, make())
    with as_member(conn, s.tenant_id, "+525500000001"):
        for table in ("membership", "app_user", "channel_identity"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(f"select count(*) from public.{table}")


def test_the_cli_dry_run_saves_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], db_url: str
) -> None:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(SPEC))
    with psycopg.connect(db_url) as c:
        before = one(c, "select count(*) from public.tenant")
    assert cli.main([str(path), "--dry-run", "--operator", OPERATOR]) == 0
    out = capsys.readouterr().out
    with psycopg.connect(db_url) as c:
        assert one(c, "select count(*) from public.tenant") == before
    assert "dry run" in out.lower() and "Taquería La Prueba" in out
    assert "+52******0001" in out and "+525500000001" not in out
    assert "postgres:postgres" not in out, "the password is never printed"


def test_the_cli_reports_a_refusal_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], db_url: str
) -> None:
    path = tmp_path / "spec.json"
    path.write_text(
        json.dumps({**SPEC, "users": [{"name": "X", "phone": RODRIGO_PHONE, "role": "owner"}]})
    )
    assert cli.main([str(path), "--dry-run", "--operator", OPERATOR]) == 1
    err = capsys.readouterr().err
    assert "already belongs to" in err and RODRIGO_PHONE not in err
