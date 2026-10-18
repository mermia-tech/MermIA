"""Exposure through PostgREST and GraphQL against the local Supabase stack (spec 7.2.5).

Needs MERMIA_DB_URL (to insert and remove fixtures) and MERMIA_API_URL, MERMIA_JWT_SECRET and
MERMIA_API_KEY (the local values printed by `supabase status -o env`). Local stack only: the
JWT secret is a published demo value. Nothing here touches a remote database.
"""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request

import psycopg
import pytest

pytestmark = [pytest.mark.rest, pytest.mark.db]

TA = "aaaaaaaa-0000-7000-8000-0000000000e1"
TB = "bbbbbbbb-0000-7000-8000-0000000000e2"
A1 = "a1a1a1a1-0000-7000-8000-0000000000e1"
A2 = "a2a2a2a2-0000-7000-8000-0000000000e2"
B1 = "b1b1b1b1-0000-7000-8000-0000000000e3"
SECRET_FILE = "secret-file-do-not-leak.xlsx"
SECRET_PHONE = "+5215599990001"
SECRET_CONFIG = "secret-config-do-not-leak"
X_TABLES = [
    "app_user", "channel_identity", "consent_log", "membership", "raw_file",
    "report_run", "external_ref", "conversation", "llm_usage", "message_log",
]  # fmt: skip


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def mint(claims: dict, secret: str | None = None) -> str:
    secret = secret or env("MERMIA_JWT_SECRET")
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps({"exp": int(time.time()) + 300, **claims}).encode())
    sig = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


def token(tenant: str = TA, locations: list[str] | None | str = "all") -> str:
    claims: dict = {"role": "authenticated", "tenant_id": tenant}
    if locations != "absent":
        claims["location_ids"] = None if locations == "all" else locations
    return mint(claims)


def call(
    path: str,
    bearer: str,
    method: str = "GET",
    body: dict | None = None,
    base: str = "/rest/v1/",
):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        env("MERMIA_API_URL") + base + path,
        data=data,
        method=method,
        headers={
            "apikey": env("MERMIA_API_KEY"),
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


USER = "0e5e0000-0000-7000-8000-0000000000e1"
SRC = "5c5c0000-0000-7000-8000-0000000000e1"
FILE = "f11e0000-0000-7000-8000-0000000000e1"
B_CENTRO = "ba7c0000-0000-7000-8000-0000000000e1"
B_POLANCO = "ba7c0000-0000-7000-8000-0000000000e2"


@pytest.fixture(scope="module")
def fixtures():
    url = env("MERMIA_DB_URL")
    env("MERMIA_API_URL")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("set session_replication_role = replica")
        statements = [
            (
                "insert into public.tenant (id, name) values (%s, 'REST A'), (%s, 'REST B')",
                (TA, TB),
            ),
            (
                (
                    "insert into public.location (tenant_id, id, name, timezone) values "
                    "(%s, %s, 'Centro', 'x'), (%s, %s, 'Polanco', 'x'), (%s, %s, 'B uno', 'x')"
                ),
                (TA, A1, TA, A2, TB, B1),
            ),
            (
                "insert into public.app_user (id, name, phone_e164) values (%s, 'Laura', %s)",
                (USER, SECRET_PHONE),
            ),
            (
                (
                    "insert into public.source (id, tenant_id, location_id, kind, config) "
                    "values (%s, %s, %s, 'sr_report', %s::jsonb)"
                ),
                (SRC, TA, A1, json.dumps({"k": SECRET_CONFIG})),
            ),
            (
                (
                    "insert into public.raw_file (id, tenant_id, storage_path, sha256, filename) "
                    "values (%s, %s, 'raw/x', repeat('c', 64), %s)"
                ),
                (FILE, TA, SECRET_FILE),
            ),
            (
                (
                    "insert into public.import_batch "
                    "(id, tenant_id, source_id, raw_file_id, location_id, parser, slice_key, applied_by) values "
                    "(%s, %s, %s, %s, %s, 'sr.x@v1', 'rest-centro', %s), "
                    "(%s, %s, %s, null, %s, 'sr.x@v1', 'rest-polanco', null)"
                ),
                (B_CENTRO, TA, SRC, FILE, A1, USER, B_POLANCO, TA, SRC, A2),
            ),
            (
                (
                    "insert into public.import_issue (tenant_id, batch_id, severity, code, message_es) values "
                    "(%s, %s, 'info', 'centro_issue', 'Centro'), (%s, %s, 'info', 'polanco_issue', 'Polanco')"
                ),
                (TA, B_CENTRO, TA, B_POLANCO),
            ),
            (
                (
                    "insert into public.menu_category (id, tenant_id, name, parent_id) values "
                    "('ca7e0000-0000-7000-8000-0000000000e1', %s, 'Bebidas', null), "
                    "('ca7e0000-0000-7000-8000-0000000000e2', %s, 'Aguas',"
                    " 'ca7e0000-0000-7000-8000-0000000000e1')"
                ),
                (TA, TA),
            ),
        ]
        for sql, params in statements:
            conn.execute(sql, params)
        yield
        for table in (
            "import_issue",
            "import_batch",
            "raw_file",
            "source",
            "menu_category",
            "location",
        ):
            conn.execute(
                f"delete from public.{table} where tenant_id in (%s, %s)", (TA, TB)
            )
        conn.execute("delete from public.app_user where id = %s", (USER,))
        conn.execute("delete from public.tenant where id in (%s, %s)", (TA, TB))


def test_forged_and_expired_tokens_are_rejected(fixtures) -> None:
    forged = mint(
        {"role": "authenticated", "tenant_id": TA, "location_ids": None}, "x" * 40
    )
    assert call("location?select=name", forged)[0] == 401
    expired = mint(
        {"role": "authenticated", "tenant_id": TA, "location_ids": None, "exp": 1}
    )
    assert call("location?select=name", expired)[0] == 401


@pytest.mark.parametrize("table", X_TABLES)
def test_backend_only_tables_are_refused(fixtures, table: str) -> None:
    status, body = call(f"{table}?select=*", token())
    assert status == 403, (table, status, body[:200])
    assert SECRET_PHONE not in body and SECRET_FILE not in body


def test_source_hides_its_secret_columns(fixtures) -> None:
    status, body = call("source?select=*", token())
    assert status == 403 and SECRET_CONFIG not in body
    status, body = call("source?select=config", token())
    assert status == 403 and SECRET_CONFIG not in body
    status, body = call("source?select=id,kind", token())
    assert status == 200 and json.loads(body)[0]["kind"] == "sr_report"


@pytest.mark.parametrize(
    "embed",
    [
        "raw_file(*)",
        "applied_by(*)",
        "applied_by:app_user!import_batch_applied_by_fkey(*)",
        "raw_file:raw_file!import_batch_tenant_id_raw_file_id_fkey(*)",
        "source(*)",
    ],
)
def test_embedding_backend_only_or_hidden_data_is_refused(fixtures, embed: str) -> None:
    status, body = call(f"import_batch?select=slice_key,{embed}", token())
    assert status == 403 and json.loads(body)["code"] == "42501", (
        embed,
        status,
        body[:200],
    )
    assert (
        SECRET_PHONE not in body
        and SECRET_FILE not in body
        and SECRET_CONFIG not in body
    )


def test_embedding_the_readable_columns_of_source_works(fixtures) -> None:
    # positive control: the refusals above are about privileges, not about a broken request
    status, body = call(
        "import_batch?select=slice_key,source(id,kind)&order=slice_key", token()
    )
    assert status == 200, body[:200]
    kinds = {r["slice_key"]: r["source"]["kind"] for r in json.loads(body)}
    assert kinds == {"rest-centro": "sr_report", "rest-polanco": "sr_report"}
    assert SECRET_CONFIG not in body


def test_embedding_cannot_reach_a_hidden_table_from_the_other_side(fixtures) -> None:
    # An ambiguous relationship is reported (300) before any permission check; a hinted one
    # reaches the privilege layer (403). Either way no data comes back.
    paths = {
        "raw_file?select=*,import_batch(*)": {403},
        "app_user?select=*,import_batch(*)": {300, 403},
        "app_user?select=*,import_batch!import_batch_applied_by_fkey(*)": {403},
    }
    for path, allowed in paths.items():
        status, body = call(path, token())
        assert status in allowed, (path, status, body[:200])
        assert SECRET_PHONE not in body and SECRET_FILE not in body, path


def test_import_issue_follows_its_batch_directly_and_embedded(fixtures) -> None:
    centro = token(locations=[A1])
    status, body = call("import_issue?select=code", centro)
    assert status == 200 and [r["code"] for r in json.loads(body)] == ["centro_issue"]
    status, body = call("import_batch?select=slice_key,import_issue(code)", centro)
    assert status == 200
    rows = json.loads(body)
    assert [r["slice_key"] for r in rows] == ["rest-centro"]
    assert [i["code"] for i in rows[0]["import_issue"]] == ["centro_issue"]
    assert "polanco" not in body
    status, body = call("import_issue?select=code,import_batch(slice_key)", centro)
    assert status == 200 and "polanco" not in body
    status, body = call("import_issue?select=code", token(locations="absent"))
    assert status == 200 and json.loads(body) == []
    status, body = call("import_issue?select=code", token(locations=[]))
    assert status == 200 and json.loads(body) == []
    status, body = call("import_issue?select=code", token())
    assert sorted(r["code"] for r in json.loads(body)) == [
        "centro_issue",
        "polanco_issue",
    ]


def test_other_tenants_see_nothing(fixtures) -> None:
    status, body = call("import_issue?select=code", token(tenant=TB))
    assert status == 200 and json.loads(body) == []
    status, body = call("location?select=name", token(tenant=TB))
    assert [r["name"] for r in json.loads(body)] == ["B uno"]


def test_writes_are_refused(fixtures) -> None:
    row = {"tenant_id": TA, "name": "Injected", "timezone": "x"}
    assert call("location", token(), "POST", row)[0] == 403
    assert call(f"location?id=eq.{A1}", token(), "PATCH", {"name": "Hacked"})[0] == 403
    assert call(f"location?id=eq.{A1}", token(), "DELETE")[0] == 403
    assert (
        call(
            "audit_log",
            token(),
            "POST",
            {"tenant_id": TA, "actor_kind": "user", "action": "x"},
        )[0]
        == 403
    )


def test_helper_schema_is_not_exposed(fixtures) -> None:
    status, body = call("rpc/current_tenant_id", token(), "POST", {})
    assert status in (404, 406), (status, body[:200])
    status, body = call(
        "rpc/set_config",
        token(),
        "POST",
        {"setting_name": "request.jwt.claims", "new_value": "{}", "is_local": False},
    )
    assert status == 404


def test_openapi_lists_no_backend_only_table(fixtures) -> None:
    status, body = call("", token())
    if status != 200:
        pytest.skip(f"OpenAPI document not served ({status})")
    paths = set(json.loads(body).get("paths", {}))
    assert {f"/{t}" for t in X_TABLES}.isdisjoint(paths), sorted(paths)
    assert "/location" in paths


def test_graphql_does_not_expose_backend_only_tables_or_secrets(fixtures) -> None:
    def graphql(query: str):
        return call("", token(), "POST", {"query": query}, base="/graphql/v1")

    # Positive control first: if GraphQL cannot even read a readable table, nothing below
    # proves anything, so the test is reported as skipped (not run), never as passed.
    status, body = graphql("{ locationCollection { edges { node { name } } } }")
    if status != 200 or "Centro" not in body:
        pytest.skip(
            f"GraphQL does not serve data on this stack ({status}: {body[:120]})"
        )
    _, body = graphql("{ rawFileCollection { edges { node { filename } } } }")
    assert SECRET_FILE not in body
    _, body = graphql("{ sourceCollection { edges { node { config } } } }")
    assert SECRET_CONFIG not in body


def test_a_self_referencing_composite_foreign_key_embeds(fixtures) -> None:
    status, body = call(
        "menu_category?select=name,menu_category(name)&order=name", token()
    )
    assert status == 200, body[:200]
    rows = {
        r["name"]: [c["name"] for c in r["menu_category"]] for r in json.loads(body)
    }
    assert rows == {"Aguas": [], "Bebidas": ["Aguas"]}
    status, body = call(
        "menu_category?select=name,menu_category(name)", token(tenant=TB)
    )
    assert status == 200 and json.loads(body) == []
