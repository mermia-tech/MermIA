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
    assert s.locations[0].timezone is None, "the default is applied only when inserting"
    assert not owner.existing_user


def test_admin_and_support_defaults() -> None:
    users = [
        *spec()["users"],
        {"name": "Ana", "phone": "+525500000003", "role": "admin"},
        {"name": "Soporte", "phone": "+525500000004", "role": "support"},
    ]
    s = OnboardingSpec.model_validate(spec(users=users))
    admin, support = s.users[2:]
    assert admin.all_locations
    assert admin.approvals == ("ingredient_price.set", "menu_item_price.set"), (
        "only the owner approves recipe.upsert by default (MR-25)"
    )
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


@pytest.mark.parametrize(
    "zone", ["america/mexico_city", "CST6CDT", "EST", "Etc/GMT+6", "Mars/Base"]
)
def test_time_zones_outside_the_db_rule_give_a_spec_error(zone: str) -> None:
    with pytest.raises(ValidationError, match="unknown time zone"):
        OnboardingSpec.model_validate(spec(locations=[{"name": "Centro", "timezone": zone}]))


def test_a_canonical_time_zone_is_accepted() -> None:
    s = OnboardingSpec.model_validate(
        spec(locations=[{"name": "Roma", "timezone": "America/Tijuana"}])
    )
    assert s.locations[0].timezone == "America/Tijuana"


def test_closed_days_become_sorted_iso_numbers_however_they_are_written() -> None:
    s = OnboardingSpec.model_validate(
        spec(
            locations=[
                {"name": "Centro", "closed_days": ["Domingo", "MIÉRCOLES", "lunes"]},
                {"name": "Roma"},
            ]
        )
    )
    assert s.locations[0].closed_weekdays == [1, 3, 7]


def test_no_closed_days_is_not_the_same_as_an_empty_list() -> None:
    s = OnboardingSpec.model_validate(
        spec(locations=[{"name": "Centro"}, {"name": "Roma", "closed_days": []}])
    )
    centro, roma = s.locations
    assert centro.closed_weekdays is None, "not said: keep the stored days"
    assert roma.closed_weekdays == [], "opens every day"


@pytest.mark.parametrize("days", ["ninguno", "Ninguno", " NINGUNO ", ["ninguno"], ["Ningúno"]])
def test_ninguno_means_it_opens_every_day(days: Any) -> None:
    s = OnboardingSpec.model_validate(
        spec(locations=[{"name": "Centro", "closed_days": days}, {"name": "Roma"}])
    )
    assert s.locations[0].closed_weekdays == []


@pytest.mark.parametrize(
    ("days", "message"),
    [
        (["ninguno", "lunes"], "va solo"),
        (["lunes", "ninguno"], "va solo"),
        (["ninguno", "ninguno"], "va solo"),
        (["funday"], "o ninguno si abre todos los días"),
        ([1], "día desconocido"),
        (["funday"], "día desconocido.*lunes, martes, miércoles, jueves, viernes, sábado, domingo"),
        (["lunes", "Lunes"], "día repetido"),
        (["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"], "siete días"),
        ("lunes", "debe ser una lista"),
    ],
)
def test_bad_closed_days_are_refused(days: Any, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        OnboardingSpec.model_validate(
            spec(locations=[{"name": "Centro", "closed_days": days}, {"name": "Roma"}])
        )


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


def test_a_mexican_phone_is_stored_without_the_old_mobile_1() -> None:
    users = [{"name": "Rosa", "phone": "+52 1 55 0000 0001", "role": "owner"}]
    (owner,) = OnboardingSpec.model_validate(spec(users=users)).users
    assert owner.phone == "+525500000001"


def test_the_same_phone_written_with_and_without_the_1_is_listed_twice() -> None:
    users = [
        {"name": "Rosa", "phone": "+525500000001", "role": "owner"},
        {"name": "Rosa2", "phone": "+5215500000001", "role": "admin"},
    ]
    with pytest.raises(ValidationError, match="phone listed twice"):
        OnboardingSpec.model_validate(spec(users=users))


def test_a_location_id_pinned_twice_is_refused() -> None:
    pin = "0193f000-0000-7000-8000-000000000001"
    locations = [{"id": pin, "name": "Centro"}, {"id": pin, "name": "Roma"}]
    with pytest.raises(ValidationError, match="location id listed twice"):
        OnboardingSpec.model_validate(spec(locations=locations))


def test_an_email_listed_twice_is_refused() -> None:
    users = [
        {"name": "Rosa", "phone": "+525500000001", "role": "owner", "email": "a@example.com"},
        {"name": "Beto", "phone": "+525500000002", "role": "admin", "email": "A@example.com"},
    ]
    with pytest.raises(ValidationError, match="email listed twice"):
        OnboardingSpec.model_validate(spec(users=users))


def test_existing_user_marks_a_person_of_another_tenant() -> None:
    users = [{"name": "Rosa", "phone": "+525500000001", "role": "owner", "existing_user": True}]
    (owner,) = OnboardingSpec.model_validate(spec(users=users)).users
    assert owner.existing_user


def test_a_duplicate_yaml_key_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text(
        "tenant: {name: X}\nlocations: [{name: A}]\n"
        "users:\n  - name: R\n    phone: '+525500000001'\n    role: manager\n"
        "    locations: all\n    role: owner\n"
    )
    with pytest.raises(ValueError, match="duplicate key 'role'"):
        load_spec(path)
