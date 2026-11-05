"""MR-30: --auth-users links app_user.auth_user_id to a Supabase Auth user (Phase 2 dashboard).

The fake-client tests need MERMIA_DB_URL only and roll back. The live test also needs
MERMIA_API_URL and MERMIA_SERVICE_ROLE_KEY from `supabase status -o env` (local demo values)
and is marked rest: it creates a real user in the local auth service and deletes it afterwards.
Nothing here touches a remote project: SupabaseAuthAdmin refuses a non-loopback URL.
"""

import json
import os
import urllib.request
import uuid
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import psycopg
import pytest

from mermia_api.admin.auth import SupabaseAuthAdmin
from mermia_api.admin.onboard import OnboardingError, onboard
from mermia_api.admin.spec import OnboardingSpec


def spec(email: str | None) -> OnboardingSpec:
    return OnboardingSpec.model_validate(
        {
            "tenant": {"name": "Taquería La Prueba Auth"},
            "locations": [{"name": "Centro"}],
            "users": [
                {"name": "Rosa", "phone": "+525500000011", "role": "owner", "email": email},
                {"name": "Beto", "phone": "+525500000012", "role": "manager",
                 "locations": ["Centro"]},
            ],
        }
    )  # fmt: skip


class FakeAuth:
    def __init__(self) -> None:
        self.created: list[str] = []

    def create_user(self, email: str) -> UUID:
        self.created.append(email)
        return uuid.uuid4()


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        yield c


def linked(conn: psycopg.Connection[Any], phone: str) -> UUID | None:
    row = conn.execute(
        "select auth_user_id from public.app_user where phone_e164 = %s", (phone,)
    ).fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    "url", ["https://abc.supabase.co", "http://10.0.0.5:54321", "http://localhost.evil.com"]
)
def test_a_remote_auth_url_is_refused(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        SupabaseAuthAdmin(url, "key")


def test_a_remote_auth_url_is_allowed_only_when_asked() -> None:
    SupabaseAuthAdmin("https://abc.supabase.co", "key", allow_remote=True)
    SupabaseAuthAdmin("http://127.0.0.1:55321", "key")
    SupabaseAuthAdmin("http://localhost:55321", "key")


@pytest.mark.db
def test_a_user_with_an_email_gets_an_auth_user_once(conn: psycopg.Connection[Any]) -> None:
    fake = FakeAuth()
    onboard(conn, spec("rosa.auth@example.com"), auth=fake)
    assert fake.created == ["rosa.auth@example.com"]
    first = linked(conn, "+525500000011")
    assert first is not None
    assert linked(conn, "+525500000012") is None, "no email, no auth user"
    again = onboard(conn, spec("rosa.auth@example.com"), auth=fake)
    assert fake.created == ["rosa.auth@example.com"], "a linked user is not created again"
    assert linked(conn, "+525500000011") == first
    assert any("Beto" in n and "no email" in n for n in again.notes)


@pytest.mark.db
def test_an_existing_auth_user_is_found_by_email(conn: psycopg.Connection[Any]) -> None:
    existing = uuid.uuid4()
    conn.execute(
        "insert into auth.users (id, email) values (%s, %s)", (existing, "Rosa.Auth@example.com")
    )
    fake = FakeAuth()
    onboard(conn, spec("rosa.auth@example.com"), auth=fake)
    assert fake.created == []
    assert linked(conn, "+525500000011") == existing


@pytest.mark.db
def test_an_auth_user_linked_to_someone_else_is_refused(conn: psycopg.Connection[Any]) -> None:
    existing = uuid.uuid4()
    conn.execute("insert into auth.users (id, email) values (%s, 'taken@example.com')", (existing,))
    conn.execute(
        """insert into public.app_user (name, phone_e164, auth_user_id)
           values ('Otro', '+525500000099', %s)""",
        (existing,),
    )
    with pytest.raises(OnboardingError, match="already linked"):
        onboard(conn, spec("taken@example.com"), auth=FakeAuth())


@pytest.mark.db
def test_without_the_flag_no_auth_user_is_made(conn: psycopg.Connection[Any]) -> None:
    onboard(conn, spec("rosa.auth@example.com"))
    assert linked(conn, "+525500000011") is None


@pytest.mark.db
@pytest.mark.rest
def test_the_local_auth_service_creates_the_user(conn: psycopg.Connection[Any]) -> None:
    url = os.environ.get("MERMIA_API_URL")
    key = os.environ.get("MERMIA_SERVICE_ROLE_KEY")
    if not url or not key:
        pytest.skip("MERMIA_API_URL or MERMIA_SERVICE_ROLE_KEY is not set")
    email = f"mr30-{uuid.uuid4().hex[:12]}@example.com"
    client = SupabaseAuthAdmin(url, key)
    created: UUID | None = None
    try:
        onboard(conn, spec(email), auth=client)
        created = linked(conn, "+525500000011")
        assert created is not None
        row = conn.execute("select email from auth.users where id = %s", (created,)).fetchone()
        assert row == (email,)
        onboard(conn, spec(email), auth=client)
        assert linked(conn, "+525500000011") == created
    finally:
        if created is not None:
            request = urllib.request.Request(
                f"{url}/auth/v1/admin/users/{created}",
                method="DELETE",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                data=json.dumps({}).encode(),
            )
            with urllib.request.urlopen(request, timeout=10):
                pass
