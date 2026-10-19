-- MR-10 control, operations and metering tables (09 section 2.5; spec 5.7, 7.2.6).
-- pending_change and audit_log are class F (readable only with all-locations scope). The writes
-- that approve and execute a change belong to later tickets (apply_pending_change, MR-32).

create table public.pending_change (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  kind text not null,
  target_type text,
  target_id uuid,
  base_version int,
  payload jsonb not null default '{}',
  diff jsonb,
  proposed_by_user uuid references public.app_user (id) on delete restrict,
  proposed_via app.proposed_via not null,
  required_role app.member_role,
  status app.pending_change_status not null default 'pending',
  expires_at timestamptz,
  resolved_by uuid references public.app_user (id) on delete restrict,
  resolved_at timestamptz,
  resolved_via text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id)
);
create index pending_change_proposed_by_idx on public.pending_change (proposed_by_user);
create index pending_change_resolved_by_idx on public.pending_change (resolved_by);
select app.tag('public.pending_change', 'values not yet specified', array['kind', 'target_type', 'resolved_via']);
select app.finish_table('public.pending_change', 'full');

-- Append-only: no updated_at, no version. Triggers stop the owner role; privileges stop the rest.
create table public.audit_log (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  ts timestamptz not null default now(),
  actor_user_id uuid references public.app_user (id) on delete restrict,
  actor_kind app.actor_kind not null,
  channel app.channel,
  action text not null,
  entity_type text,
  entity_id uuid,
  before jsonb,
  after jsonb,
  pending_change_id uuid,
  batch_id uuid,
  request_id text,
  unique (tenant_id, id),
  foreign key (tenant_id, pending_change_id) references public.pending_change (tenant_id, id) on delete restrict,
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict
);
create index audit_log_actor_idx on public.audit_log (actor_user_id);
create index audit_log_pending_change_idx on public.audit_log (tenant_id, pending_change_id);
create index audit_log_batch_idx on public.audit_log (tenant_id, batch_id);
select app.tag('public.audit_log', 'values not yet specified', array['entity_type']);
select app.finish_table('public.audit_log', 'full');
create trigger audit_log_no_row_mutation before update or delete on public.audit_log
  for each row execute function app.block_mutation();
create trigger audit_log_no_truncate before truncate on public.audit_log
  for each statement execute function app.block_mutation();
revoke all on public.audit_log from service_role;
grant select, insert on public.audit_log to service_role;

-- Alerts and suggestions are produced by code rules (03). location_id is added: get_cost_alerts
-- takes a location (09 section 4.1). Null location = tenant-level (spec 5.6).
create table public.alert (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid,
  rule text not null,
  subject text,
  value numeric,
  threshold numeric,
  status text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict
);
create index alert_location_idx on public.alert (tenant_id, location_id);
select app.tag('public.alert', 'values not yet specified', array['rule', 'status']);
select app.finish_table('public.alert', 'location', 'location_id');

create table public.price_suggestion (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid,
  rule text not null,
  subject text,
  value numeric,
  threshold numeric,
  status text,
  suggested_price bigint,
  currency char(3) not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  rationale_code text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict
);
create index price_suggestion_location_idx on public.price_suggestion (tenant_id, location_id);
select app.tag('public.price_suggestion', 'unit=centavos', array['suggested_price']);
select app.tag('public.price_suggestion', 'values not yet specified', array['rule', 'status', 'rationale_code']);
select app.finish_table('public.price_suggestion', 'location', 'location_id');

create table public.report_run (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid,
  kind app.report_kind not null,
  period_from date,
  period_to date,
  recipients uuid[] not null default '{}',
  template text,
  status text,
  wa_message_ids text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  check (period_from is null or period_to is null or period_from <= period_to),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict
);
create index report_run_location_idx on public.report_run (tenant_id, location_id);
select app.tag('public.report_run', 'values not yet specified', array['status']);
select app.finish_table('public.report_run', 'backend');

create table public.conversation (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  user_id uuid not null references public.app_user (id) on delete restrict,
  channel app.channel not null,
  summary text,
  last_turns jsonb not null default '[]',
  window_open_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  unique (tenant_id, user_id, channel)
);
create index conversation_user_idx on public.conversation (user_id);
select app.finish_table('public.conversation', 'backend');

-- Fields of 13 section I4. Cost is metered from day 1.
create table public.llm_usage (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid,
  user_id uuid references public.app_user (id) on delete restrict,
  ts timestamptz not null default now(),
  request_id text,
  route app.llm_route not null,
  model text,
  input_tokens int check (input_tokens >= 0),
  cache_read_tokens int check (cache_read_tokens >= 0),
  cache_write_tokens int check (cache_write_tokens >= 0),
  output_tokens int check (output_tokens >= 0),
  cost_usd numeric(12, 6) check (cost_usd >= 0),
  latency_ms int check (latency_ms >= 0),
  tool_calls int check (tool_calls >= 0),
  validator_result text,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict
);
create index llm_usage_location_idx on public.llm_usage (tenant_id, location_id);
create index llm_usage_user_idx on public.llm_usage (user_id);
select app.tag('public.llm_usage', 'unit=usd', array['cost_usd']);
select app.tag('public.llm_usage', 'values not yet specified', array['validator_result']);
select app.finish_table('public.llm_usage', 'backend');

create table public.message_log (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  wa_message_id text not null,
  direction text not null,
  template text,
  pricing_category app.meta_pricing_category,
  billable boolean,
  cost_usd numeric(12, 6) check (cost_usd >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id)
);
select app.tag('public.message_log', 'unit=usd', array['cost_usd']);
select app.tag('public.message_log', 'values not yet specified', array['direction']);
select app.finish_table('public.message_log', 'backend');
