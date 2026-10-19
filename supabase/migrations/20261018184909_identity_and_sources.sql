-- MR-10 tenancy, identity and sources (09 section 2.1; spec 5.7, 7.2).
-- app_user, channel_identity and consent_log have no tenant_id: one person can belong to several
-- tenants. They are backend-only (class X).

create table public.tenant (
  id uuid primary key default app.uuid_v7(),
  name text not null,
  rfc text,
  plan text,
  settings jsonb not null default '{}',
  status text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1
);
select app.tag('public.tenant', 'values not yet specified', array['plan', 'status']);
select app.finish_table('public.tenant', 'tenant_root');

create table public.location (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  name text not null,
  timezone text not null,
  address text,
  sr_version text,
  sr_edition text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id)
);
select app.tag('public.location', 'values not yet specified', array['sr_version', 'sr_edition']);
select app.finish_table('public.location', 'location', 'id');

create table public.app_user (
  id uuid primary key default app.uuid_v7(),
  name text not null,
  phone_e164 text unique check (phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
  email text,
  auth_user_id uuid unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1
);
select app.finish_table('public.app_user', 'backend');

-- location_ids: SQL null means every location (09 2.1) but only together with the explicit flag.
-- A row that states no scope gets an empty list, i.e. no location (spec 5.7, 7.5.10).
create table public.membership (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  user_id uuid not null references public.app_user (id) on delete restrict,
  role app.member_role not null,
  location_ids uuid[] default '{}',
  all_locations boolean not null default false,
  can_approve text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  unique (tenant_id, user_id),
  constraint membership_scope_explicit check (all_locations = (location_ids is null))
);
create index membership_user_idx on public.membership (user_id);

-- Claims are derived from this row, so its integrity is a security property (spec 7.5.5).
create function app.check_membership_locations() returns trigger
language plpgsql set search_path = ''
as $$
begin
  if new.location_ids is not null and exists (
    select 1 from unnest(new.location_ids) as l (id)
    where not exists (select 1 from public.location x where x.id = l.id and x.tenant_id = new.tenant_id)
  ) then
    raise exception 'location_ids contains a location outside the tenant' using errcode = '23514';
  end if;
  return new;
end
$$;
create trigger membership_locations before insert or update of location_ids, tenant_id
  on public.membership for each row execute function app.check_membership_locations();
select app.finish_table('public.membership', 'backend');

create table public.channel_identity (
  id uuid primary key default app.uuid_v7(),
  user_id uuid not null references public.app_user (id) on delete restrict,
  channel app.channel not null,
  external_id text not null,
  verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (channel, external_id)
);
create index channel_identity_user_idx on public.channel_identity (user_id);
select app.finish_table('public.channel_identity', 'backend');

create table public.consent_log (
  id uuid primary key default app.uuid_v7(),
  user_id uuid not null references public.app_user (id) on delete restrict,
  notice_version text not null,
  channel app.channel not null,
  accepted_at timestamptz not null,
  message_types text[] not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1
);
create index consent_log_user_idx on public.consent_log (user_id);
select app.finish_table('public.consent_log', 'backend');

create table public.source (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  location_id uuid,
  kind app.source_kind not null,
  config jsonb not null default '{}',
  api_key_hash text,
  status text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict
);
create index source_location_idx on public.source (tenant_id, location_id);
select app.tag('public.source', 'values not yet specified', array['status']);
select app.finish_table('public.source', 'location', 'location_id');
-- Clients read sources (get_data_status) but never the secrets (spec 7.2.2).
revoke select on public.source from authenticated;
grant select (id, tenant_id, location_id, kind, status, created_at, updated_at, version)
  on public.source to authenticated;

create table public.external_ref (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  source_id uuid not null,
  entity_type text not null,
  external_id text not null,
  internal_id uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  unique (tenant_id, source_id, entity_type, external_id),
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict
);
select app.tag('public.external_ref', 'values not yet specified', array['entity_type']);
select app.finish_table('public.external_ref', 'backend');
