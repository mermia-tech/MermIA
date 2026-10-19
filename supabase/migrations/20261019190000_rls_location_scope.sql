-- MR-14: cheap location checks in RLS (MR-53 item 7) and a not-blank check that matches the
-- contract's `Text` (MR-53 item 8).
--
-- Item 7. The class-L policy called app.can_see_location(loc_col) per row. The function is not
-- inlined (it sets search_path) and parses the JWT on every call: 3.83 s vs 4.5 ms over 200k
-- rows for a location-limited user. The new policy reads the claim once per statement, through
-- uncorrelated sub-selects (init plans), and compares each row against a uuid[]:
--   (select app.has_all_locations())                        explicit null: every location
--   or (loc is null and (select app.has_location_list()))   tenant-level row, member with a list
--   or loc = any((select app.location_scope_ids()))         listed location
-- Same answers as can_see_location for every claim shape (20_location covers both side by side).
-- can_see_location stays for callers that check a single id.
--
-- Item 8. btrim only strips spaces, so a tab-, newline- or NBSP-only string passed the DB while
-- the contract's `Text` (pattern \S, Unicode White_Space in pydantic-core) rejects it. The check
-- now needs one character outside Unicode White_Space.

-- Location scope helpers ---------------------------------------------------------------------
-- True when location_ids is a non-empty JSON array of strings only: the shapes can_see_location
-- accepts as a list (absent, wrong type, empty or mixed lists grant nothing).
create function app.has_location_list() returns boolean
language sql stable set search_path = ''
as $$
  select coalesce(
    jsonb_typeof(auth.jwt() -> 'location_ids') = 'array'
    and jsonb_array_length(auth.jwt() -> 'location_ids') > 0
    and not exists (select 1 from jsonb_array_elements(auth.jwt() -> 'location_ids') e
                    where jsonb_typeof(e) <> 'string'),
    false)
$$;

-- The listed location ids, or an empty array when the claim is not a valid list. Only strings in
-- canonical lowercase uuid form count: can_see_location compares against loc::text, so an
-- uppercase or brace-wrapped id never matched there and must not match here.
create function app.location_scope_ids() returns uuid[]
language sql stable set search_path = ''
as $$
  select case when app.has_location_list() then coalesce(
    (select array_agg(e::uuid)
     from jsonb_array_elements_text(auth.jwt() -> 'location_ids') e
     where e ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    '{}') else '{}' end
$$;

grant execute on function app.has_location_list(), app.location_scope_ids() to authenticated;

-- Policy expressions -------------------------------------------------------------------------
-- The select policy for an access mode; finish_table and the re-policy below share it.
create function app.rls_select_expr(
  rel regclass, mode text, loc_col text default null, parent regclass default null, fk_col text default null
) returns text
language plpgsql stable set search_path = ''
as $$
declare
  relname text;
  tenant_term constant text := 'tenant_id = (select app.current_tenant_id())';
begin
  select c.relname into relname from pg_class c where c.oid = rel;
  return case mode
    when 'tenant' then tenant_term
    when 'tenant_root' then 'id = (select app.current_tenant_id())'
    when 'location' then tenant_term || format(
      ' and ((select app.has_all_locations())'
      ' or (%1$I is null and (select app.has_location_list()))'
      ' or %1$I = any ((select app.location_scope_ids())::uuid[]))', loc_col)
    when 'full' then tenant_term || ' and (select app.has_all_locations())'
    when 'parent' then tenant_term || format(
      ' and exists (select 1 from %s p where p.tenant_id = %I.tenant_id and p.id = %I.%I)',
      parent, relname, relname, fk_col)
  end;
end
$$;

-- Not-blank check ----------------------------------------------------------------------------
-- At least one character outside Unicode White_Space (what \S means in the contract).
create or replace function app.add_text_checks(rel regclass) returns void
language plpgsql set search_path = ''
as $$
declare
  c record;
  non_space constant text :=
    '[^\t\n\v\f\r \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]';
begin
  for c in
    select a.attname
    from pg_attribute a
    where a.attrelid = rel and a.attnum > 0 and not a.attisdropped
      and a.atttypid in ('text'::regtype, 'character varying'::regtype)
    order by a.attnum
  loop
    execute format('alter table %s drop constraint if exists %I', rel, c.attname || '_not_blank');
    execute format('alter table %s add constraint %I check (%I is null or %I ~ %L)',
                   rel, c.attname || '_not_blank', c.attname, c.attname, non_space);
  end loop;
end
$$;

create or replace function app.finish_table(
  rel regclass, mode text, loc_col text default null, parent regclass default null, fk_col text default null
) returns void
language plpgsql set search_path = ''
as $$
declare
  cls text;
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

  if exists (select 1 from pg_attribute where attrelid = rel and attname = 'updated_at' and not attisdropped) then
    execute format('create trigger touch_row before update on %s for each row execute function app.touch_row()', rel);
  end if;

  perform app.add_text_checks(rel);

  execute format('alter table %s enable row level security', rel);
  execute format('revoke all on %s from anon, authenticated', rel);

  if mode <> 'backend' then
    execute format('grant select on %s to authenticated', rel);
    execute format('create policy rls_select on %s for select to authenticated using (%s)',
                   rel, app.rls_select_expr(rel, mode, loc_col, parent, fk_col));
  end if;

  cls := case mode
    when 'tenant' then 'T' when 'tenant_root' then 'T' when 'location' then 'L'
    when 'full' then 'F' when 'parent' then 'LP' else 'X'
  end;
  execute format('comment on table %s is %L', rel,
                 'rls_class=' || cls || case when loc_col is not null then ';loc_col=' || loc_col else '' end);
end
$$;

-- Existing tables ----------------------------------------------------------------------------
-- Re-create the class L and F policies and every not-blank check. The access class and the
-- location column come from the table comment finish_table wrote.
do $$
declare
  t record;
begin
  for t in
    select c.oid::regclass as rel,
           substring(obj_description(c.oid, 'pg_class') from 'rls_class=([A-Z]+)') as cls,
           substring(obj_description(c.oid, 'pg_class') from 'loc_col=([a-z_]+)') as loc_col
    from pg_class c
    where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
  loop
    perform app.add_text_checks(t.rel);
    if t.cls in ('L', 'F') then
      execute format('drop policy rls_select on %s', t.rel);
      execute format('create policy rls_select on %s for select to authenticated using (%s)', t.rel,
                     app.rls_select_expr(t.rel, case t.cls when 'L' then 'location' else 'full' end, t.loc_col));
    end if;
  end loop;
end
$$;
