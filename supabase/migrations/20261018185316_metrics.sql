-- MR-10 precomputed metrics (09 section 2.5; spec 5.7). Class L: they follow the location filter.

create table public.dish_cost_snapshot (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  menu_item_id uuid not null,
  location_id uuid not null,
  date date not null,
  cost bigint not null,
  price_net bigint not null,
  margin bigint not null,
  currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  food_cost_pct numeric(7, 4),
  confidence app.cost_confidence not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  unique (tenant_id, menu_item_id, location_id, date),
  foreign key (tenant_id, menu_item_id) references public.menu_item (tenant_id, id) on delete restrict,
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict
);
create index dish_cost_snapshot_location_idx on public.dish_cost_snapshot (tenant_id, location_id, date);
select app.tag('public.dish_cost_snapshot', 'unit=centavos', array['cost', 'price_net', 'margin']);
select app.tag('public.dish_cost_snapshot', 'unit=percent_points', array['food_cost_pct']);
select app.finish_table('public.dish_cost_snapshot', 'location', 'location_id');

create table public.daily_location_metrics (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid not null,
  business_date date not null,
  net_sales bigint not null,
  currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  tickets int,
  avg_ticket bigint,
  theoretical_food_cost_pct numeric(7, 4),
  cost_coverage_pct numeric(7, 4),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  unique (tenant_id, location_id, business_date),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict
);
select app.tag('public.daily_location_metrics', 'unit=centavos', array['net_sales', 'avg_ticket']);
select app.tag('public.daily_location_metrics', 'unit=percent_points',
               array['theoretical_food_cost_pct', 'cost_coverage_pct']);
select app.finish_table('public.daily_location_metrics', 'location', 'location_id');
