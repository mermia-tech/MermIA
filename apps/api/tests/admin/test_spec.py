"""MR-30: the onboarding spec. Pure: validation, defaults and the masked phone. No database."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mermia_api.admin.spec import (
    EXAMPLE,
    OnboardingSpec,
    load_spec,
    mask_phone,
    wa_id,
)
from mermia_contracts.pending import PendingKind


def spec(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tenant": {"name": "Taquería La Prueba", "rfc": "tlp200101ab1"},
        "locations": [{"name": "Centro"}, {"name": "Roma"}],
        "users": [
            {"name": "Rosa", "phone": "+52 55 0000 0001", "role": "owner"},
            {
                "name": "Beto",
                "phone": "+52 (55) 0000-0002",
                "role": "manager",
                "locations": ["Roma"],
            },
        ],
    }
    return {**base, **over}


def test_a_valid_spec_gets_the_role_defaults() -> None:
    s = OnboardingSpec.model_validate(spec())
    owner, manager = s.users
    assert owner.phone == "+525500000001"
    assert owner.all_locations and owner.location_names == ()
    assert set(owner.approvals) == set(PendingKind)
    assert not manager.all_locations and manager.location_names == ("Roma",)
    assert manager.approvals == ("import_batch.approve", "import_batch.rollback")
    assert s.tenant.rfc == "TLP200101AB1", "RFC is stored upper case"
    assert s.locations[0].timezone == "America/Mexico_City"


def test_admin_and_support_defaults() -> None:
    users = [
        *spec()["users"],
        {"name": "Ana", "phone": "+525500000003", "role": "admin"},
        {"name": "Soporte", "phone": "+525500000004", "role": "support"},
    ]
    s = OnboardingSpec.model_validate(spec(users=users))
    admin, support = s.users[2:]
    assert admin.all_locations
    assert admin.approvals == ("ingredient_price.set", "recipe.upsert", "menu_item_price.set")
    assert support.all_locations and support.approvals == ()


def test_can_approve_overrides_the_default() -> None:
    users = [
        spec()["users"][0],
        {**spec()["users"][1], "can_approve": ["recipe.upsert", "import_batch.approve"]},
    ]
    (_, manager) = OnboardingSpec.model_validate(spec(users=users)).users
    assert manager.approvals == ("recipe.upsert", "import_batch.approve")


@pytest.mark.parametrize(
    ("users", "message"),
    [
        ([{"name": "Beto", "phone": "+525500000002", "role": "manager", "locations": ["Roma"]}],
         "at least one owner"),
        ([{"name": "Rosa", "phone": "+525500000001", "role": "owner"},
          {"name": "Beto", "phone": "+525500000002", "role": "manager"}],
         "must list its locations"),
        ([{"name": "Rosa", "phone": "+525500000001", "role": "owner"},
          {"name": "Beto", "phone": "+525500000002", "role": "manager", "locations": ["Narvarte"]}],
         "unknown location"),
        ([{"name": "Rosa", "phone": "+525500000001", "role": "owner"},
          {"name": "Beto", "phone": "+52 55 0000 0001", "role": "manager", "locations": ["Roma"]}],
         "phone listed twice"),
        ([{"name": "Rosa", "phone": "+525500000001", "role": "owner"},
          {"name": "Soporte", "phone": "+525500000004", "role": "support",
           "can_approve": ["recipe.upsert"]}],
         "support never approves"),
        ([{"name": "Rosa", "phone": "+525500000001", "role": "owner", "can_approve": ["x.y"]}],
         "can_approve"),
        ([{"name": "Rosa", "phone": "5500000001", "role": "owner"}], "E.164"),
        ([{"name": "Rosa", "phone": "+52 55 abc", "role": "owner"}], "E.164"),
        ([{"name": "Rosa", "phone": "+525500000001", "role": "owner", "email": "no-at"}], "email"),
        ([{"name": "Rosa", "phone": "+525500000001", "role": "chef"}], "role"),
        ([{"name": "  ", "phone": "+525500000001", "role": "owner"}], "name"),
        ([{"name": "Rosa", "phone": "+525500000001", "role": "owner", "locations": []}],
         "at least 1 item"),
        ([{"name": "Rosa", "phone": "+525500000001", "role": "owner", "phone2": "x"}], "phone2"),
    ],
)  # fmt: skip
def test_bad_users_are_refused(users: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        OnboardingSpec.model_validate(spec(users=users))


def test_location_names_are_unique_after_normalizing() -> None:
    with pytest.raises(ValidationError, match="location listed twice"):
        OnboardingSpec.model_validate(spec(locations=[{"name": "Centro"}, {"name": "centro "}]))


def test_a_user_names_a_location_however_it_is_written() -> None:
    users = [spec()["users"][0], {**spec()["users"][1], "locations": ["ROMA"]}]
    (_, manager) = OnboardingSpec.model_validate(spec(users=users)).users
    assert manager.location_names == ("ROMA",)


def test_unknown_timezone_and_bad_rfc_are_refused() -> None:
    with pytest.raises(ValidationError, match="time zone"):
        OnboardingSpec.model_validate(spec(locations=[{"name": "Centro", "timezone": "Mars/Base"}]))
    with pytest.raises(ValidationError, match="RFC"):
        OnboardingSpec.model_validate(spec(tenant={"name": "X", "rfc": "123"}))


def test_the_spec_needs_a_location_and_a_user() -> None:
    with pytest.raises(ValidationError):
        OnboardingSpec.model_validate(spec(locations=[]))
    with pytest.raises(ValidationError):
        OnboardingSpec.model_validate(spec(users=[]))


def test_the_example_file_is_valid() -> None:
    s = load_spec(EXAMPLE)
    assert s.tenant.name and s.locations and any(u.role == "owner" for u in s.users)


def test_load_spec_reads_json_too(tmp_path: Path) -> None:
    path = tmp_path / "spec.json"
    path.write_text(
        '{"tenant": {"name": "X"}, "locations": [{"name": "A"}],'
        ' "users": [{"name": "R", "phone": "+525500000001", "role": "owner"}]}'
    )
    assert load_spec(path).tenant.name == "X"


def test_load_spec_refuses_a_file_that_is_not_a_mapping(tmp_path: Path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text("- a\n- b\n")
    with pytest.raises(ValueError, match="mapping"):
        load_spec(path)


def test_masking_keeps_the_country_code_and_last_four() -> None:
    assert mask_phone("+525512345001") == "+52******5001"
    assert "1234" not in mask_phone("+525512345001")


def test_wa_id_is_the_number_without_plus() -> None:
    assert wa_id("+525512345001") == "525512345001"
