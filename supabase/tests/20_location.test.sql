-- Layer: policy helpers. Claim semantics for tenant_id and location_ids (spec 7.3, 7.5.10).
begin;
select * from no_plan();

create function pg_temp.eval(claims text, expr text) returns text language plpgsql as $$
declare r text;
begin
  execute 'set local role authenticated';
  perform set_config('request.jwt.claims', claims, true);
  begin
    execute 'select (' || expr || ')::text' into r;
  exception when others then
    r := 'ERR ' || sqlstate;
  end;
  reset role;
  return r;
end $$;


-- can_see_location --------------------------------------------------------
select is(pg_temp.eval('{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000001","location_ids":null}', $q$app.can_see_location('a1a1a1a1-0000-7000-8000-000000000001'::uuid)$q$), 'true', 'explicit null sees every location');
select is(pg_temp.eval('{"location_ids":["a1a1a1a1-0000-7000-8000-000000000001"]}', $q$app.can_see_location('a1a1a1a1-0000-7000-8000-000000000001'::uuid)$q$), 'true', 'listed location is visible');
select is(pg_temp.eval('{"location_ids":["a1a1a1a1-0000-7000-8000-000000000001"]}', $q$app.can_see_location('a2a2a2a2-0000-7000-8000-000000000002'::uuid)$q$), 'false', 'unlisted location is not visible');
select is(pg_temp.eval('{"location_ids":[]}', $q$app.can_see_location('a1a1a1a1-0000-7000-8000-000000000001'::uuid)$q$), 'false', 'empty list sees nothing');
select is(pg_temp.eval('{"location_ids":"a1a1a1a1-0000-7000-8000-000000000001"}', $q$app.can_see_location('a1a1a1a1-0000-7000-8000-000000000001'::uuid)$q$), 'false', 'wrong type (string) sees nothing');
select is(pg_temp.eval('{"location_ids":{"a":1}}', $q$app.can_see_location('a1a1a1a1-0000-7000-8000-000000000001'::uuid)$q$), 'false', 'wrong type (object) sees nothing');
select is(pg_temp.eval('{"location_ids":[1,2]}', $q$app.can_see_location('a1a1a1a1-0000-7000-8000-000000000001'::uuid)$q$), 'false', 'array of numbers sees nothing');
select is(pg_temp.eval('{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000001"}', $q$app.can_see_location('a1a1a1a1-0000-7000-8000-000000000001'::uuid)$q$), 'false', 'absent key sees nothing (fail-closed)');
select is(pg_temp.eval('', $q$app.can_see_location('a1a1a1a1-0000-7000-8000-000000000001'::uuid)$q$), 'false', 'no claims at all sees nothing');
select is(pg_temp.eval('{"location_ids":null}', 'app.can_see_location(null::uuid)'), 'true', 'explicit null sees tenant-level rows');
select is(pg_temp.eval('{"location_ids":["a1a1a1a1-0000-7000-8000-000000000001"]}', 'app.can_see_location(null::uuid)'), 'true', 'a member with a location sees tenant-level rows');
select is(pg_temp.eval('{"location_ids":[]}', 'app.can_see_location(null::uuid)'), 'false', 'a member with no location sees no tenant-level row');
select is(pg_temp.eval('{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000001"}', 'app.can_see_location(null::uuid)'), 'false', 'an absent key sees no tenant-level row');
select is(pg_temp.eval('{"location_ids":"x"}', 'app.can_see_location(null::uuid)'), 'false', 'a wrong type sees no tenant-level row');
select is(pg_temp.eval('{"location_ids":[1,2]}', 'app.can_see_location(null::uuid)'), 'false', 'a list of numbers sees no tenant-level row');
select is(pg_temp.eval('', 'app.can_see_location(null::uuid)'), 'false', 'no claims sees no tenant-level row');

-- has_all_locations ---------------------------------------------------------
select is(pg_temp.eval('{"location_ids":null}', 'app.has_all_locations()'), 'true', 'explicit null means all locations');
select is(pg_temp.eval('{"location_ids":["a1a1a1a1-0000-7000-8000-000000000001"]}', 'app.has_all_locations()'), 'false', 'a list is not full scope');
select is(pg_temp.eval('{"location_ids":[]}', 'app.has_all_locations()'), 'false', 'empty list is not full scope');
select is(pg_temp.eval('{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000001"}', 'app.has_all_locations()'), 'false', 'absent key is not full scope');
select is(pg_temp.eval('', 'app.has_all_locations()'), 'false', 'no claims is not full scope');
select is(pg_temp.eval('{"location_ids":"null"}', 'app.has_all_locations()'), 'false', 'the string "null" is not full scope');

-- current_tenant_id -----------------------------------------------------------
select is(pg_temp.eval('{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000001"}', 'app.current_tenant_id()'), 'aaaaaaaa-0000-7000-8000-000000000001', 'valid tenant claim');
select is(pg_temp.eval('{"tenant_id":"AAAAAAAA-0000-7000-8000-000000000001"}', 'app.current_tenant_id()'), 'aaaaaaaa-0000-7000-8000-000000000001', 'upper-case uuid is accepted and normalised');
select is(pg_temp.eval('{"tenant_id":"not-a-uuid"}', 'app.current_tenant_id()'), null, 'malformed tenant claim yields null, never an error');
select is(pg_temp.eval('{"tenant_id":123}', 'app.current_tenant_id()'), null, 'numeric tenant claim yields null');
select is(pg_temp.eval('{}', 'app.current_tenant_id()'), null, 'missing tenant claim yields null');
select is(pg_temp.eval('', 'app.current_tenant_id()'), null, 'no claims yields null');

-- Real rows with real keys: location-scoped tables, parent-inherited issues, full-scope tables,
-- hidden columns (spec 7.2.2, 7.2.5). Inserted as postgres, read as authenticated.
insert into public.tenant (id, name) values
  ('aaaaaaaa-0000-7000-8000-000000000001', 'Tenant A'), ('bbbbbbbb-0000-7000-8000-000000000002', 'Tenant B');
insert into public.location (tenant_id, id, name, timezone) values
  ('aaaaaaaa-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001', 'Centro', 'America/Mexico_City'),
  ('aaaaaaaa-0000-7000-8000-000000000001', 'a2a2a2a2-0000-7000-8000-000000000002', 'Polanco', 'America/Mexico_City'),
  ('bbbbbbbb-0000-7000-8000-000000000002', 'b1b1b1b1-0000-7000-8000-000000000001', 'B uno', 'America/Mexico_City');
insert into public.source (id, tenant_id, location_id, kind, config, api_key_hash) values
  ('5c5c5c5c-0000-7000-8000-00000000000a', 'aaaaaaaa-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001', 'sr_report', '{"secret":"s"}', 'h1'),
  ('5c5c5c5c-0000-7000-8000-00000000000c', 'aaaaaaaa-0000-7000-8000-000000000001', null, 'cfdi', '{"secret":"s"}', 'h2'),
  ('5c5c5c5c-0000-7000-8000-00000000000b', 'bbbbbbbb-0000-7000-8000-000000000002', 'b1b1b1b1-0000-7000-8000-000000000001', 'sr_report', '{}', 'h3');
insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key) values
  ('ba7c0000-0000-7000-8000-0000000000a1', 'aaaaaaaa-0000-7000-8000-000000000001', '5c5c5c5c-0000-7000-8000-00000000000a', 'a1a1a1a1-0000-7000-8000-000000000001', 'sr.x@v1', 'k1'),
  ('ba7c0000-0000-7000-8000-0000000000a2', 'aaaaaaaa-0000-7000-8000-000000000001', '5c5c5c5c-0000-7000-8000-00000000000a', 'a2a2a2a2-0000-7000-8000-000000000002', 'sr.x@v1', 'k2'),
  ('ba7c0000-0000-7000-8000-0000000000a3', 'aaaaaaaa-0000-7000-8000-000000000001', '5c5c5c5c-0000-7000-8000-00000000000c', null, 'sr.x@v1', 'k3');
insert into public.import_issue (tenant_id, batch_id, severity, code, message_es) values
  ('aaaaaaaa-0000-7000-8000-000000000001', 'ba7c0000-0000-7000-8000-0000000000a1', 'info', 'centro_issue', 'Aviso de Centro'),
  ('aaaaaaaa-0000-7000-8000-000000000001', 'ba7c0000-0000-7000-8000-0000000000a2', 'info', 'polanco_issue', 'Aviso de Polanco'),
  ('aaaaaaaa-0000-7000-8000-000000000001', 'ba7c0000-0000-7000-8000-0000000000a3', 'info', 'tenant_issue', 'Aviso del tenant');
insert into public.pending_change (tenant_id, kind, proposed_via) values ('aaaaaaaa-0000-7000-8000-000000000001', 'ingredient_price.set', 'agent');
insert into public.audit_log (tenant_id, actor_kind, action) values ('aaaaaaaa-0000-7000-8000-000000000001', 'system', 'seed');

create function pg_temp.rows(claims text, q text) returns text language plpgsql as $$
declare r text;
begin
  execute 'set local role authenticated';
  perform set_config('request.jwt.claims', claims, true);
  begin
    execute 'select coalesce(string_agg(x::text, '','' order by x::text), ''<none>'') from (' || q || ') s(x)' into r;
  exception when others then
    r := 'ERR ' || sqlstate;
  end;
  reset role;
  return r;
end $$;

\set ALLA '''{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000001","location_ids":null}'''
\set CENTRO '''{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000001","location_ids":["a1a1a1a1-0000-7000-8000-000000000001"]}'''
\set ABSENT '''{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000001"}'''
\set EMPTY_LIST '''{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000001","location_ids":[]}'''

-- parent-inherited visibility (class LP)
select is(pg_temp.rows(:ALLA, 'select code from public.import_issue'), 'centro_issue,polanco_issue,tenant_issue', 'LP: all-locations scope reads every issue');
select is(pg_temp.rows(:CENTRO, 'select code from public.import_issue'), 'centro_issue,tenant_issue', 'LP: a Centro-only member reads Centro issues and tenant-level issues');
select is(pg_temp.rows(:ABSENT, 'select code from public.import_issue'), '<none>', 'LP: an absent location claim reads no issue');
select is(pg_temp.rows(:EMPTY_LIST, 'select code from public.import_issue'), '<none>', 'LP: an empty list reads no issue');
select is(pg_temp.rows(:CENTRO, 'select i.code from public.import_issue i join public.import_batch b on b.id = i.batch_id'), 'centro_issue,tenant_issue', 'LP: a join through the batch cannot widen the result');

-- location-scoped tables (class L)
select is(pg_temp.rows(:CENTRO, 'select name from public.location'), 'Centro', 'L: a Centro-only member sees only its location');
select is(pg_temp.rows(:ALLA, 'select name from public.location'), 'Centro,Polanco', 'L: all-locations scope sees both locations of the tenant, never another tenant''s');
select is(pg_temp.rows(:CENTRO, 'select slice_key from public.import_batch'), 'k1,k3', 'L: a Centro-only member sees Centro batches and tenant-level batches');
select is(pg_temp.rows(:ABSENT, 'select slice_key from public.import_batch'), '<none>', 'L: absent location claim sees no batch');

-- hidden columns of source (A1)
select is(pg_temp.rows(:CENTRO, 'select kind from public.source'), 'cfdi,sr_report', 'source: safe columns are readable, rows follow the location filter');
select is(pg_temp.rows(:CENTRO, 'select config from public.source'), 'ERR 42501', 'source.config is not readable');
select is(pg_temp.rows(:CENTRO, 'select api_key_hash from public.source'), 'ERR 42501', 'source.api_key_hash is not readable');
select is(pg_temp.rows(:CENTRO, 'select * from public.source'), 'ERR 42501', 'select * on source is refused');
select is(pg_temp.rows(:CENTRO, 'select row_to_json(s)::text from public.source s'), 'ERR 42501', 'row_to_json over source is refused');
select is(pg_temp.rows(:ALLA, 'select count(*)::text from public.source'), '2', 'counting sources works without exposing columns');

-- full-scope tables (class F)
select is(pg_temp.rows(:ALLA, 'select kind from public.pending_change'), 'ingredient_price.set', 'F: explicit null scope reads pending changes');
select is(pg_temp.rows(:CENTRO, 'select kind from public.pending_change'), '<none>', 'F: a Centro-only member reads no pending change');
select is(pg_temp.rows(:ABSENT, 'select kind from public.pending_change'), '<none>', 'F: absent scope reads no pending change');
select is(pg_temp.rows(:ALLA, 'select action from public.audit_log'), 'seed', 'F: explicit null scope reads the audit log');
select is(pg_temp.rows(:CENTRO, 'select action from public.audit_log'), '<none>', 'F: a Centro-only member reads no audit row');

-- shared catalog with and without a location (class L, spec 7.2.2) ---------------------------------------
insert into public.staff (tenant_id, location_id, display_name) values
  ('aaaaaaaa-0000-7000-8000-000000000001', 'a2a2a2a2-0000-7000-8000-000000000002', 'Pedro'),
  ('aaaaaaaa-0000-7000-8000-000000000001', null, 'Juan');
insert into public.menu_item (tenant_id, location_id, name) values
  ('aaaaaaaa-0000-7000-8000-000000000001', 'a2a2a2a2-0000-7000-8000-000000000002', 'Platillo de Polanco'),
  ('aaaaaaaa-0000-7000-8000-000000000001', null, 'Platillo compartido');
insert into public.menu_category (tenant_id, location_id, name) values
  ('aaaaaaaa-0000-7000-8000-000000000001', 'a2a2a2a2-0000-7000-8000-000000000002', 'Categoria de Polanco'),
  ('aaaaaaaa-0000-7000-8000-000000000001', null, 'Categoria compartida');

select is(pg_temp.rows(:CENTRO, 'select display_name from public.staff'), 'Juan', 'staff: a Centro-only member does not read Polanco staff, only tenant-level staff');
select is(pg_temp.rows(:ALLA, 'select display_name from public.staff'), 'Juan,Pedro', 'staff: all-locations scope reads both');
select is(pg_temp.rows(:ABSENT, 'select display_name from public.staff'), '<none>', 'staff: an absent claim reads none, not even tenant-level rows');
select is(pg_temp.rows(:EMPTY_LIST, 'select display_name from public.staff'), '<none>', 'staff: an empty list reads none');
select is(pg_temp.rows(:CENTRO, 'select name from public.menu_item'), 'Platillo compartido', 'menu_item: shared items are visible, other locations'' items are not');
select is(pg_temp.rows(:ALLA, 'select name from public.menu_item'), 'Platillo compartido,Platillo de Polanco', 'menu_item: all-locations scope reads both');
select is(pg_temp.rows(:CENTRO, 'select name from public.menu_category'), 'Categoria compartida', 'menu_category: shared categories are visible, other locations'' are not');
select is(pg_temp.rows(:EMPTY_LIST, 'select name from public.menu_category'), '<none>', 'menu_category: an empty list reads none');

select * from finish();
rollback;
