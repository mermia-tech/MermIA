-- Layers: privilege + policy. Data-driven tenant and location isolation over every table
-- (spec 7.2, 10.4). Fixtures are inserted with foreign keys switched off (replica mode) so one
-- generic generator can fill all 40 tables; the integrity of the keys is proven in 40_integrity.
begin;
select * from no_plan();

\set TA '''aaaaaaaa-0000-7000-8000-000000000001'''
\set TB '''bbbbbbbb-0000-7000-8000-000000000002'''

create temp table cls (tbl text primary key, cls text not null, loc_col text);
insert into cls
select c.relname,
       split_part(split_part(obj_description(c.oid, 'pg_class'), ';', 1), '=', 2),
       nullif(split_part(coalesce(split_part(obj_description(c.oid, 'pg_class'), ';', 2), ''), '=', 2), '')
from pg_class c
where c.relnamespace = 'public'::regnamespace and c.relkind = 'r';

-- one generic row generator: required columns get type-based dummies, a few columns are pinned
create function pg_temp.dummy_row(rel regclass, tenant uuid, loc uuid, row_id uuid, pins jsonb default '{}')
returns void language plpgsql as $$
declare
  cols text; vals text; lc text;
begin
  select loc_col into lc from pg_temp.cls where tbl = (select relname from pg_class where oid = rel);
  select string_agg(quote_ident(a.attname), ', ' order by a.attnum),
         string_agg(case
           when pins ? a.attname then pins ->> a.attname
           when a.attname = 'id' and (select relname from pg_class where oid = rel) = 'location' then quote_literal(loc) || '::uuid'
           when a.attname = 'id' then quote_literal(row_id) || '::uuid'
           when a.attname = 'tenant_id' then quote_literal(tenant) || '::uuid'
           when a.attname = lc then quote_literal(loc) || '::uuid'
           when a.attname = 'sha256' then quote_literal(repeat('a', 64))
           when a.attname = 'parser' then quote_literal('sr.test@v1')
           when a.attname = 'code' then quote_literal('ok')
           when a.attname = 'currency' then quote_literal('MXN')
           when t.typtype = 'e' then quote_literal((select enumlabel from pg_enum where enumtypid = t.oid order by enumsortorder limit 1)) || '::' || format_type(a.atttypid, a.atttypmod)
           when t.typcategory = 'A' then quote_literal('{}') || '::' || format_type(a.atttypid, a.atttypmod)
           when t.typname = 'uuid' then 'gen_random_uuid()'
           when t.typname in ('text', 'varchar') then quote_literal('x') || ' || gen_random_uuid()::text'
           when t.typname in ('int2', 'int4', 'int8', 'numeric') then '1'
           when t.typname = 'bool' then 'false'
           when t.typname = 'date' then 'current_date'
           when t.typname = 'timestamptz' then 'now()'
           when t.typname = 'jsonb' then quote_literal('{}') || '::jsonb'
           when t.typname = 'bytea' then quote_literal('\x00') || '::bytea'
           else 'null' end, ', ' order by a.attnum)
    into cols, vals
  from pg_attribute a join pg_type t on t.oid = a.atttypid
  where a.attrelid = rel and a.attnum > 0 and not a.attisdropped
    and (a.attnotnull and not a.atthasdef
         or a.attname in ('id', 'tenant_id')
         or a.attname = lc
         or pins ? a.attname);
  execute format('insert into %s (%s) values (%s)', rel, cols, vals);
end $$;

-- fixtures: tenant A has locations A1 and A2, tenant B has B1
set local session_replication_role = replica;
do $$
declare
  r record;
  ta constant uuid := 'aaaaaaaa-0000-7000-8000-000000000001';
  tb constant uuid := 'bbbbbbbb-0000-7000-8000-000000000002';
  a1 constant uuid := 'a1a1a1a1-0000-7000-8000-000000000001';
  a2 constant uuid := 'a2a2a2a2-0000-7000-8000-000000000002';
  b1 constant uuid := 'b1b1b1b1-0000-7000-8000-000000000001';
  pins_recipe constant jsonb := '{"menu_item_id": "gen_random_uuid()"}';
  pins_line constant jsonb := '{"ingredient_id": "gen_random_uuid()"}';
  p jsonb;
begin
  for r in select * from pg_temp.cls order by tbl loop
    p := case r.tbl when 'recipe' then pins_recipe when 'recipe_line' then pins_line else '{}'::jsonb end;
    if r.tbl = 'tenant' then
      perform pg_temp.dummy_row('public.tenant', ta, null, ta);
      perform pg_temp.dummy_row('public.tenant', tb, null, tb);
    elsif r.cls = 'X' and r.tbl in ('app_user', 'channel_identity', 'consent_log') then
      perform pg_temp.dummy_row(('public.' || r.tbl)::regclass, null, null, gen_random_uuid(), p);
    elsif r.cls = 'L' then
      perform pg_temp.dummy_row(('public.' || r.tbl)::regclass, ta, a1, case r.tbl when 'import_batch' then 'ba000000-0000-7000-8000-0000000000a1' else gen_random_uuid() end::uuid, p);
      perform pg_temp.dummy_row(('public.' || r.tbl)::regclass, ta, a2, case r.tbl when 'import_batch' then 'ba000000-0000-7000-8000-0000000000a2' else gen_random_uuid() end::uuid, p);
      perform pg_temp.dummy_row(('public.' || r.tbl)::regclass, tb, b1, case r.tbl when 'import_batch' then 'ba000000-0000-7000-8000-0000000000b1' else gen_random_uuid() end::uuid, p);
    elsif r.cls = 'LP' then
      perform pg_temp.dummy_row('public.import_issue', ta, null, gen_random_uuid(), jsonb_build_object('batch_id', quote_literal('ba000000-0000-7000-8000-0000000000a1') || '::uuid'));
      perform pg_temp.dummy_row('public.import_issue', ta, null, gen_random_uuid(), jsonb_build_object('batch_id', quote_literal('ba000000-0000-7000-8000-0000000000a2') || '::uuid'));
      perform pg_temp.dummy_row('public.import_issue', tb, null, gen_random_uuid(), jsonb_build_object('batch_id', quote_literal('ba000000-0000-7000-8000-0000000000b1') || '::uuid'));
    else
      perform pg_temp.dummy_row(('public.' || r.tbl)::regclass, ta, null, gen_random_uuid(), p);
      perform pg_temp.dummy_row(('public.' || r.tbl)::regclass, tb, null, gen_random_uuid(), p);
    end if;
  end loop;
end $$;
set local session_replication_role = origin;

-- how many rows does a role see in a table under a given claim set?
create function pg_temp.seen(r text, claims text, tbl text) returns text language plpgsql as $$
declare n bigint;
begin
  execute format('set local role %I', r);
  perform set_config('request.jwt.claims', claims, true);
  begin
    execute format('select count(*) from public.%I', tbl) into n;
    reset role;
    return n::text;
  exception when others then
    reset role;
    return 'ERR ' || sqlstate;
  end;
end $$;

-- counts only the two test tenants' rows, so data already in the database (the seed) is ignored
create function pg_temp.seen_test_tenants(r text, tbl text) returns text language plpgsql as $$
declare n bigint;
begin
  execute format('set local role %I', r);
  execute format('select count(*) from public.%I where tenant_id in (%L, %L)', tbl,
                 'aaaaaaaa-0000-7000-8000-000000000001', 'bbbbbbbb-0000-7000-8000-000000000002') into n;
  reset role;
  return n::text;
end $$;

-- scenarios: name, claims
create temp table scenario (name text primary key, claims text not null);
insert into scenario values
  ('A all',       '{"role":"authenticated","tenant_id":"aaaaaaaa-0000-7000-8000-000000000001","location_ids":null}'),
  ('A centro',    '{"role":"authenticated","tenant_id":"aaaaaaaa-0000-7000-8000-000000000001","location_ids":["a1a1a1a1-0000-7000-8000-000000000001"]}'),
  ('A empty',     '{"role":"authenticated","tenant_id":"aaaaaaaa-0000-7000-8000-000000000001","location_ids":[]}'),
  ('A absent',    '{"role":"authenticated","tenant_id":"aaaaaaaa-0000-7000-8000-000000000001"}'),
  ('A bad type',  '{"role":"authenticated","tenant_id":"aaaaaaaa-0000-7000-8000-000000000001","location_ids":"all"}'),
  ('B all',       '{"role":"authenticated","tenant_id":"bbbbbbbb-0000-7000-8000-000000000002","location_ids":null}'),
  ('no tenant',   '{"role":"authenticated","location_ids":null}'),
  ('bad tenant',  '{"role":"authenticated","tenant_id":"not-a-uuid","location_ids":null}'),
  ('no claims',   '');

-- expected counts per class and scenario (T: 1 row per tenant; L: A has 2, B has 1; LP like L; F: 1 per tenant)
create temp table expected (cls text, name text, n text, primary key (cls, name));
insert into expected values
  ('T','A all','1'),('T','A centro','1'),('T','A empty','1'),('T','A absent','1'),('T','A bad type','1'),('T','B all','1'),('T','no tenant','0'),('T','bad tenant','0'),('T','no claims','0'),
  ('L','A all','2'),('L','A centro','1'),('L','A empty','0'),('L','A absent','0'),('L','A bad type','0'),('L','B all','1'),('L','no tenant','0'),('L','bad tenant','0'),('L','no claims','0'),
  ('LP','A all','2'),('LP','A centro','1'),('LP','A empty','0'),('LP','A absent','0'),('LP','A bad type','0'),('LP','B all','1'),('LP','no tenant','0'),('LP','bad tenant','0'),('LP','no claims','0'),
  ('F','A all','1'),('F','A centro','0'),('F','A empty','0'),('F','A absent','0'),('F','A bad type','0'),('F','B all','1'),('F','no tenant','0'),('F','bad tenant','0'),('F','no claims','0'),
  ('X','A all','ERR 42501'),('X','A centro','ERR 42501'),('X','A empty','ERR 42501'),('X','A absent','ERR 42501'),('X','A bad type','ERR 42501'),('X','B all','ERR 42501'),('X','no tenant','ERR 42501'),('X','bad tenant','ERR 42501'),('X','no claims','ERR 42501');

create temp table result as
select c.tbl, c.cls, s.name as scenario, e.n as expected, pg_temp.seen('authenticated', s.claims, c.tbl) as actual
from cls c join scenario s on true join expected e on e.cls = c.cls and e.name = s.name;

-- the tenant table is its own root: its class is T but a location claim is irrelevant (already in T)
select diag(format('MISMATCH %s [%s] under "%s": expected %s, got %s', tbl, cls, scenario, expected, actual))
from result where expected is distinct from actual;
select is((select count(*) from result where expected is distinct from actual), 0::bigint,
          'authenticated sees exactly the rows its claims allow, in every table and scenario');
select is((select count(*) from result), (select count(*) from cls) * (select count(*) from scenario),
          'the matrix covers all 40 tables and all 9 scenarios');

-- anon is denied at the privilege layer everywhere
select is((select count(*) from cls where pg_temp.seen('anon', '', tbl) is distinct from 'ERR 42501'), 0::bigint,
          'anon is denied on every table');

-- privileged roles see every row (3 rows in L tables and LP, 2 elsewhere; app_user-like tables have 1)
select is((select count(*) from cls where cls in ('T','F') and tbl not in ('tenant') and pg_temp.seen_test_tenants('service_role', tbl) is distinct from '2'), 0::bigint,
          'service_role sees both tenants in tenant-wide and full-scope tables');
select is((select count(*) from cls where cls in ('L','LP') and pg_temp.seen_test_tenants('service_role', tbl) is distinct from '3'), 0::bigint,
          'service_role sees all three location rows in location-scoped tables');
select is(pg_temp.seen('postgres', '', 'sale_ticket'), '3', 'postgres bypasses RLS');

select * from finish();
rollback;
