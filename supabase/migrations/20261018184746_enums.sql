-- MR-10 enums. Only values written in the architecture docs (spec 5.3); other columns stay text.
-- Postgres cannot drop enum values: additions are later ALTER TYPE ... ADD VALUE migrations.

create type app.member_role as enum ('owner', 'manager', 'admin', 'support');
create type app.channel as enum ('whatsapp', 'web', 'pos');
create type app.source_kind as enum (
  'sr_report', 'sr_corte_email', 'sr_erp_push', 'sr_connector', 'cfdi', 'photo_ocr', 'manual', 'mermia_pos');
create type app.batch_quality as enum ('file', 'push', 'ocr');
create type app.batch_status as enum (
  'received', 'rejected', 'parsed', 'needs_review', 'applied', 'rolled_back', 'superseded');
create type app.issue_severity as enum ('info', 'warning', 'error');
create type app.menu_item_kind as enum ('dish', 'drink', 'modifier', 'combo');
create type app.sale_channel as enum ('dine_in', 'takeout', 'delivery_app', 'delivery');
create type app.ticket_status as enum ('paid', 'cancelled');
create type app.fiscal_status as enum ('none', 'requested', 'in_global', 'stamped');
create type app.payment_method as enum ('cash', 'card', 'transfer', 'voucher', 'other');
create type app.supplier_kind as enum ('cfdi', 'market', 'other');
create type app.base_unit as enum ('g', 'ml', 'pza');
create type app.yield_source as enum ('default', 'measured');
create type app.purchase_doc_kind as enum ('cfdi', 'nota_photo', 'manual');
create type app.ingredient_price_source as enum ('cfdi', 'nota', 'sr_import', 'manual', 'benchmark');
create type app.recipe_status as enum ('draft', 'confirmed');
create type app.cost_confidence as enum ('confirmed', 'estimated', 'missing');
create type app.pending_change_status as enum (
  'pending', 'approved', 'rejected', 'expired', 'conflict', 'applied', 'failed');
create type app.proposed_via as enum ('agent', 'dashboard', 'import', 'pos');
create type app.actor_kind as enum ('user', 'system', 'agent');
create type app.report_kind as enum ('weekly', 'daily');
create type app.llm_route as enum ('template', 'haiku', 'sonnet', 'fallback');
create type app.meta_pricing_category as enum ('marketing', 'utility', 'authentication', 'service');
