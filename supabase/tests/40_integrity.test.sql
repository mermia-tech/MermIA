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
-- MR-14: whitespace other than spaces is blank too, as in the contract's Text (\S)
select throws_ok($$insert into public.tenant (name) values (E'\t\n\r')$$, '23514', null, 'tab/newline-only text is rejected');
select throws_ok($$insert into public.tenant (name) values (U&'\00A0\3000\2009')$$, '23514', null, 'NBSP/ideographic-space-only text is rejected');
select lives_ok($$insert into public.tenant (name) values (U&' \00A0x')$$, 'text with one visible character is accepted');
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

-- catalog and sales (spec 5.7) ---------------------------------------------------------------------------
insert into public.staff (id, tenant_id, display_name) values ('57aff000-0000-7000-8000-000000000001', 'aaaaaaaa-0000-7000-8000-000000000001', 'Juan');
insert into public.menu_item (id, tenant_id, name) values ('3e100000-0000-7000-8000-000000000001', 'aaaaaaaa-0000-7000-8000-000000000001', 'Taco al pastor');
insert into public.sale_ticket (id, tenant_id, location_id, source_id, batch_id, external_id, business_date, status, subtotal, total)
  values ('71c4e700-0000-7000-8000-000000000001', 'aaaaaaaa-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001',
          '5c5c5c5c-0000-7000-8000-00000000000a', 'ba7c0000-0000-7000-8000-000000000001', 'T-1', '2026-10-12', 'paid', 10000, 11600);
select lives_ok($$insert into public.sale_line (tenant_id, ticket_id, location_id, source_id, batch_id, menu_item_id, qty, unit_price, net)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '71c4e700-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001',
          '5c5c5c5c-0000-7000-8000-00000000000a', 'ba7c0000-0000-7000-8000-000000000001', '3e100000-0000-7000-8000-000000000001', 2, 5000, 10000)$$,
  'a line in its ticket''s location');
select throws_ok($$insert into public.sale_line (tenant_id, ticket_id, location_id, source_id, batch_id, menu_item_id, qty, unit_price, net)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '71c4e700-0000-7000-8000-000000000001', 'a2a2a2a2-0000-7000-8000-000000000002',
          '5c5c5c5c-0000-7000-8000-00000000000a', 'ba7c0000-0000-7000-8000-000000000001', '3e100000-0000-7000-8000-000000000001', 1, 5000, 5000)$$,
  '23503', null, 'a line cannot carry a different location than its ticket');
select throws_ok($$insert into public.payment (tenant_id, ticket_id, location_id, source_id, batch_id, method, amount)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '71c4e700-0000-7000-8000-000000000001', 'a2a2a2a2-0000-7000-8000-000000000002',
          '5c5c5c5c-0000-7000-8000-00000000000a', 'ba7c0000-0000-7000-8000-000000000001', 'cash', 11600)$$,
  '23503', null, 'a payment cannot carry a different location than its ticket');
select throws_ok($$insert into public.sale_line (tenant_id, ticket_id, location_id, source_id, batch_id, menu_item_id, qty, unit_price, net)
  values ('bbbbbbbb-0000-7000-8000-000000000002', '71c4e700-0000-7000-8000-000000000001', 'b1b1b1b1-0000-7000-8000-000000000001',
          '5c5c5c5c-0000-7000-8000-00000000000b', 'ba7c0000-0000-7000-8000-000000000001', '3e100000-0000-7000-8000-000000000001', 1, 5000, 5000)$$,
  '23503', null, 'a line cannot attach to another tenant''s ticket');
select throws_ok($$update public.sale_ticket set currency = 'mxn' where id = '71c4e700-0000-7000-8000-000000000001'$$,
  '23514', null, 'currency must be three upper-case letters');
select throws_ok($$insert into public.menu_item_price (tenant_id, menu_item_id, location_id, price_gross, effective_from, effective_to)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '3e100000-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001', 5000, '2026-10-12', '2026-10-01')$$,
  '23514', null, 'a price cannot end before it starts');
select throws_ok($$insert into public.item_sales_agg (tenant_id, location_id, source_id, batch_id, menu_item_id, period_from, period_to, units, gross, discount, net)
  values ('aaaaaaaa-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001', '5c5c5c5c-0000-7000-8000-00000000000a', 'ba7c0000-0000-7000-8000-000000000001',
          '3e100000-0000-7000-8000-000000000001', '2026-10-12', '2026-10-11', 1, 1, 0, 1)$$,
  '23514', null, 'a period cannot end before it starts');
select lives_ok($$insert into public.daily_sales_agg (tenant_id, location_id, source_id, batch_id, business_date, net_sales, cancellations_count)
  values ('aaaaaaaa-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001', '5c5c5c5c-0000-7000-8000-00000000000a', 'ba7c0000-0000-7000-8000-000000000001',
          '2026-10-12', 3188000, 2)$$,
  'a daily row may report the cancellation count without the amount');
select is((select cancellations_amount from public.daily_sales_agg where tenant_id = 'aaaaaaaa-0000-7000-8000-000000000001' limit 1), null, 'an unreported amount stays null, not zero');

-- control tables (spec 5.7, 7.2.6) ---------------------------------------------------------------------------
select throws_ok($$insert into public.pending_change (tenant_id, kind, proposed_via)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '  ', 'agent')$$, '23514', null, 'pending_change.kind cannot be blank');
select throws_ok($$insert into public.pending_change (tenant_id, proposed_via)
  values ('aaaaaaaa-0000-7000-8000-000000000001', 'agent')$$, '23502', null, 'pending_change.kind is required');
select lives_ok($$insert into public.pending_change (id, tenant_id, kind, target_type, proposed_via)
  values ('9c000000-0000-7000-8000-000000000001', 'aaaaaaaa-0000-7000-8000-000000000001', 'ingredient_price.set', 'ingredient', 'agent')$$,
  'a pending change defaults to status pending');
select is((select status::text from public.pending_change where id = '9c000000-0000-7000-8000-000000000001'), 'pending', 'default status is pending');

insert into public.audit_log (id, tenant_id, actor_kind, action, pending_change_id)
  values ('a0d17000-0000-7000-8000-000000000001', 'aaaaaaaa-0000-7000-8000-000000000001', 'agent', 'proposed', '9c000000-0000-7000-8000-000000000001');
select throws_ok($$update public.audit_log set action = 'x'$$, '42501', 'audit_log is append-only', 'audit_log rows cannot be updated, even by the owner role');
select throws_ok($$delete from public.audit_log$$, '42501', 'audit_log is append-only', 'audit_log rows cannot be deleted, even by the owner role');
select throws_ok($$truncate public.audit_log$$, '42501', 'audit_log is append-only', 'audit_log cannot be truncated, even by the owner role');
select throws_ok($$insert into public.audit_log (tenant_id, actor_kind, action, pending_change_id)
  values ('bbbbbbbb-0000-7000-8000-000000000002', 'agent', 'x', '9c000000-0000-7000-8000-000000000001')$$,
  '23503', null, 'an audit row cannot reference another tenant''s pending change');
select throws_ok($$insert into public.audit_log (tenant_id, actor_kind) values ('aaaaaaaa-0000-7000-8000-000000000001', 'user')$$,
  '23502', null, 'an audit row needs an action');

select lives_ok($$insert into public.conversation (tenant_id, user_id, channel) values ('aaaaaaaa-0000-7000-8000-000000000001', '11111111-1111-4111-8111-111111111111', 'whatsapp')$$,
  'a conversation per user and channel');
select throws_ok($$insert into public.conversation (tenant_id, user_id, channel) values ('aaaaaaaa-0000-7000-8000-000000000001', '11111111-1111-4111-8111-111111111111', 'whatsapp')$$,
  '23505', null, 'only one conversation per user, channel and tenant');
select throws_ok($$insert into public.llm_usage (tenant_id, route, input_tokens) values ('aaaaaaaa-0000-7000-8000-000000000001', 'haiku', -5)$$,
  '23514', null, 'token counts cannot be negative');
select throws_ok($$insert into public.llm_usage (tenant_id, route) values ('aaaaaaaa-0000-7000-8000-000000000001', 'gpt')$$,
  '22P02', null, 'llm route is template, haiku, sonnet or fallback');
select throws_ok($$insert into public.report_run (tenant_id, kind, period_from, period_to) values ('aaaaaaaa-0000-7000-8000-000000000001', 'weekly', '2026-10-12', '2026-10-05')$$,
  '23514', null, 'a report period cannot end before it starts');
select throws_ok($$insert into public.message_log (tenant_id, wa_message_id, direction, pricing_category) values ('aaaaaaaa-0000-7000-8000-000000000001', 'wamid.1', 'out', 'premium')$$,
  '22P02', null, 'pricing category is one of the four Meta categories');

-- costing and metrics (spec 5.7) ----------------------------------------------------------------------------
insert into public.ingredient (id, tenant_id, name, base_unit) values ('1a000000-0000-7000-8000-000000000001', 'aaaaaaaa-0000-7000-8000-000000000001', 'Carne al pastor', 'g');
insert into public.supplier (id, tenant_id, name, kind) values ('50000000-0000-7000-8000-000000000001', 'aaaaaaaa-0000-7000-8000-000000000001', 'Carnes SA', 'cfdi');
select is((select default_yield_pct from public.ingredient where id = '1a000000-0000-7000-8000-000000000001'), 100::numeric, 'default yield is 100 percent points');

select throws_ok($$insert into public.recipe (tenant_id, recipe_version) values ('aaaaaaaa-0000-7000-8000-000000000001', 1)$$,
  '23514', null, 'a recipe needs a dish or a produced ingredient');
select throws_ok($$insert into public.recipe (tenant_id, recipe_version, menu_item_id, produces_ingredient_id)
  values ('aaaaaaaa-0000-7000-8000-000000000001', 1, '3e100000-0000-7000-8000-000000000001', '1a000000-0000-7000-8000-000000000001')$$,
  '23514', null, 'a recipe cannot be both a dish recipe and a sub-recipe');
insert into public.recipe (id, tenant_id, recipe_version, menu_item_id) values ('4ec10000-0000-7000-8000-000000000001', 'aaaaaaaa-0000-7000-8000-000000000001', 1, '3e100000-0000-7000-8000-000000000001');
select is((select status::text from public.recipe where id = '4ec10000-0000-7000-8000-000000000001'), 'draft', 'recipes start as draft');
select throws_ok($$insert into public.recipe_line (tenant_id, recipe_id, qty_base) values ('aaaaaaaa-0000-7000-8000-000000000001', '4ec10000-0000-7000-8000-000000000001', 100)$$,
  '23514', null, 'a recipe line needs an ingredient or a sub-recipe');
select throws_ok($$insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, sub_recipe_id, qty_base)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '4ec10000-0000-7000-8000-000000000001', '1a000000-0000-7000-8000-000000000001', '4ec10000-0000-7000-8000-000000000001', 100)$$,
  '23514', null, 'a recipe line cannot have both');
select lives_ok($$insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, qty_base, yield_override_pct)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '4ec10000-0000-7000-8000-000000000001', '1a000000-0000-7000-8000-000000000001', 100, 85.5)$$,
  'a valid recipe line');

select throws_ok($$insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source, batch_id, pending_change_id)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '1a000000-0000-7000-8000-000000000001', 0.220000, '2026-10-12', 'manual',
          'ba7c0000-0000-7000-8000-000000000001', '9c000000-0000-7000-8000-000000000001')$$,
  '23514', null, 'a price comes from a batch or a pending change, not both');
select lives_ok($$insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source, pending_change_id)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '1a000000-0000-7000-8000-000000000001', 0.220000, '2026-10-12', 'manual', '9c000000-0000-7000-8000-000000000001')$$,
  'a price from a pending change');
select is((select unit_price_net from public.ingredient_price where tenant_id = 'aaaaaaaa-0000-7000-8000-000000000001' limit 1), 0.220000::numeric, 'unit prices keep six decimals (pesos per base unit)');
select throws_ok($$insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, effective_to, source)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '1a000000-0000-7000-8000-000000000001', 1, '2026-10-12', '2026-10-01', 'manual')$$,
  '23514', null, 'a price cannot end before it starts');

select lives_ok($$insert into public.unit_conversion (tenant_id, from_unit, to_unit, factor) values ('aaaaaaaa-0000-7000-8000-000000000001', 'kg', 'g', 1000)$$, 'a global conversion');
select throws_ok($$insert into public.unit_conversion (tenant_id, from_unit, to_unit, factor) values ('aaaaaaaa-0000-7000-8000-000000000001', 'kg', 'g', 1000)$$,
  '23505', null, 'a duplicate global conversion is rejected (nulls not distinct)');
select throws_ok($$insert into public.unit_conversion (tenant_id, from_unit, to_unit, factor) values ('aaaaaaaa-0000-7000-8000-000000000001', 'l', 'ml', 0)$$,
  '23514', null, 'a conversion factor must be positive');

insert into public.purchase_doc (id, tenant_id, supplier_id, kind, cfdi_uuid) values ('d0c00000-0000-7000-8000-000000000001', 'aaaaaaaa-0000-7000-8000-000000000001', '50000000-0000-7000-8000-000000000001', 'cfdi', 'cfd10000-0000-4000-8000-000000000001');
select throws_ok($$insert into public.purchase_doc (tenant_id, supplier_id, kind, cfdi_uuid) values ('aaaaaaaa-0000-7000-8000-000000000001', '50000000-0000-7000-8000-000000000001', 'cfdi', 'cfd10000-0000-4000-8000-000000000001')$$,
  '23505', null, 'the same CFDI cannot be loaded twice');
select lives_ok($$insert into public.purchase_doc (tenant_id, supplier_id, kind) values ('aaaaaaaa-0000-7000-8000-000000000001', '50000000-0000-7000-8000-000000000001', 'manual')$$, 'documents without a CFDI uuid do not collide');
select throws_ok($$insert into public.ingredient_alias (tenant_id, supplier_id, source_text, ingredient_id) values ('aaaaaaaa-0000-7000-8000-000000000001', '50000000-0000-7000-8000-000000000001', 'PASTOR KG', '1a000000-0000-7000-8000-000000000001'), ('aaaaaaaa-0000-7000-8000-000000000001', '50000000-0000-7000-8000-000000000001', 'PASTOR KG', '1a000000-0000-7000-8000-000000000001')$$,
  '23505', null, 'one alias per supplier text');

select lives_ok($$insert into public.dish_cost_snapshot (tenant_id, menu_item_id, location_id, date, cost, price_net, margin, food_cost_pct, confidence)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '3e100000-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001', '2026-10-12', 2100, 5000, 2900, 42.0, 'estimated')$$,
  'a dish cost snapshot');
select throws_ok($$insert into public.dish_cost_snapshot (tenant_id, menu_item_id, location_id, date, cost, price_net, margin, food_cost_pct, confidence)
  values ('aaaaaaaa-0000-7000-8000-000000000001', '3e100000-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001', '2026-10-12', 2100, 5000, 2900, 42.0, 'estimated')$$,
  '23505', null, 'one snapshot per dish, location and date');
select throws_ok($$insert into public.daily_location_metrics (tenant_id, location_id, business_date, net_sales) values
  ('aaaaaaaa-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001', '2026-10-12', 1), ('aaaaaaaa-0000-7000-8000-000000000001', 'a1a1a1a1-0000-7000-8000-000000000001', '2026-10-12', 2)$$,
  '23505', null, 'one metrics row per location and day');

select * from finish();
rollback;
