-- Layer: integrity. uuid_v7, triggers, constraints (spec 5.2, 8).
begin;
select * from no_plan();

-- app.uuid_v7 (spec 5.2): compatibility, ordering, uniqueness
create temp table gen as select n, app.uuid_v7() as u from generate_series(1, 10000) as n;
select is((select count(*) from gen where substr(u::text, 15, 1) <> '7'), 0::bigint, 'uuid_v7: version nibble is 7');
select is((select count(*) from gen where substr(u::text, 20, 1) not in ('8', '9', 'a', 'b')), 0::bigint, 'uuid_v7: RFC variant bits');
select is((select count(distinct u) from gen), 10000::bigint, 'uuid_v7: unique over 10,000 values');
select is((select count(*) from (select u < lag(u) over (order by n) as inv from gen) s where inv), 0::bigint, 'uuid_v7: no ordering inversions in one statement');
select ok(abs(extract(epoch from now()) - extract(epoch from to_timestamp(('x' || substr(replace((select u::text from gen where n = 1), '-', ''), 1, 12))::bit(48)::bigint / 1000.0))) < 10, 'uuid_v7: embedded timestamp matches the clock');
select is(substr(replace(app.uuid_v7('2026-01-01 00:00:00+00'::timestamptz)::text, '-', ''), 1, 12), lpad(to_hex((extract(epoch from '2026-01-01 00:00:00+00'::timestamptz) * 1000)::bigint), 12, '0'), 'uuid_v7: explicit timestamp argument is honoured');
select ok(obj_description('app.uuid_v7(timestamptz)'::regprocedure, 'pg_proc') like '%PostgreSQL License%', 'uuid_v7: license is recorded on the function');

-- fixtures used by the integrity checks below (inserted as postgres, which bypasses RLS)
insert into public.tenant (id, name) values
  ('aaaaaaaa-0000-7000-8000-000000000001', 'Tenant A'), ('bbbbbbbb-0000-7000-8000-000000000002', 'Tenant B');
insert into public.location (tenant_id, id, name, timezone) values
  ('aaaaaaaa-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001', 'Centro', 'America/Mexico_City'),
  ('aaaaaaaa-0000-7000-8000-000000000001', 'a2a2a2a2-0000-7000-8000-000000000002', 'Polanco', 'America/Mexico_City'),
  ('bbbbbbbb-0000-7000-8000-000000000002', 'b1b1b1b1-0000-7000-8000-000000000001', 'B uno', 'America/Mexico_City');
insert into public.app_user (id, name) values
  ('11111111-1111-4111-8111-111111111111', 'Laura'), ('22222222-2222-4222-8222-222222222222', 'Carlos');

-- row triggers --------------------------------------------------------------------------
update public.location set name = 'Centro 2', updated_at = '2000-01-01' where id = 'a1a1a1a1-0000-7000-8000-000000000001';
select is((select version from public.location where id = 'a1a1a1a1-0000-7000-8000-000000000001'), 2, 'touch_row increments version');
select is((select updated_at from public.location where id = 'a1a1a1a1-0000-7000-8000-000000000001'), now(), 'touch_row sets updated_at to now()');
select throws_ok($$update public.location set tenant_id = 'bbbbbbbb-0000-7000-8000-000000000002' where id = 'a1a1a1a1-0000-7000-8000-000000000001'$$,
  '42501', 'tenant_id is immutable', 'tenant_id cannot change');

-- text integrity (spec 5.1) ----------------------------------------------------------------
select throws_ok($$insert into public.tenant (name) values ('   ')$$, '23514', null, 'blank required text is rejected');
select throws_ok($$insert into public.tenant (name, plan) values ('X', '')$$, '23514', null, 'blank optional text is rejected');
select lives_ok($$insert into public.tenant (name, plan) values ('X', null)$$, 'null optional text is allowed');
select throws_ok($$insert into public.app_user (name, phone_e164) values ('P', '5512345678')$$, '23514', null, 'phone must be E.164');
select lives_ok($$insert into public.app_user (name, phone_e164) values ('P', '+5215512345678')$$, 'valid E.164 phone');

-- membership scope (spec 5.7, 7.5.10) ---------------------------------------------------------
insert into public.membership (tenant_id, user_id, role)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '11111111-1111-4111-8111-111111111111', 'manager');
select is((select location_ids from public.membership where user_id = '11111111-1111-4111-8111-111111111111'), '{}'::uuid[], 'a membership without a stated scope has an empty location list');
select is((select all_locations from public.membership where user_id = '11111111-1111-4111-8111-111111111111'), false, 'a membership without a stated scope is not all-locations');
select throws_ok($$insert into public.membership (tenant_id, user_id, role, location_ids)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '22222222-2222-4222-8222-222222222222', 'owner', null)$$,
  '23514', null, 'a null scope without the explicit flag is rejected');
select throws_ok($$insert into public.membership (tenant_id, user_id, role, location_ids, all_locations)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '22222222-2222-4222-8222-222222222222', 'owner', array['a1a1a1a1-0000-7000-8000-000000000001']::uuid[], true)$$,
  '23514', null, 'the all-locations flag with a list is rejected');
select lives_ok($$insert into public.membership (tenant_id, user_id, role, location_ids, all_locations)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '22222222-2222-4222-8222-222222222222', 'owner', null, true)$$,
  'explicit full scope needs both the null and the flag');
select throws_ok($$update public.membership set location_ids = array['b1b1b1b1-0000-7000-8000-000000000001']::uuid[]
  where user_id = '11111111-1111-4111-8111-111111111111'$$,
  '23514', null, 'a location of another tenant is rejected');
select throws_ok($$update public.membership set location_ids = array[null]::uuid[]
  where user_id = '11111111-1111-4111-8111-111111111111'$$,
  '23514', null, 'a null element in the list is rejected');
select lives_ok($$update public.membership set location_ids = array['a1a1a1a1-0000-7000-8000-000000000001']::uuid[]
  where user_id = '11111111-1111-4111-8111-111111111111'$$, 'a location of the same tenant is accepted');
select throws_ok($$insert into public.membership (tenant_id, user_id, role)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '11111111-1111-4111-8111-111111111111', 'support')$$,
  '23505', null, 'one membership per user and tenant');

-- identity uniqueness ---------------------------------------------------------------------------
insert into public.channel_identity (user_id, channel, external_id) values ('11111111-1111-4111-8111-111111111111', 'whatsapp', '5215500000001');
select throws_ok($$insert into public.channel_identity (user_id, channel, external_id) values ('22222222-2222-4222-8222-222222222222', 'whatsapp', '5215500000001')$$,
  '23505', null, 'a sender id maps to one user per channel');

-- ingestion (spec 5.7) ---------------------------------------------------------------------------------
insert into public.source (id, tenant_id, location_id, kind) values
  ('5c5c5c5c-0000-7000-8000-00000000000a', 'aaaaaaaa-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001', 'sr_report'),
  ('5c5c5c5c-0000-7000-8000-00000000000b', 'bbbbbbbb-0000-7000-8000-000000000002', 'b1b1b1b1-0000-7000-8000-000000000001', 'sr_report');
insert into public.raw_file (tenant_id, storage_path, sha256)
  values ('aaaaaaaa-0000-7000-8000-000000000001', 'raw/a1.xlsx', repeat('a', 64));
select throws_ok($$insert into public.raw_file (tenant_id, storage_path, sha256) values ('aaaaaaaa-0000-7000-8000-000000000001', 'raw/a2.xlsx', repeat('a', 64))$$,
  '23505', null, 'the same file twice in one tenant is rejected');
select lives_ok($$insert into public.raw_file (tenant_id, storage_path, sha256) values ('bbbbbbbb-0000-7000-8000-000000000002', 'raw/b1.xlsx', repeat('a', 64))$$,
  'the same file in another tenant is allowed');
select throws_ok($$insert into public.raw_file (tenant_id, storage_path, sha256) values ('aaaaaaaa-0000-7000-8000-000000000001', 'raw/a3.xlsx', 'not-a-hash')$$,
  '23514', null, 'sha256 must be 64 lowercase hex characters');
select throws_ok($$insert into public.raw_file (tenant_id, storage_path, sha256, size) values ('aaaaaaaa-0000-7000-8000-000000000001', 'raw/a4.xlsx', repeat('b', 64), -1)$$,
  '23514', null, 'size cannot be negative');

select lives_ok($$insert into public.import_batch (tenant_id, source_id, location_id, parser, slice_key, status)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '5c5c5c5c-0000-7000-8000-00000000000a', 'a1a1a1a1-0000-7000-8000-000000000001', 'sr.productos_vendidos@v1', 'slice-1', 'applied')$$,
  'first applied batch of a slice');
select throws_ok($$insert into public.import_batch (tenant_id, source_id, location_id, parser, slice_key, status)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '5c5c5c5c-0000-7000-8000-00000000000a', 'a1a1a1a1-0000-7000-8000-000000000001', 'sr.productos_vendidos@v1', 'slice-1', 'applied')$$,
  '23505', null, 'a second applied batch for the same slice is rejected');
select lives_ok($$insert into public.import_batch (tenant_id, source_id, location_id, parser, slice_key, status)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '5c5c5c5c-0000-7000-8000-00000000000a', 'a1a1a1a1-0000-7000-8000-000000000001', 'sr.productos_vendidos@v1', 'slice-1', 'superseded')$$,
  'superseded batches of the same slice are allowed');
select lives_ok($$insert into public.import_batch (tenant_id, source_id, location_id, parser, slice_key, status)
  values ('bbbbbbbb-0000-7000-8000-000000000002', '5c5c5c5c-0000-7000-8000-00000000000b', 'b1b1b1b1-0000-7000-8000-000000000001', 'sr.productos_vendidos@v1', 'slice-1', 'applied')$$,
  'the same slice key in another tenant is independent');
select throws_ok($$insert into public.import_batch (tenant_id, source_id, parser, slice_key)
  values ('bbbbbbbb-0000-7000-8000-000000000002', '5c5c5c5c-0000-7000-8000-00000000000a', 'sr.productos_vendidos@v1', 'slice-x')$$,
  '23503', null, 'a batch cannot use another tenant''s source (composite FK)');
select throws_ok($$insert into public.import_batch (tenant_id, source_id, parser, slice_key)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '5c5c5c5c-0000-7000-8000-00000000000a', 'Not A Parser', 'slice-y')$$,
  '23514', null, 'parser must look like name@vN');
select throws_ok($$insert into public.import_batch (tenant_id, source_id, parser, slice_key, status)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '5c5c5c5c-0000-7000-8000-00000000000a', 'sr.x@v1', 'slice-z', 'archived')$$,
  '22P02', null, 'an unknown batch status is rejected');

insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key)
  values ('ba7c0000-0000-7000-8000-000000000001', 'aaaaaaaa-0000-7000-8000-000000000001', '5c5c5c5c-0000-7000-8000-00000000000a', 'a1a1a1a1-0000-7000-8000-000000000001', 'sr.x@v1', 'slice-issue');
select lives_ok($$insert into public.import_issue (tenant_id, batch_id, severity, code, message_es)
  values ('aaaaaaaa-0000-7000-8000-000000000001', 'ba7c0000-0000-7000-8000-000000000001', 'warning', 'period_mismatch', 'El periodo no coincide.')$$,
  'a valid import issue');
select throws_ok($$insert into public.import_issue (tenant_id, batch_id, severity, code, message_es)
  values ('aaaaaaaa-0000-7000-8000-000000000001', 'ba7c0000-0000-7000-8000-000000000001', 'fatal', 'x', 'y')$$,
  '22P02', null, 'severity is info, warning or error');
select throws_ok($$insert into public.import_issue (tenant_id, batch_id, severity, code, message_es)
  values ('aaaaaaaa-0000-7000-8000-000000000001', 'ba7c0000-0000-7000-8000-000000000001', 'error', 'Bad Code', 'y')$$,
  '23514', null, 'issue code format');
select throws_ok($$insert into public.import_issue (tenant_id, batch_id, severity, code, message_es)
  values ('bbbbbbbb-0000-7000-8000-000000000002', 'ba7c0000-0000-7000-8000-000000000001', 'info', 'ok', 'y')$$,
  '23503', null, 'an issue cannot point at another tenant''s batch');

select * from finish();
rollback;
