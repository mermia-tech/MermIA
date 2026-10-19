-- MR-16: apply_batch and rollback_batch move batch status only; facts are insert-only (09 D3).
begin;
select * from no_plan();

\set CENTRO '705e8e51-376b-5785-adbb-405eff4e2a22'
\set OWNER '''eb52f6ad-4d75-5b06-9881-9f68f4fb05a0'''
\set LUPITA '''240e45f0-ef48-5654-a835-8fbc70de15bc'''
\set IVAN '''23f18862-2ab3-5684-be6f-db47265e5ff9'''
\set SEEDED '''18005b12-2cda-54d0-a6d4-08900bd031ae'''

-- privileges (spec 7.5.7) ------------------------------------------------------------------
select ok(has_function_privilege('service_role', 'app.apply_batch(uuid, uuid)', 'execute'), 'the backend applies batches');
select ok(has_function_privilege('service_role', 'app.rollback_batch(uuid, uuid)', 'execute'), 'and rolls them back');
select is((select count(*) from pg_proc p where p.oid in ('app.apply_batch(uuid, uuid)'::regprocedure, 'app.rollback_batch(uuid, uuid)'::regprocedure)
           and (has_function_privilege('authenticated', p.oid, 'execute') or has_function_privilege('anon', p.oid, 'execute'))), 0::bigint,
          'clients cannot call them');
select is((select count(*) from pg_proc p where p.oid in ('app.apply_batch(uuid, uuid)'::regprocedure, 'app.rollback_batch(uuid, uuid)'::regprocedure)
           and p.prosecdef and p.proconfig @> array['search_path=""']), 2::bigint, 'both are definers with an empty search_path');

-- a correction for Centro 2026-10-11: a new batch of the same slice, with its own item rows
insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key, status)
select 'cccccccc-0000-7000-8000-000000000001', b.tenant_id, b.source_id, b.location_id, b.parser, b.slice_key, 'needs_review'
from public.import_batch b where b.id = :SEEDED;
insert into public.item_sales_agg (tenant_id, location_id, source_id, batch_id, period_from, period_to, menu_item_id, units, gross, discount, net)
select a.tenant_id, a.location_id, a.source_id, 'cccccccc-0000-7000-8000-000000000001', a.period_from, a.period_to, a.menu_item_id, a.units + 1, a.gross, a.discount, a.net
from public.item_sales_agg a where a.batch_id = :SEEDED;
create temp table before_units as
select sum(units) as units from app.v_item_sales_daily where location_id = :'CENTRO' and business_date = '2026-10-11';

select is((select sum(units) from app.v_item_sales_daily where location_id = :'CENTRO' and business_date = '2026-10-11'),
          (select units from before_units), 'a batch in needs_review is not read');

-- who may apply -------------------------------------------------------------------------------
select throws_ok(format('select app.apply_batch(%L, %L)', 'cccccccc-0000-7000-8000-000000000001', :IVAN), '42501', null,
                 'a Polanco manager cannot approve a Centro batch');
select throws_ok(format('select app.apply_batch(%L, %L)', 'cccccccc-0000-7000-8000-000000000001', '00000000-0000-7000-8000-000000000000'), '42501', null,
                 'a user without a membership cannot either');
select lives_ok(format('select app.apply_batch(%L, %L)', 'cccccccc-0000-7000-8000-000000000001', :LUPITA),
                'the Centro manager approves it');

select is((select status::text from public.import_batch where id = 'cccccccc-0000-7000-8000-000000000001'), 'applied', 'the correction is applied');
select is((select status::text from public.import_batch where id = :SEEDED), 'superseded', 'the earlier batch of the slice is superseded');
select is((select supersedes_batch_id::text from public.import_batch where id = 'cccccccc-0000-7000-8000-000000000001'), :SEEDED, 'and remembered');
select is((select applied_by::text from public.import_batch where id = 'cccccccc-0000-7000-8000-000000000001'), :LUPITA, 'applied_by is the approver');
select is((select sum(units) from app.v_item_sales_daily where location_id = :'CENTRO' and business_date = '2026-10-11'),
          (select units from before_units) + (select count(*) from public.item_sales_agg where batch_id = :SEEDED),
          'the views now read the correction only (one more unit per line)');
select is((select row(actor_kind, action, before ->> 'status', after ->> 'supersedes_batch_id')::text from public.audit_log
           where batch_id = 'cccccccc-0000-7000-8000-000000000001' and action = 'import_batch.apply'),
          format('(user,import_batch.apply,needs_review,%s)', :SEEDED), 'the approval is audit-logged');
select throws_ok(format('select app.apply_batch(%L)', 'cccccccc-0000-7000-8000-000000000001'), '55000', null, 'an applied batch does not apply twice');
select throws_ok(format('select app.apply_batch(%L)', :SEEDED), '55000', null, 'nor does a superseded one');

-- Deshacer ----------------------------------------------------------------------------------
select throws_ok(format('select app.rollback_batch(%L, %L)', 'cccccccc-0000-7000-8000-000000000001', :IVAN), '42501', null,
                 'a Polanco manager cannot undo it');
select lives_ok(format('select app.rollback_batch(%L, %L)', 'cccccccc-0000-7000-8000-000000000001', :OWNER), 'the owner undoes it');
select is((select status::text from public.import_batch where id = 'cccccccc-0000-7000-8000-000000000001'), 'rolled_back', 'rolled back');
select is((select status::text from public.import_batch where id = :SEEDED), 'applied', 'the earlier batch is current again');
select is((select sum(units) from app.v_item_sales_daily where location_id = :'CENTRO' and business_date = '2026-10-11'),
          (select units from before_units), 'the metrics return to the earlier numbers');
select is((select count(*) from public.item_sales_agg where batch_id = 'cccccccc-0000-7000-8000-000000000001'),
          (select count(*) from public.item_sales_agg where batch_id = :SEEDED), 'no row was deleted (insert-only facts)');
select is((select row(actor_kind, after ->> 'restored_batch_id')::text from public.audit_log
           where batch_id = 'cccccccc-0000-7000-8000-000000000001' and action = 'import_batch.rollback'),
          format('(user,%s)', :SEEDED), 'the rollback is audit-logged');
select throws_ok(format('select app.rollback_batch(%L)', 'cccccccc-0000-7000-8000-000000000001'), '55000', null, 'a rolled-back batch does not roll back twice');
select lives_ok(format('select app.apply_batch(%L, %L)', 'cccccccc-0000-7000-8000-000000000001', :OWNER), 'an undone Deshacer restores it (09 2.6)');
select is((select string_agg(status::text, ',' order by id) from public.import_batch where id in (:SEEDED, 'cccccccc-0000-7000-8000-000000000001')),
          'superseded,applied', 'and supersedes the seeded batch again');
select lives_ok(format('select app.rollback_batch(%L, %L)', 'cccccccc-0000-7000-8000-000000000001', :OWNER), 'undone once more');

-- a first batch for a new slice: applied by the system, rollback leaves the slice empty
insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key, status)
select 'cccccccc-0000-7000-8000-000000000002', b.tenant_id, b.source_id, b.location_id, b.parser,
       replace(b.slice_key, '2026-10-11', '2026-10-12'), 'parsed'
from public.import_batch b where b.id = :SEEDED;
select lives_ok($$select app.apply_batch('cccccccc-0000-7000-8000-000000000002')$$, 'the system applies a clean batch');
select is((select row(status, supersedes_batch_id, applied_by)::text from public.import_batch where id = 'cccccccc-0000-7000-8000-000000000002'),
          '(applied,,)', 'nothing superseded, no user');
select is((select actor_kind::text from public.audit_log where batch_id = 'cccccccc-0000-7000-8000-000000000002'), 'system', 'logged as the system');
select lives_ok($$select app.rollback_batch('cccccccc-0000-7000-8000-000000000002')$$, 'and undoes it');
select is((select count(*) from public.import_batch where slice_key like '%:2026-10-12:2026-10-12' and status = 'applied'
           and location_id = :'CENTRO' and parser = 'sr.productos_vendidos@v1'), 0::bigint, 'the slice has no current batch again');
select throws_ok($$select app.apply_batch('00000000-0000-7000-8000-00000000dead')$$, 'P0002', null, 'an unknown batch');

select * from finish();
rollback;
