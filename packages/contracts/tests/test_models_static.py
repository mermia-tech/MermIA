"""Shape, types, nullability, enums and JSON of the generated row models (no database)."""

import datetime as dt
import enum
import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from mermia_contracts.db import models
from mermia_contracts.db.overrides import ImportBatchStats, PaymentMix, TenantSettings

NOW = dt.datetime(2026, 10, 12, 12, 0, tzinfo=dt.UTC)
ID = uuid.UUID("11111111-1111-7111-8111-111111111111")


def rows() -> list[type]:
    return [c for n, c in vars(models).items() if n.endswith("Row") and n != "RowModel"]


def enums() -> list[type]:
    return [
        c
        for c in vars(models).values()
        if isinstance(c, type) and issubclass(c, enum.StrEnum) and c is not enum.StrEnum
    ]


def test_forty_rows_and_twenty_four_enums() -> None:
    assert len(rows()) == 40
    assert len(enums()) == 24


def test_rows_are_frozen_and_reject_unknown_columns() -> None:
    row = models.LocationRow(
        id=ID, tenant_id=ID, name="Centro", timezone="America/Mexico_City",
        created_at=NOW, updated_at=NOW, version=1,
    )  # fmt: skip
    with pytest.raises(ValidationError):
        row.name = "x"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        models.LocationRow(**{**row.model_dump(), "surprise": 1})


def test_required_columns_are_required_and_nullable_ones_default_to_none() -> None:
    with pytest.raises(ValidationError):
        models.LocationRow(id=ID)  # type: ignore[call-arg]
    row = models.LocationRow(
        id=ID, tenant_id=ID, name="Centro", timezone="x",
        created_at=NOW, updated_at=NOW, version=1,
    )  # fmt: skip
    assert row.address is None and row.sr_version is None


def test_audit_log_has_no_updated_at_or_version() -> None:
    fields = models.AuditLogRow.model_fields
    assert "updated_at" not in fields and "version" not in fields
    assert "ts" in fields


def test_membership_scope_columns() -> None:
    fields = models.MembershipRow.model_fields
    assert fields["all_locations"].is_required()
    assert not fields["location_ids"].is_required()
    row = models.MembershipRow(
        id=ID, tenant_id=ID, user_id=ID, role="owner", all_locations=True,
        location_ids=None, can_approve=[], created_at=NOW, updated_at=NOW, version=1,
    )  # fmt: skip
    assert row.role is models.MemberRole.owner and row.location_ids is None


def test_money_is_integer_centavos_and_unit_prices_keep_six_decimals() -> None:
    price = models.IngredientPriceRow(
        id=ID, tenant_id=ID, ingredient_id=ID, unit_price_net=Decimal("0.220000"),
        effective_from=dt.date(2026, 10, 12), source="manual",
        created_at=NOW, updated_at=NOW, version=1,
    )  # fmt: skip
    assert price.unit_price_net == Decimal("0.22")
    with pytest.raises(ValidationError):
        models.IngredientPriceRow(
            **{**price.model_dump(), "unit_price_net": Decimal("0.2200001")}
        )
    fields = models.DailySalesAggRow.model_fields
    assert fields["net_sales"].annotation is int
    assert fields["net_sales"].description == "unit=centavos"


def test_percent_points_alias_documents_the_unit() -> None:
    field = models.IngredientRow.model_fields["default_yield_pct"]
    assert field.description == "unit=percent_points"
    nullable = models.DishCostSnapshotRow.model_fields["food_cost_pct"]
    assert "unit=percent_points" in str(nullable.annotation)


def test_enum_members_follow_the_database_labels_and_escape_keywords() -> None:
    assert models.BatchStatus.needs_review.value == "needs_review"
    assert models.ProposedVia.import_.value == "import"
    assert [m.value for m in models.IssueSeverity] == ["info", "warning", "error"]


def test_documented_jsonb_columns_are_typed_and_the_rest_are_open() -> None:
    assert models.ImportBatchRow.model_fields["stats"].annotation is ImportBatchStats
    assert models.TenantRow.model_fields["settings"].annotation is TenantSettings
    settings = TenantSettings(target_food_cost_pct=Decimal("32.5"), kpis=["margin"])
    assert settings.model_extra == {"kpis": ["margin"]}
    mix = models.DailySalesAggRow.model_fields["payment_mix"].annotation
    assert mix == PaymentMix
    payload = models.PendingChangeRow.model_fields["payload"].annotation
    assert str(payload) == "pydantic.types.JsonValue" or "JsonValue" in str(payload)
