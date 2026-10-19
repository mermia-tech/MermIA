"""Row models of the public schema. GENERATED: do not edit.

Regenerate with `python -m mermia_contracts.tools.gen_db_models` after
`supabase db reset`. Source of truth: supabase/migrations.

generator_version: 1
migrations_sha256: c989c17feaff371bd3fcdac4cb4e56ffc19c6f811660b87677e06e4d08e4f212
"""

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, JsonValue

from mermia_contracts.db.overrides import ImportBatchStats, PaymentMix, TenantSettings
from mermia_contracts.db.types import (
    Bytes,
    Cents,
    Factor,
    Fraction,
    PercentPoints,
    Quantity,
    RowModel,
    UnitPricePesosPerBaseUnit,
    UnitPricePesosPerPurchaseUnit,
    Usd,
)


class ActorKind(StrEnum):
    user = "user"
    system = "system"
    agent = "agent"


class BaseUnit(StrEnum):
    g = "g"
    ml = "ml"
    pza = "pza"


class BatchQuality(StrEnum):
    file = "file"
    push = "push"
    ocr = "ocr"


class BatchStatus(StrEnum):
    received = "received"
    rejected = "rejected"
    parsed = "parsed"
    needs_review = "needs_review"
    applied = "applied"
    rolled_back = "rolled_back"
    superseded = "superseded"


class Channel(StrEnum):
    whatsapp = "whatsapp"
    web = "web"
    pos = "pos"


class CostConfidence(StrEnum):
    confirmed = "confirmed"
    estimated = "estimated"
    missing = "missing"


class FiscalStatus(StrEnum):
    none = "none"
    requested = "requested"
    in_global = "in_global"
    stamped = "stamped"


class IngredientPriceSource(StrEnum):
    cfdi = "cfdi"
    nota = "nota"
    sr_import = "sr_import"
    manual = "manual"
    benchmark = "benchmark"


class IssueSeverity(StrEnum):
    info = "info"
    warning = "warning"
    error = "error"


class LlmRoute(StrEnum):
    template = "template"
    haiku = "haiku"
    sonnet = "sonnet"
    fallback = "fallback"


class MemberRole(StrEnum):
    owner = "owner"
    manager = "manager"
    admin = "admin"
    support = "support"


class MenuItemKind(StrEnum):
    dish = "dish"
    drink = "drink"
    modifier = "modifier"
    combo = "combo"


class MetaPricingCategory(StrEnum):
    marketing = "marketing"
    utility = "utility"
    authentication = "authentication"
    service = "service"


class PaymentMethod(StrEnum):
    cash = "cash"
    card = "card"
    transfer = "transfer"
    voucher = "voucher"
    other = "other"


class PendingChangeStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    conflict = "conflict"
    applied = "applied"
    failed = "failed"


class ProposedVia(StrEnum):
    agent = "agent"
    dashboard = "dashboard"
    import_ = "import"
    pos = "pos"


class PurchaseDocKind(StrEnum):
    cfdi = "cfdi"
    nota_photo = "nota_photo"
    manual = "manual"


class RecipeStatus(StrEnum):
    draft = "draft"
    confirmed = "confirmed"


class ReportKind(StrEnum):
    weekly = "weekly"
    daily = "daily"


class SaleChannel(StrEnum):
    dine_in = "dine_in"
    takeout = "takeout"
    delivery_app = "delivery_app"
    delivery = "delivery"


class SourceKind(StrEnum):
    sr_report = "sr_report"
    sr_corte_email = "sr_corte_email"
    sr_erp_push = "sr_erp_push"
    sr_connector = "sr_connector"
    cfdi = "cfdi"
    photo_ocr = "photo_ocr"
    manual = "manual"
    mermia_pos = "mermia_pos"


class SupplierKind(StrEnum):
    cfdi = "cfdi"
    market = "market"
    other = "other"


class TicketStatus(StrEnum):
    paid = "paid"
    cancelled = "cancelled"


class YieldSource(StrEnum):
    default = "default"
    measured = "measured"


class AlertRow(RowModel):
    """Row of public.alert. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID | None = None
    rule: str
    subject: str | None = None
    value: Decimal | None = None
    threshold: Decimal | None = None
    status: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class AppUserRow(RowModel):
    """Row of public.app_user. rls_class=X."""

    id: UUID
    name: str
    phone_e164: str | None = None
    email: str | None = None
    auth_user_id: UUID | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class AuditLogRow(RowModel):
    """Row of public.audit_log. rls_class=F."""

    id: UUID
    tenant_id: UUID
    ts: AwareDatetime
    actor_user_id: UUID | None = None
    actor_kind: ActorKind
    channel: Channel | None = None
    action: str
    entity_type: str | None = None
    entity_id: UUID | None = None
    before: JsonValue | None = None
    after: JsonValue | None = None
    pending_change_id: UUID | None = None
    batch_id: UUID | None = None
    request_id: str | None = None


class ChannelIdentityRow(RowModel):
    """Row of public.channel_identity. rls_class=X."""

    id: UUID
    user_id: UUID
    channel: Channel
    external_id: str
    verified_at: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class ConsentLogRow(RowModel):
    """Row of public.consent_log. rls_class=X."""

    id: UUID
    user_id: UUID
    notice_version: str
    channel: Channel
    accepted_at: AwareDatetime
    message_types: list[str]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class ConversationRow(RowModel):
    """Row of public.conversation. rls_class=X."""

    id: UUID
    tenant_id: UUID
    user_id: UUID
    channel: Channel
    summary: str | None = None
    last_turns: JsonValue
    window_open_until: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class DailyLocationMetricsRow(RowModel):
    """Row of public.daily_location_metrics. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID
    business_date: dt.date
    net_sales: Cents
    currency: str
    tickets: int | None = None
    avg_ticket: Cents | None = None
    theoretical_food_cost_pct: PercentPoints | None = None
    cost_coverage_pct: PercentPoints | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class DailySalesAggRow(RowModel):
    """Row of public.daily_sales_agg. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID
    source_id: UUID
    external_id: str | None = None
    batch_id: UUID
    business_date: dt.date
    net_sales: Cents
    tax: Cents | None = None
    tickets: int | None = None
    guests: int | None = None
    discounts: Cents | None = None
    cancellations_amount: Cents | None = None
    cancellations_count: int | None = None
    payment_mix: PaymentMix
    tips: Cents | None = None
    currency: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class DishCostSnapshotRow(RowModel):
    """Row of public.dish_cost_snapshot. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    menu_item_id: UUID
    location_id: UUID
    date: dt.date
    cost: Cents
    price_net: Cents
    margin: Cents
    currency: str
    food_cost_pct: PercentPoints | None = None
    confidence: CostConfidence
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class ExternalRefRow(RowModel):
    """Row of public.external_ref. rls_class=X."""

    id: UUID
    tenant_id: UUID
    source_id: UUID
    entity_type: str
    external_id: str
    internal_id: UUID
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class ImportBatchRow(RowModel):
    """Row of public.import_batch. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    source_id: UUID
    raw_file_id: UUID | None = None
    location_id: UUID | None = None
    parser: str
    slice_key: str
    status: BatchStatus
    stats: ImportBatchStats
    supersedes_batch_id: UUID | None = None
    quality: BatchQuality
    applied_by: UUID | None = None
    applied_at: AwareDatetime | None = None
    rolled_back_by: UUID | None = None
    rolled_back_at: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class ImportIssueRow(RowModel):
    """Row of public.import_issue. rls_class=LP."""

    id: UUID
    tenant_id: UUID
    batch_id: UUID
    severity: IssueSeverity
    code: str
    message_es: str
    row_ref: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class IngredientRow(RowModel):
    """Row of public.ingredient. rls_class=T."""

    id: UUID
    tenant_id: UUID
    name: str
    base_unit: BaseUnit
    category: str | None = None
    default_yield_pct: PercentPoints
    yield_source: YieldSource
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class IngredientAliasRow(RowModel):
    """Row of public.ingredient_alias. rls_class=T."""

    id: UUID
    tenant_id: UUID
    supplier_id: UUID
    source_text: str
    ingredient_id: UUID
    pack_qty: Quantity | None = None
    pack_unit: str | None = None
    confirmed_by: UUID | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class IngredientPriceRow(RowModel):
    """Row of public.ingredient_price. rls_class=T."""

    id: UUID
    tenant_id: UUID
    ingredient_id: UUID
    unit_price_net: UnitPricePesosPerBaseUnit
    effective_from: dt.date
    effective_to: dt.date | None = None
    source: IngredientPriceSource
    source_ref: str | None = None
    confidence: str | None = None
    batch_id: UUID | None = None
    pending_change_id: UUID | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class ItemSalesAggRow(RowModel):
    """Row of public.item_sales_agg. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID
    source_id: UUID
    external_id: str | None = None
    batch_id: UUID
    period_from: dt.date
    period_to: dt.date
    menu_item_id: UUID
    units: Quantity
    gross: Cents
    discount: Cents
    net: Cents
    currency: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class LlmUsageRow(RowModel):
    """Row of public.llm_usage. rls_class=X."""

    id: UUID
    tenant_id: UUID
    location_id: UUID | None = None
    user_id: UUID | None = None
    ts: AwareDatetime
    request_id: str | None = None
    route: LlmRoute
    model: str | None = None
    input_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Usd | None = None
    latency_ms: int | None = None
    tool_calls: int | None = None
    validator_result: str | None = None
    error: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class LocationRow(RowModel):
    """Row of public.location. rls_class=L;loc_col=id."""

    id: UUID
    tenant_id: UUID
    name: str
    timezone: str
    address: str | None = None
    sr_version: str | None = None
    sr_edition: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class MembershipRow(RowModel):
    """Row of public.membership. rls_class=X."""

    id: UUID
    tenant_id: UUID
    user_id: UUID
    role: MemberRole
    location_ids: list[UUID] | None = None
    all_locations: bool
    can_approve: list[str]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class MenuCategoryRow(RowModel):
    """Row of public.menu_category. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID | None = None
    source_id: UUID | None = None
    external_id: str | None = None
    batch_id: UUID | None = None
    name: str
    parent_id: UUID | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class MenuItemRow(RowModel):
    """Row of public.menu_item. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID | None = None
    source_id: UUID | None = None
    external_id: str | None = None
    batch_id: UUID | None = None
    name: str
    normalized_name: str | None = None
    category_id: UUID | None = None
    kind: MenuItemKind
    is_active: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class MenuItemPriceRow(RowModel):
    """Row of public.menu_item_price. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID
    source_id: UUID | None = None
    external_id: str | None = None
    batch_id: UUID | None = None
    menu_item_id: UUID
    price_gross: Cents
    currency: str
    tax_rate: Fraction | None = None
    effective_from: dt.date
    effective_to: dt.date | None = None
    source: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class MessageLogRow(RowModel):
    """Row of public.message_log. rls_class=X."""

    id: UUID
    tenant_id: UUID
    wa_message_id: str
    direction: str
    template: str | None = None
    pricing_category: MetaPricingCategory | None = None
    billable: bool | None = None
    cost_usd: Usd | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class ModifierLinkRow(RowModel):
    """Row of public.modifier_link. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID | None = None
    source_id: UUID | None = None
    external_id: str | None = None
    batch_id: UUID | None = None
    menu_item_id: UUID
    modifier_item_id: UUID
    price_delta: Cents
    currency: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class PaymentRow(RowModel):
    """Row of public.payment. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID
    source_id: UUID
    external_id: str | None = None
    batch_id: UUID
    ticket_id: UUID
    method: PaymentMethod
    amount: Cents
    tip: Cents
    currency: str
    provider: str | None = None
    provider_ref: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class PendingChangeRow(RowModel):
    """Row of public.pending_change. rls_class=F."""

    id: UUID
    tenant_id: UUID
    kind: str
    target_type: str | None = None
    target_id: UUID | None = None
    base_version: int | None = None
    payload: JsonValue
    diff: JsonValue | None = None
    proposed_by_user: UUID | None = None
    proposed_via: ProposedVia
    required_role: MemberRole | None = None
    status: PendingChangeStatus
    expires_at: AwareDatetime | None = None
    resolved_by: UUID | None = None
    resolved_at: AwareDatetime | None = None
    resolved_via: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class PriceSuggestionRow(RowModel):
    """Row of public.price_suggestion. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID | None = None
    rule: str
    subject: str | None = None
    value: Decimal | None = None
    threshold: Decimal | None = None
    status: str | None = None
    suggested_price: Cents | None = None
    currency: str
    rationale_code: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class PurchaseDocRow(RowModel):
    """Row of public.purchase_doc. rls_class=T."""

    id: UUID
    tenant_id: UUID
    supplier_id: UUID
    kind: PurchaseDocKind
    cfdi_uuid: UUID | None = None
    issued_at: AwareDatetime | None = None
    subtotal: Cents | None = None
    total: Cents | None = None
    currency: str
    raw_file_id: UUID | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class PurchaseLineRow(RowModel):
    """Row of public.purchase_line. rls_class=T."""

    id: UUID
    tenant_id: UUID
    purchase_doc_id: UUID
    description: str
    qty: Quantity
    unit: str
    unit_price_net: UnitPricePesosPerPurchaseUnit
    ingredient_id: UUID | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class RawFileRow(RowModel):
    """Row of public.raw_file. rls_class=X."""

    id: UUID
    tenant_id: UUID
    storage_path: str
    sha256: str
    mime: str | None = None
    filename: str | None = None
    size: Bytes | None = None
    received_via: str | None = None
    sender_user_id: UUID | None = None
    received_at: AwareDatetime
    retention_until: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class RecipeRow(RowModel):
    """Row of public.recipe. rls_class=T."""

    id: UUID
    tenant_id: UUID
    menu_item_id: UUID | None = None
    produces_ingredient_id: UUID | None = None
    recipe_version: int
    effective_from: dt.date | None = None
    effective_to: dt.date | None = None
    yield_qty: Quantity | None = None
    status: RecipeStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class RecipeLineRow(RowModel):
    """Row of public.recipe_line. rls_class=T."""

    id: UUID
    tenant_id: UUID
    recipe_id: UUID
    ingredient_id: UUID | None = None
    sub_recipe_id: UUID | None = None
    qty_base: Quantity
    yield_override_pct: PercentPoints | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class ReportRunRow(RowModel):
    """Row of public.report_run. rls_class=X."""

    id: UUID
    tenant_id: UUID
    location_id: UUID | None = None
    kind: ReportKind
    period_from: dt.date | None = None
    period_to: dt.date | None = None
    recipients: list[UUID]
    template: str | None = None
    status: str | None = None
    wa_message_ids: list[str]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class SaleLineRow(RowModel):
    """Row of public.sale_line. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID
    source_id: UUID
    external_id: str | None = None
    batch_id: UUID
    ticket_id: UUID
    menu_item_id: UUID
    parent_line_id: UUID | None = None
    qty: Quantity
    unit_price: Cents
    discount: Cents
    tax: Cents
    net: Cents
    currency: str
    is_void: bool
    void_reason: str | None = None
    voided_by: UUID | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class SaleTicketRow(RowModel):
    """Row of public.sale_ticket. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID
    source_id: UUID
    external_id: str | None = None
    batch_id: UUID
    business_date: dt.date
    opened_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None
    channel: SaleChannel | None = None
    area: str | None = None
    table_label: str | None = None
    guests: int | None = None
    staff_id: UUID | None = None
    subtotal: Cents
    discount: Cents
    tax: Cents
    tip: Cents
    total: Cents
    currency: str
    status: TicketStatus
    fiscal_status: FiscalStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class SourceRow(RowModel):
    """Row of public.source. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID | None = None
    kind: SourceKind
    config: JsonValue
    api_key_hash: str | None = None
    status: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class StaffRow(RowModel):
    """Row of public.staff. rls_class=L;loc_col=location_id."""

    id: UUID
    tenant_id: UUID
    location_id: UUID | None = None
    source_id: UUID | None = None
    external_id: str | None = None
    batch_id: UUID | None = None
    display_name: str
    role: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class SupplierRow(RowModel):
    """Row of public.supplier. rls_class=T."""

    id: UUID
    tenant_id: UUID
    name: str
    rfc: str | None = None
    kind: SupplierKind
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class TenantRow(RowModel):
    """Row of public.tenant. rls_class=T."""

    id: UUID
    name: str
    rfc: str | None = None
    plan: str | None = None
    settings: TenantSettings
    status: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int


class UnitConversionRow(RowModel):
    """Row of public.unit_conversion. rls_class=T."""

    id: UUID
    tenant_id: UUID
    ingredient_id: UUID | None = None
    from_unit: str
    to_unit: str
    factor: Factor
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int
