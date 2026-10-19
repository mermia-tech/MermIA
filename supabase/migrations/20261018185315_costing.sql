-- MR-10 costing (09 section 2.4; spec 5.4, 5.7). Unit prices are numeric(20,6) pesos per unit;
-- ledger totals are bigint centavos. Percentages are percent points.

create table public.supplier (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  name text not null,
  rfc text,
  kind app.supplier_kind not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id)
);
select app.finish_table('public.supplier', 'tenant');

create table public.ingredient (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  name text not null,
  base_unit app.base_unit not null,
  category text,
  default_yield_pct numeric(7, 4) not null default 100,
  yield_source app.yield_source not null default 'default',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id)
);
select app.tag('public.ingredient', 'unit=percent_points', array['default_yield_pct']);
select app.finish_table('public.ingredient', 'tenant');

create table public.ingredient_alias (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  supplier_id uuid not null,
  source_text text not null,
  ingredient_id uuid not null,
  pack_qty numeric(18, 6),
  pack_unit text,
  confirmed_by uuid references public.app_user (id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  unique (tenant_id, supplier_id, source_text),
  foreign key (tenant_id, supplier_id) references public.supplier (tenant_id, id) on delete restrict,
  foreign key (tenant_id, ingredient_id) references public.ingredient (tenant_id, id) on delete restrict
);
create index ingredient_alias_ingredient_idx on public.ingredient_alias (tenant_id, ingredient_id);
create index ingredient_alias_confirmed_by_idx on public.ingredient_alias (confirmed_by);
select app.tag('public.ingredient_alias', 'unit=quantity', array['pack_qty']);
select app.tag('public.ingredient_alias', 'values not yet specified', array['pack_unit']);
select app.finish_table('public.ingredient_alias', 'tenant');

-- ingredient_id null = a global conversion (kg to g, L to ml).
create table public.unit_conversion (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  ingredient_id uuid,
  from_unit text not null,
  to_unit text not null,
  factor numeric(20, 10) not null check (factor > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  unique nulls not distinct (tenant_id, ingredient_id, from_unit, to_unit),
  foreign key (tenant_id, ingredient_id) references public.ingredient (tenant_id, id) on delete restrict
);
select app.tag('public.unit_conversion', 'unit=quantity', array['factor']);
select app.tag('public.unit_conversion', 'values not yet specified', array['from_unit', 'to_unit']);
select app.finish_table('public.unit_conversion', 'tenant');

create table public.purchase_doc (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  supplier_id uuid not null,
  kind app.purchase_doc_kind not null,
  cfdi_uuid uuid,
  issued_at timestamptz,
  subtotal bigint,
  total bigint,
  currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  raw_file_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  unique (tenant_id, cfdi_uuid),
  foreign key (tenant_id, supplier_id) references public.supplier (tenant_id, id) on delete restrict,
  foreign key (tenant_id, raw_file_id) references public.raw_file (tenant_id, id) on delete restrict
);
create index purchase_doc_supplier_idx on public.purchase_doc (tenant_id, supplier_id);
create index purchase_doc_raw_file_idx on public.purchase_doc (tenant_id, raw_file_id);
select app.tag('public.purchase_doc', 'unit=centavos', array['subtotal', 'total']);
select app.finish_table('public.purchase_doc', 'tenant');

create table public.purchase_line (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  purchase_doc_id uuid not null,
  description text not null,
  qty numeric(18, 6) not null,
  unit text not null,
  unit_price_net numeric(20, 6) not null,
  ingredient_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, purchase_doc_id) references public.purchase_doc (tenant_id, id) on delete restrict,
  foreign key (tenant_id, ingredient_id) references public.ingredient (tenant_id, id) on delete restrict
);
create index purchase_line_doc_idx on public.purchase_line (tenant_id, purchase_doc_id);
create index purchase_line_ingredient_idx on public.purchase_line (tenant_id, ingredient_id);
select app.tag('public.purchase_line', 'unit=quantity', array['qty']);
select app.tag('public.purchase_line', 'unit=pesos_per_purchase_unit', array['unit_price_net']);
select app.tag('public.purchase_line', 'values not yet specified', array['unit']);
select app.finish_table('public.purchase_line', 'tenant');

-- Append-only by convention; the cost of record by date follows source priority (03).
create table public.ingredient_price (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  ingredient_id uuid not null,
  unit_price_net numeric(20, 6) not null,
  effective_from date not null,
  effective_to date,
  source app.ingredient_price_source not null,
  source_ref text,
  confidence text,
  batch_id uuid,
  pending_change_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  check (effective_to is null or effective_to >= effective_from),
  check (num_nonnulls(batch_id, pending_change_id) <= 1),
  foreign key (tenant_id, ingredient_id) references public.ingredient (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict,
  foreign key (tenant_id, pending_change_id) references public.pending_change (tenant_id, id) on delete restrict
);
create index ingredient_price_ingredient_idx on public.ingredient_price (tenant_id, ingredient_id, effective_from);
create index ingredient_price_batch_idx on public.ingredient_price (tenant_id, batch_id);
create index ingredient_price_pending_change_idx on public.ingredient_price (tenant_id, pending_change_id);
select app.tag('public.ingredient_price', 'unit=pesos_per_base_unit', array['unit_price_net']);
select app.tag('public.ingredient_price', 'values not yet specified', array['confidence']);
select app.finish_table('public.ingredient_price', 'tenant');

-- 09 section 2.4 names the recipe revision `version`, which collides with the shared optimistic
-- concurrency column `version`. The revision is stored as recipe_version (spec 5.6, C18).
create table public.recipe (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  menu_item_id uuid,
  produces_ingredient_id uuid,
  recipe_version int not null,
  effective_from date,
  effective_to date,
  yield_qty numeric(18, 6),
  status app.recipe_status not null default 'draft',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  check (num_nonnulls(menu_item_id, produces_ingredient_id) = 1),
  check (effective_to is null or effective_from is null or effective_to >= effective_from),
  foreign key (tenant_id, menu_item_id) references public.menu_item (tenant_id, id) on delete restrict,
  foreign key (tenant_id, produces_ingredient_id) references public.ingredient (tenant_id, id) on delete restrict
);
create index recipe_item_idx on public.recipe (tenant_id, menu_item_id);
create index recipe_ingredient_idx on public.recipe (tenant_id, produces_ingredient_id);
select app.tag('public.recipe', 'unit=quantity', array['yield_qty']);
select app.finish_table('public.recipe', 'tenant');

create table public.recipe_line (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  recipe_id uuid not null,
  ingredient_id uuid,
  sub_recipe_id uuid,
  qty_base numeric(18, 6) not null,
  yield_override_pct numeric(7, 4),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  check (num_nonnulls(ingredient_id, sub_recipe_id) = 1),
  foreign key (tenant_id, recipe_id) references public.recipe (tenant_id, id) on delete restrict,
  foreign key (tenant_id, ingredient_id) references public.ingredient (tenant_id, id) on delete restrict,
  foreign key (tenant_id, sub_recipe_id) references public.recipe (tenant_id, id) on delete restrict
);
create index recipe_line_recipe_idx on public.recipe_line (tenant_id, recipe_id);
create index recipe_line_ingredient_idx on public.recipe_line (tenant_id, ingredient_id);
create index recipe_line_sub_recipe_idx on public.recipe_line (tenant_id, sub_recipe_id);
select app.tag('public.recipe_line', 'unit=quantity', array['qty_base']);
select app.tag('public.recipe_line', 'unit=percent_points', array['yield_override_pct']);
select app.finish_table('public.recipe_line', 'tenant');
