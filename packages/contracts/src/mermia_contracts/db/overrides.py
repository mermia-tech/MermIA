"""Typed shapes for jsonb columns whose content the architecture documents.

Everything else stays JsonValue until MR-11 defines it (spec 10.2). The generator imports
the names listed in OVERRIDES.
"""

from pydantic import BaseModel, ConfigDict

from mermia_contracts.db.types import Cents, PercentPoints


class TenantSettings(BaseModel):
    """tenant.settings: food-cost target and report cadence (09 section 2.1).

    The key names are provisional: 03 names the target `target_food_cost_pct`; the
    cadence key is an author choice. Other keys (for example owner-chosen KPIs, 07) pass.
    """

    model_config = ConfigDict(extra="allow")

    target_food_cost_pct: PercentPoints | None = None
    report_cadence: str | None = None


class ImportBatchStats(BaseModel):
    """import_batch.stats: rows, totals, anomalies (09 section 2.2)."""

    model_config = ConfigDict(extra="allow")

    rows: int | None = None
    totals: dict[str, int | str | None] | None = None  # no floats: totals can be money
    anomalies: list[str] | None = None


PaymentMix = dict[str, Cents]
"""daily_sales_agg.payment_mix: centavos by payment_method label (09 section 2.3)."""

# (table, column) -> name defined in this module
OVERRIDES: dict[tuple[str, str], str] = {
    ("tenant", "settings"): "TenantSettings",
    ("import_batch", "stats"): "ImportBatchStats",
    ("daily_sales_agg", "payment_mix"): "PaymentMix",
}
