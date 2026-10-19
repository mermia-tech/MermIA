-- MR-10 foundations: schema app, UUIDv7, row triggers, claim helpers, table-hardening helpers.
-- Spec: docs/superpowers/specs/2026-10-18-mr-10-contracts-schema-design.md (5.1, 5.2, 7.3, 7.4, 8)
--
-- app.uuid_v7 is adapted from uuidv7_sub_ms in https://github.com/dverite/postgres-uuidv7-sql
-- (renamed, moved to schema app). The upstream license text follows and must appear in all copies.
--
--   Copyright (c) 2024-2025, Daniel Vérité
--
--   Permission to use, copy, modify, and distribute this software and its documentation for any
--   purpose, without fee, and without a written agreement is hereby granted, provided that the
--   above copyright notice and this paragraph and the following two paragraphs appear in all
--   copies.
--
--   In no event shall Daniel Vérité be liable to any party for direct, indirect, special,
--   incidental, or consequential damages, including lost profits, arising out of the use of this
--   software and its documentation, even if Daniel Vérité has been advised of the possibility of
--   such damage.
--
--   Daniel Vérité specifically disclaims any warranties, including, but not limited to, the
--   implied warranties of merchantability and fitness for a particular purpose. The software
--   provided hereunder is on an "AS IS" basis, and Daniel Vérité has no obligations to provide
--   maintenance, support, updates, enhancements, or modifications.

create schema app;

-- Privileges -------------------------------------------------------------------------------
-- Objects created by postgres in public must not be reachable by client roles unless a class
-- grants it explicitly (the platform default grants everything; spec 7.1).
alter default privileges for role postgres in schema public revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public revoke execute on functions from anon, authenticated;
-- Postgres grants EXECUTE on new functions to PUBLIC by default, and a per-schema revoke does not
-- remove that built-in default. Revoke it globally for functions that postgres creates, so every
-- function is executable only where a migration grants it (a deliberate, secure default).
alter default privileges for role postgres revoke execute on functions from public;

grant usage on schema app to authenticated, service_role;

-- UUIDv7 (RFC 9562 method 3: millisecond timestamp, 12 bits of sub-millisecond precision) ---
create function app.uuid_v7(ts timestamptz default clock_timestamp()) returns uuid
language sql volatile parallel safe
as $$
  select encode(
    substring(int8send(floor(t_ms)::int8) from 3) ||
    int2send((7 << 12)::int2 | ((t_ms - floor(t_ms)) * 4096)::int2) ||
    substring(uuid_send(gen_random_uuid()) from 9 for 8),
    'hex')::uuid
  from (select extract(epoch from ts) * 1000 as t_ms) s
$$;

comment on function app.uuid_v7(timestamptz) is
  'UUIDv7 with sub-millisecond ordering. Adapted from uuidv7_sub_ms in dverite/postgres-uuidv7-sql, Copyright (c) 2024-2025 Daniel Verite, PostgreSQL License; the full notice is in the header of the foundations migration.';

grant execute on function app.uuid_v7(timestamptz) to service_role;

-- Claim helpers (spec 7.3). They only read claims; they do not make claims trustworthy (7.5) ---
create function app.current_tenant_id() returns uuid
language sql stable set search_path = ''
as $$
  select case
    when (auth.jwt() ->> 'tenant_id') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    then (auth.jwt() ->> 'tenant_id')::uuid
  end
$$;

-- Fail-closed. An explicit JSON null (all locations) or a list of location ids grants access; an
-- absent key, any other type, or a list with non-string elements grants nothing, not even
-- tenant-level rows (loc is null). A well-formed list that is empty grants no location and no
-- tenant-level row either: a member with no location sees no location-scoped data.
create function app.can_see_location(loc uuid) returns boolean
language sql stable set search_path = ''
as $$
  select case
    when auth.jwt() is null then false
    when jsonb_typeof(auth.jwt() -> 'location_ids') = 'null' then true
    when jsonb_typeof(auth.jwt() -> 'location_ids') = 'array' then
      jsonb_array_length(auth.jwt() -> 'location_ids') > 0
      and not exists (select 1 from jsonb_array_elements(auth.jwt() -> 'location_ids') e
                      where jsonb_typeof(e) <> 'string')
      and (loc is null or (auth.jwt() -> 'location_ids') ? loc::text)
    else false
  end
$$;

create function app.has_all_locations() returns boolean
language sql stable set search_path = ''
as $$
  select coalesce(jsonb_typeof(auth.jwt() -> 'location_ids') = 'null', false)
$$;

grant execute on function app.current_tenant_id(), app.can_see_location(uuid), app.has_all_locations()
  to authenticated;

-- Row triggers -------------------------------------------------------------------------------
create function app.touch_row() returns trigger
language plpgsql set search_path = ''
as $$
begin
  if (to_jsonb(new) ->> 'tenant_id') is distinct from (to_jsonb(old) ->> 'tenant_id') then
    raise exception 'tenant_id is immutable' using errcode = '42501';
  end if;
  new.updated_at := now();
  new.version := old.version + 1;
  return new;
end
$$;

create function app.block_mutation() returns trigger
language plpgsql set search_path = ''
as $$
begin
  raise exception '% is append-only', tg_table_name using errcode = '42501';
end
$$;

-- Table-hardening helpers, called by every table migration (spec 5.1, 6.1) -----------------------
-- Not-blank check on every text column: unspecified values still keep integrity.
create function app.add_text_checks(rel regclass) returns void
language plpgsql set search_path = ''
as $$
declare
  c record;
begin
  for c in
    select a.attname
    from pg_attribute a
    where a.attrelid = rel and a.attnum > 0 and not a.attisdropped
      and a.atttypid in ('text'::regtype, 'character varying'::regtype)
    order by a.attnum
  loop
    execute format('alter table %s add constraint %I check (%I is null or btrim(%I) <> %L)',
                   rel, c.attname || '_not_blank', c.attname, c.attname, '');
  end loop;
end
$$;

-- Records a unit or a note in a column comment; the model generator reads it (spec 5.4).
create function app.tag(rel regclass, tag text, cols text[]) returns void
language plpgsql set search_path = ''
as $$
declare
  col text;
begin
  foreach col in array cols loop
    execute format('comment on column %s.%I is %L', rel, col, tag);
  end loop;
end
$$;

-- Applies an access class to a table (spec 7.2). Modes:
--   tenant       class T   tenant policy
--   tenant_root  class T   the tenant table itself (id = active tenant)
--   location     class L   tenant policy + location column (loc_col)
--   full         class F   tenant policy + explicit all-locations scope
--   parent       class LP  tenant policy + visibility inherited from the parent row
--   backend      class X   RLS on, no policy, no client privilege
create function app.finish_table(
  rel regclass, mode text, loc_col text default null, parent regclass default null, fk_col text default null
) returns void
language plpgsql set search_path = ''
as $$
declare
  relname text;
  cls text;
  expr text;
  tenant_term constant text := 'tenant_id = (select app.current_tenant_id())';
begin
  if mode not in ('tenant', 'tenant_root', 'location', 'full', 'parent', 'backend') then
    raise exception 'unknown access mode %', mode;
  end if;
  if mode = 'location' and loc_col is null then
    raise exception 'mode location needs loc_col';
  end if;
  if mode = 'parent' and (parent is null or fk_col is null) then
    raise exception 'mode parent needs parent and fk_col';
  end if;

  select c.relname into relname from pg_class c where c.oid = rel;

  if exists (select 1 from pg_attribute where attrelid = rel and attname = 'updated_at' and not attisdropped) then
    execute format('create trigger touch_row before update on %s for each row execute function app.touch_row()', rel);
  end if;

  perform app.add_text_checks(rel);

  execute format('alter table %s enable row level security', rel);
  execute format('revoke all on %s from anon, authenticated', rel);

  if mode <> 'backend' then
    execute format('grant select on %s to authenticated', rel);
    expr := case mode
      when 'tenant' then tenant_term
      when 'tenant_root' then 'id = (select app.current_tenant_id())'
      when 'location' then tenant_term || format(' and app.can_see_location(%I)', loc_col)
      when 'full' then tenant_term || ' and app.has_all_locations()'
      when 'parent' then tenant_term || format(
        ' and exists (select 1 from %s p where p.tenant_id = %I.tenant_id and p.id = %I.%I)',
        parent, relname, relname, fk_col)
    end;
    execute format('create policy rls_select on %s for select to authenticated using (%s)', rel, expr);
  end if;

  cls := case mode
    when 'tenant' then 'T' when 'tenant_root' then 'T' when 'location' then 'L'
    when 'full' then 'F' when 'parent' then 'LP' else 'X'
  end;
  execute format('comment on table %s is %L', rel,
                 'rls_class=' || cls || case when loc_col is not null then ';loc_col=' || loc_col else '' end);
end
$$;
