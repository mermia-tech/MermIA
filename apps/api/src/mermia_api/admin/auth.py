"""Supabase Auth users for the Phase 2 dashboard (`--auth-users`, MR-30).

`app_user.auth_user_id` links a MermIA user to a Supabase Auth user. The dashboard's claims
will come from `membership` through the custom_access_token hook (MR-10 spec 7.5.2), never from
the auth user's metadata, so the auth user is created with an email only.

onboard.py first looks the user up by email in auth.users (same transaction); only a
missing one is created here, through the Admin API with the service-role key. That call commits
on its own: if the onboarding transaction then rolls back, the next run finds the user by email.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
REQUEST_TIMEOUT_S = 15


class AuthAdmin(Protocol):
    def create_user(self, email: str) -> UUID:
        """Creates a confirmed auth user with this email and returns its id."""
        ...


class AuthAdminError(RuntimeError):
    pass


class SupabaseAuthAdmin:
    """The GoTrue Admin API of one Supabase project. Refuses a non-loopback URL unless
    allow_remote is set, so tests and local runs cannot reach a real project by mistake."""

    def __init__(self, api_url: str, service_role_key: str, *, allow_remote: bool = False) -> None:
        host = urlparse(api_url).hostname
        if not allow_remote and host not in LOOPBACK_HOSTS:
            raise ValueError(
                "the auth API URL is not a loopback address; pass --allow-remote-auth to use it"
            )
        self._url = api_url.rstrip("/")
        self._key = service_role_key

    def create_user(self, email: str) -> UUID:
        body = json.dumps({"email": email, "email_confirm": True}).encode()
        request = urllib.request.Request(
            f"{self._url}/auth/v1/admin/users",
            data=body,
            method="POST",
            headers={
                "apikey": self._key,
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as e:
            raise AuthAdminError(f"the auth API refused the user (HTTP {e.code})") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise AuthAdminError(f"the auth API is unreachable: {e}") from None
        try:
            return UUID(payload["id"])
        except (KeyError, TypeError, ValueError):
            raise AuthAdminError("the auth API answered without a user id") from None
