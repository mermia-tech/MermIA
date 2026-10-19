-- MR-10 catalog and sales facts (09 section 2.3; spec 5.4, 5.6, 5.7).
-- Every table carries location_id, source_id, external_id and batch_id (09 section 2). They are
-- nullable on shared catalog rows and not null on fact rows. All ten tables are class L: a row
-- with a location follows the location filter, and a row without one is tenant-level (shared
-- catalog), visible to members who have at least one location or all of them. Money is bigint centavos plus a
-- currency; quantities are numeric(18,6).

create table public.menu_category (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid,
  source_id uuid,
  external_id text,
  batch_id uuid,
  name text not null,
  parent_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict,
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict,
  foreign key (tenant_id, parent_id) references public.menu_category (tenant_id, id) on delete restrict
);
create index menu_category_location_idx on public.menu_category (tenant_id, location_id);
create index menu_category_source_idx on public.menu_category (tenant_id, source_id);
create index menu_category_batch_idx on public.menu_category (tenant_id, batch_id);
create index menu_category_parent_idx on public.menu_category (tenant_id, parent_id);
select app.finish_table('public.menu_category', 'location', 'location_id');

-- Shared across locations: location_id stays null.
create table public.menu_item (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid,
  source_id uuid,
  external_id text,
  batch_id uuid,
  name text not null,
  normalized_name text,
  category_id uuid,
  kind app.menu_item_kind not null default 'dish',
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict,
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict,
  foreign key (tenant_id, category_id) references public.menu_category (tenant_id, id) on delete restrict
);
create index menu_item_location_idx on public.menu_item (tenant_id, location_id);
create index menu_item_source_idx on public.menu_item (tenant_id, source_id);
create index menu_item_batch_idx on public.menu_item (tenant_id, batch_id);
create index menu_item_category_idx on public.menu_item (tenant_id, category_id);
create index menu_item_normalized_name_idx on public.menu_item (tenant_id, normalized_name);
select app.finish_table('public.menu_item', 'location', 'location_id');

create table public.menu_item_price (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid not null,
  source_id uuid,
  external_id text,
  batch_id uuid,
  menu_item_id uuid not null,
  price_gross bigint not null,
  currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  tax_rate numeric(5, 4),
  effective_from date not null,
  effective_to date,
  source text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  check (effective_to is null or effective_to >= effective_from),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict,
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict,
  foreign key (tenant_id, menu_item_id) references public.menu_item (tenant_id, id) on delete restrict
);
create index menu_item_price_location_idx on public.menu_item_price (tenant_id, location_id);
create index menu_item_price_source_idx on public.menu_item_price (tenant_id, source_id);
create index menu_item_price_batch_idx on public.menu_item_price (tenant_id, batch_id);
create index menu_item_price_item_idx on public.menu_item_price (tenant_id, menu_item_id);
select app.tag('public.menu_item_price', 'unit=centavos', array['price_gross']);
select app.tag('public.menu_item_price', 'unit=fraction', array['tax_rate']);
select app.tag('public.menu_item_price', 'values not yet specified', array['source']);
select app.finish_table('public.menu_item_price', 'location', 'location_id');

create table public.modifier_link (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid,
  source_id uuid,
  external_id text,
  batch_id uuid,
  menu_item_id uuid not null,
  modifier_item_id uuid not null,
  price_delta bigint not null default 0,
  currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict,
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict,
  foreign key (tenant_id, menu_item_id) references public.menu_item (tenant_id, id) on delete restrict,
  foreign key (tenant_id, modifier_item_id) references public.menu_item (tenant_id, id) on delete restrict
);
create index modifier_link_location_idx on public.modifier_link (tenant_id, location_id);
create index modifier_link_source_idx on public.modifier_link (tenant_id, source_id);
create index modifier_link_batch_idx on public.modifier_link (tenant_id, batch_id);
create index modifier_link_item_idx on public.modifier_link (tenant_id, menu_item_id);
create index modifier_link_modifier_idx on public.modifier_link (tenant_id, modifier_item_id);
select app.tag('public.modifier_link', 'unit=centavos', array['price_delta']);
select app.finish_table('public.modifier_link', 'location', 'location_id');

-- Personal data: first name only (09 section 2.3).
create table public.staff (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid,
  source_id uuid,
  external_id text,
  batch_id uuid,
  display_name text not null,
  role text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict,
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict
);
create index staff_location_idx on public.staff (tenant_id, location_id);
create index staff_source_idx on public.staff (tenant_id, source_id);
create index staff_batch_idx on public.staff (tenant_id, batch_id);
select app.tag('public.staff', 'values not yet specified', array['role']);
select app.finish_table('public.staff', 'location', 'location_id');

create table public.sale_ticket (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid not null,
  source_id uuid not null,
  external_id text,
  batch_id uuid not null,
  business_date date not null,
  opened_at timestamptz,
  closed_at timestamptz,
  channel app.sale_channel,
  area text,
  table_label text,
  guests int,
  staff_id uuid,
  subtotal bigint not null,
  discount bigint not null default 0,
  tax bigint not null default 0,
  tip bigint not null default 0,
  total bigint not null,
  currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  status app.ticket_status not null,
  fiscal_status app.fiscal_status not null default 'none',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  -- lets lines and payments prove they share the ticket's location (spec 5.7)
  unique (tenant_id, id, location_id),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict,
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict,
  foreign key (tenant_id, staff_id) references public.staff (tenant_id, id) on delete restrict
);
create index sale_ticket_location_idx on public.sale_ticket (tenant_id, location_id, business_date);
create index sale_ticket_source_idx on public.sale_ticket (tenant_id, source_id);
create index sale_ticket_batch_idx on public.sale_ticket (tenant_id, batch_id);
create index sale_ticket_staff_idx on public.sale_ticket (tenant_id, staff_id);
select app.tag('public.sale_ticket', 'unit=centavos', array['subtotal', 'discount', 'tax', 'tip', 'total']);
select app.finish_table('public.sale_ticket', 'location', 'location_id');

create table public.sale_line (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid not null,
  source_id uuid not null,
  external_id text,
  batch_id uuid not null,
  ticket_id uuid not null,
  menu_item_id uuid not null,
  parent_line_id uuid,
  qty numeric(18, 6) not null,
  unit_price bigint not null,
  discount bigint not null default 0,
  tax bigint not null default 0,
  net bigint not null,
  currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  is_void boolean not null default false,
  void_reason text,
  voided_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, ticket_id, location_id)
    references public.sale_ticket (tenant_id, id, location_id) on delete restrict,
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict,
  foreign key (tenant_id, menu_item_id) references public.menu_item (tenant_id, id) on delete restrict,
  foreign key (tenant_id, parent_line_id) references public.sale_line (tenant_id, id) on delete restrict,
  foreign key (tenant_id, voided_by) references public.staff (tenant_id, id) on delete restrict
);
create index sale_line_ticket_idx on public.sale_line (tenant_id, ticket_id);
create index sale_line_location_idx on public.sale_line (tenant_id, location_id);
create index sale_line_source_idx on public.sale_line (tenant_id, source_id);
create index sale_line_batch_idx on public.sale_line (tenant_id, batch_id);
create index sale_line_item_idx on public.sale_line (tenant_id, menu_item_id);
create index sale_line_parent_idx on public.sale_line (tenant_id, parent_line_id);
create index sale_line_voided_by_idx on public.sale_line (tenant_id, voided_by);
select app.tag('public.sale_line', 'unit=quantity', array['qty']);
select app.tag('public.sale_line', 'unit=centavos', array['unit_price', 'discount', 'tax', 'net']);
select app.finish_table('public.sale_line', 'location', 'location_id');

create table public.payment (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid not null,
  source_id uuid not null,
  external_id text,
  batch_id uuid not null,
  ticket_id uuid not null,
  method app.payment_method not null,
  amount bigint not null,
  tip bigint not null default 0,
  currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  provider text,
  provider_ref text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, ticket_id, location_id)
    references public.sale_ticket (tenant_id, id, location_id) on delete restrict,
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict
);
create index payment_ticket_idx on public.payment (tenant_id, ticket_id);
create index payment_location_idx on public.payment (tenant_id, location_id);
create index payment_source_idx on public.payment (tenant_id, source_id);
create index payment_batch_idx on public.payment (tenant_id, batch_id);
select app.tag('public.payment', 'unit=centavos', array['amount', 'tip']);
select app.finish_table('public.payment', 'location', 'location_id');

-- Aggregate grain: "Productos vendidos" style reports. period_from = period_to for a single day
-- (spec 5.6; the pilot sample will say whether range exports occur).
create table public.item_sales_agg (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid not null,
  source_id uuid not null,
  external_id text,
  batch_id uuid not null,
  period_from date not null,
  period_to date not null,
  menu_item_id uuid not null,
  units numeric(18, 6) not null,
  gross bigint not null,
  discount bigint not null default 0,
  net bigint not null,
  currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  check (period_from <= period_to),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict,
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict,
  foreign key (tenant_id, menu_item_id) references public.menu_item (tenant_id, id) on delete restrict
);
create index item_sales_agg_location_idx on public.item_sales_agg (tenant_id, location_id, period_from);
create index item_sales_agg_source_idx on public.item_sales_agg (tenant_id, source_id);
create index item_sales_agg_batch_idx on public.item_sales_agg (tenant_id, batch_id);
create index item_sales_agg_item_idx on public.item_sales_agg (tenant_id, menu_item_id);
select app.tag('public.item_sales_agg', 'unit=quantity', array['units']);
select app.tag('public.item_sales_agg', 'unit=centavos', array['gross', 'discount', 'net']);
select app.finish_table('public.item_sales_agg', 'location', 'location_id');

-- Aggregate grain: Corte Z / "Ventas por dia". Only net_sales is required; the other figures are
-- null when a report does not give them ("not reported" is not zero; spec 5.5).
create table public.daily_sales_agg (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid not null,
  source_id uuid not null,
  external_id text,
  batch_id uuid not null,
  business_date date not null,
  net_sales bigint not null,
  tax bigint,
  tickets int,
  guests int,
  discounts bigint,
  cancellations_amount bigint,
  cancellations_count int,
  payment_mix jsonb not null default '{}',
  tips bigint,
  currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict,
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict
);
create index daily_sales_agg_location_idx on public.daily_sales_agg (tenant_id, location_id, business_date);
create index daily_sales_agg_source_idx on public.daily_sales_agg (tenant_id, source_id);
create index daily_sales_agg_batch_idx on public.daily_sales_agg (tenant_id, batch_id);
select app.tag('public.daily_sales_agg', 'unit=centavos',
               array['net_sales', 'tax', 'discounts', 'cancellations_amount', 'tips']);
select app.finish_table('public.daily_sales_agg', 'location', 'location_id');
