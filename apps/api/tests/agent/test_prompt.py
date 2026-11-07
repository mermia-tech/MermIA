"""The static prefix is identical for everyone (cacheable); tenant context goes in the tail."""

import hashlib
import inspect
import re
from datetime import date
from uuid import UUID

from mermia_api.agent.prompt import STATIC_PREFIX, tail
from mermia_contracts.db.models import MemberRole

CENTRO = UUID("705e8e51-376b-5785-adbb-405eff4e2a22")
POLANCO = UUID("fdda5e3b-6bcd-5c48-a6de-f524be37463e")
OTHER = UUID("0b5c2c9e-6f2a-4c1e-9d55-2f1f4c3a7e10")


def test_static_prefix_is_pinned() -> None:
    # A change here invalidates every tenant's provider cache: change it on purpose only.
    digest = hashlib.sha256(STATIC_PREFIX.encode()).hexdigest()
    assert digest == "13580b55c620d13bbe38cbe424c3ebcf061508ee69f6e9a70051a79fc9fd6fab"


def test_static_prefix_holds_no_date_and_no_location() -> None:
    assert not re.search(r"\d", STATIC_PREFIX)
    assert "Centro" not in STATIC_PREFIX and "Polanco" not in STATIC_PREFIX


def test_static_prefix_states_the_number_rule() -> None:
    assert "nunca inventes" in STATIC_PREFIX
    assert "propose_change" in STATIC_PREFIX


def test_tail_carries_today_role_and_locations() -> None:
    text = tail(
        today=date(2026, 11, 5),
        role=MemberRole.owner,
        locations={CENTRO: "Centro", POLANCO: "Polanco"},
    )
    assert "2026-11-05" in text and "jueves 5 de noviembre de 2026" in text
    assert "dueño" in text
    assert f"Centro ({CENTRO})" in text and f"Polanco ({POLANCO})" in text


def test_two_tenants_share_the_prefix_and_differ_in_the_tail() -> None:
    a = tail(today=date(2026, 11, 5), role=MemberRole.owner, locations={CENTRO: "Centro"})
    b = tail(today=date(2026, 11, 6), role=MemberRole.manager, locations={OTHER: "Norte"})
    assert a != b
    assert "gerente" in b


def test_tail_takes_no_personal_data() -> None:
    assert set(inspect.signature(tail).parameters) == {"today", "role", "locations"}
