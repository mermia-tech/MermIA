-- MR-32: apply_pending_change applies an approved change and logs it (MR-11 spec 3; MR-10 spec 7.5.7).
-- Part 1 kinds: ingredient_price.set, menu_item_price.set, import_batch.approve, import_batch.rollback.
begin;
select * from no_plan();

\set TENANT '''03299e41-28bd-5779-bcc6-0e5e76580fad'''
\set CENTRO '''705e8e51-376b-5785-adbb-405eff4e2a22'''
\set POLANCO '''fdda5e3b-6bcd-5c48-a6de-f524be37463e'''
\set OWNER '''eb52f6ad-4d75-5b06-9881-9f68f4fb05a0'''
\set LUPITA '''240e45f0-ef48-5654-a835-8fbc70de15bc'''
\set PASTOR '''f496f051-9f85-5f8a-a4b6-c1a814d37c73'''
\set CARNE '''356dfff4-d912-542b-b8b0-8ae42068eb7e'''
\set SEEDED_CENTRO '''18005b12-2cda-54d0-a6d4-08900bd031ae'''
\set SEEDED_POLANCO '''4c1a738a-a5bd-55d6-a29e-bda916bdbe3b'''
\set SUPPORT '''eeeeeeee-0000-7000-8000-000000000001'''
\set ADMIN '''eeeeeeee-0000-7000-8000-000000000002'''
\set STRANGER '''eeeeeeee-0000-7000-8000-000000000003'''
\set ALL_KINDS '''{ingredient_price.set,recipe.upsert,menu_item_price.set,import_batch.approve,import_batch.rollback}'''

-- business "today" for the recompute (app.business_today reads app.today first)
set local app.today = '2026-10-12';

-- privileges (spec 7.5.7) ------------------------------------------------------------------
select ok(has_function_privilege('service_role', 'app.apply_pending_change(uuid, uuid)', 'execute'), 'the backend applies changes');
select ok(has_function_privilege('service_role', 'app.pending_base_version(text, uuid, jsonb)', 'execute'),
          'and reads the version a proposal must carry');
select is((select count(*) from pg_proc p where p.oid in ('app.apply_pending_change(uuid, uuid)'::regprocedure,
                                                           'app.pending_base_version(text, uuid, jsonb)'::regprocedure)
           and (has_function_privilege('authenticated', p.oid, 'execute') or has_function_privilege('anon', p.oid, 'execute'))),
          0::bigint, 'clients cannot call them');
select ok((select p.prosecdef and p.proconfig @> array['search_path=""'] from pg_proc p
           where p.oid = 'app.apply_pending_change(uuid, uuid)'::regprocedure), 'apply is a definer with an empty search_path');
select ok(has_function_privilege('service_role', 'app.backfill_dish_costs(uuid, int)', 'execute'),
          'the backend backfills dish costs after an apply');
select ok(not has_function_privilege('authenticated', 'app.backfill_dish_costs(uuid, int)', 'execute')
          and not has_function_privilege('anon', 'app.backfill_dish_costs(uuid, int)', 'execute'), 'clients cannot');
select ok((select not p.prosecdef and p.proconfig @> array['search_path=""'] from pg_proc p
           where p.oid = 'app.backfill_dish_costs(uuid, int)'::regprocedure),
          'the backfill runs as the caller (service_role has the grants it needs) with an empty search_path');
select is((select obj_description('public.dish_cost_backfill'::regclass, 'pg_class')), 'rls_class=X',
          'the backfill record is backend-only (class X)');

-- people: MermIA support, a tenant admin, and the owner of another tenant ---------------------
insert into public.app_user (id, name) values (:SUPPORT, 'Soporte'), (:ADMIN, 'Admin'), (:STRANGER, 'Otro dueño');
insert into public.membership (tenant_id, user_id, role, location_ids, all_locations, can_approve) values
  (:TENANT, :SUPPORT, 'support', null, true, :ALL_KINDS),
  (:TENANT, :ADMIN, 'admin', null, true, :ALL_KINDS);
insert into public.tenant (id, name) values ('eeeeeeee-0000-7000-8000-0000000000a1', 'Otra taquería');
insert into public.membership (tenant_id, user_id, role, location_ids, all_locations, can_approve) values
  ('eeeeeeee-0000-7000-8000-0000000000a1', :STRANGER, 'owner', null, true, :ALL_KINDS);

-- batches waiting for approval at each location
insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key, status)
select 'eeeeeeee-0000-7000-8000-0000000000b1', b.tenant_id, b.source_id, b.location_id, b.parser, b.slice_key, 'needs_review'
from public.import_batch b where b.id = :SEEDED_CENTRO;
insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key, status)
select 'eeeeeeee-0000-7000-8000-0000000000b2', b.tenant_id, b.source_id, b.location_id, b.parser, b.slice_key, 'needs_review'
from public.import_batch b where b.id = :SEEDED_POLANCO;

-- helpers: file a proposal with the version D2 defines, and tap Confirmar ----------------------
create temp table pc (name text primary key, id uuid not null);
create temp table tap (name text primary key, res jsonb not null);

create function pg_temp.propose(name text, kind text, target_type text, target uuid, payload jsonb,
                                required app.member_role default null,
                                expires timestamptz default now() + interval '1 day') returns uuid
language sql as $$
  with x as (
    insert into public.pending_change (tenant_id, kind, target_type, target_id, base_version, payload,
                                       proposed_by_user, proposed_via, required_role, expires_at)
    values ('03299e41-28bd-5779-bcc6-0e5e76580fad', kind, target_type, target,
            app.pending_base_version(kind, target, payload), payload,
            'eb52f6ad-4d75-5b06-9881-9f68f4fb05a0', 'agent', required, expires)
    returning id)
  insert into pc select name, id from x
  returning id
$$;
create function pg_temp.pc(name text) returns uuid language sql stable as $$ select id from pc where pc.name = $1 $$;
create function pg_temp.tap(name text, change text, user_id uuid) returns jsonb
language sql as $$
  insert into tap select name, app.apply_pending_change(pg_temp.pc(change), user_id) returning res
$$;
create function pg_temp.res(name text) returns jsonb language sql stable as $$ select res from tap where tap.name = $1 $$;
create function pg_temp.audits(change text, action text) returns bigint language sql stable as $$
  select count(*) from public.audit_log where pending_change_id = pg_temp.pc(change) and audit_log.action = $2
$$;
create function pg_temp.status(change text) returns text language sql stable as $$
  select status::text from public.pending_change where id = pg_temp.pc(change)
$$;

-- ingredient_price.set ------------------------------------------------------------------------
select is(app.compute_dish_costs(:TENANT, '2026-10-12', '2026-10-12') > 0, true, 'snapshots exist for today');
create temp table pastor_before as
select cost from public.dish_cost_snapshot where menu_item_id = :PASTOR and location_id = :CENTRO and date = '2026-10-12';
select is((select app.pending_base_version('ingredient_price.set', :CARNE, '{}')), 2, 'the version of a price is its row count');

select pg_temp.propose('price', 'ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.30", "effective_from": "2026-10-12", "source": "manual"}');
select pg_temp.tap('price', 'price', :OWNER);
select is(pg_temp.res('price'),
          jsonb_build_object('code', 'applied', 'pending_change_id', pg_temp.pc('price'), 'status', 'applied', 'message', null),
          'the owner applies a price change');
select is((select row(unit_price_net, effective_from, source)::text from public.ingredient_price where pending_change_id = pg_temp.pc('price')),
          '(0.300000,2026-10-12,manual)', 'the price row is written and linked to the change');
select is((select row(status, resolved_by)::text from public.pending_change where id = pg_temp.pc('price')),
          format('(applied,%s)', :OWNER), 'the change is applied by the owner');
select is(pg_temp.audits('price', 'pending_change.apply'), 1::bigint, 'one apply audit row');
select is((select row(actor_kind, actor_user_id, entity_type, entity_id, after ->> 'base_unit', before ->> 'unit_price_net')::text
           from public.audit_log where pending_change_id = pg_temp.pc('price') and action = 'pending_change.apply'),
          format('(user,%s,ingredient,%s,g,0.195000)', :OWNER, :CARNE), 'it records the actor, the unit and the price it replaced');
select cmp_ok((select cost from public.dish_cost_snapshot where menu_item_id = :PASTOR and location_id = :CENTRO and date = '2026-10-12'),
              '>', (select cost from pastor_before), 'the pastor cost is recomputed in the same transaction');

-- a second tap changes nothing
select pg_temp.tap('price again', 'price', :OWNER);
select is(pg_temp.res('price again') ->> 'code', 'already_applied', 'a second tap is already_applied');
select is(pg_temp.res('price again') ->> 'status', 'applied', 'with status applied');
select is((select count(*) from public.ingredient_price where pending_change_id = pg_temp.pc('price')), 1::bigint, 'no second price row');
select is((select count(*) from public.audit_log where pending_change_id = pg_temp.pc('price')), 1::bigint, 'no second audit row');

-- a future price is stored but not costed yet
select pg_temp.propose('future', 'ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.40", "effective_from": "2026-12-01", "source": "manual"}');
select is(pg_temp.tap('future', 'future', :OWNER) ->> 'code', 'applied', 'a future price applies');
select is((select count(*) from public.dish_cost_snapshot where tenant_id = :TENANT and date > '2026-10-12'), 0::bigint,
          'and no snapshot is computed past today');

-- a backdated price: the tap recomputes today only, the backfill does the older days ----------
select is(app.compute_dish_costs(:TENANT, '2026-10-01', '2026-10-11') > 0, true, 'snapshots exist for the days before');
create temp table snap_before as
select date, id, cost from public.dish_cost_snapshot where menu_item_id = :PASTOR and location_id = :CENTRO and date between '2026-10-01' and '2026-10-12';
create function pg_temp.snap(d date) returns public.dish_cost_snapshot language sql stable as $$
  select * from public.dish_cost_snapshot
  where menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and location_id = '705e8e51-376b-5785-adbb-405eff4e2a22' and date = d
$$;

select pg_temp.propose('backdated', 'ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.50", "effective_from": "2026-10-05", "source": "manual"}');
select is(pg_temp.tap('backdated', 'backdated', :OWNER) ->> 'code', 'applied', 'a backdated price applies');
select isnt((pg_temp.snap('2026-10-12')).id, (select id from snap_before where date = '2026-10-12'), 'the tap rewrites today''s snapshot');
select is((pg_temp.snap('2026-10-06')).id, (select id from snap_before where date = '2026-10-06'), 'but not the older days');
select is((select after -> 'backfill' from public.audit_log where pending_change_id = pg_temp.pc('backdated') and action = 'pending_change.apply'),
          '{"from": "2026-10-05", "to": "2026-10-11", "capped": false, "requested_from": "2026-10-05"}'::jsonb,
          'the apply audit row names the days left to the backfill');
-- the durable record (from, to, next_before, done): written by the apply, in the same commit
create function pg_temp.backfill(change text) returns text language sql stable as $$
  select row(b.from_date, b.to_date, b.next_before, b.done_at is not null)::text
  from public.dish_cost_backfill b where b.pending_change_id = pg_temp.pc(change)
$$;
select is(pg_temp.backfill('backdated'), '(2026-10-05,2026-10-11,2026-10-12,f)', 'the apply records the backfill it leaves');
select is((select tenant_id from public.dish_cost_backfill where pending_change_id = pg_temp.pc('backdated')), :TENANT::uuid,
          'for the change''s tenant');

-- the backfill walks back from yesterday in chunks of at most max_days; each chunk moves the record
select is(app.backfill_dish_costs(pg_temp.pc('backdated'), 3) - 'snapshots',
          '{"from": "2026-10-09", "to": "2026-10-11", "next_before": "2026-10-09"}'::jsonb, 'the first chunk ends yesterday');
select is(pg_temp.backfill('backdated'), '(2026-10-05,2026-10-11,2026-10-09,f)', 'and records where to go on');
select is(app.backfill_dish_costs(pg_temp.pc('backdated'), 3) - 'snapshots',
          '{"from": "2026-10-06", "to": "2026-10-08", "next_before": "2026-10-06"}'::jsonb, 'the next call resumes from the record');
select is(app.backfill_dish_costs(pg_temp.pc('backdated'), 3) - 'snapshots',
          '{"from": "2026-10-05", "to": "2026-10-05", "next_before": null}'::jsonb, 'the last chunk stops at the effective date');
select is(pg_temp.backfill('backdated'), '(2026-10-05,2026-10-11,2026-10-05,t)', 'and marks the backfill done');
select cmp_ok((pg_temp.snap('2026-10-06')).cost, '>', (select cost from snap_before where date = '2026-10-06'),
              'the older days now use the backdated price');
select is((pg_temp.snap('2026-10-04')).id, (select id from snap_before where date = '2026-10-04'), 'days before it are not touched');
create temp table snap_after as select (pg_temp.snap('2026-10-06')).id;
select is(app.backfill_dish_costs(pg_temp.pc('backdated')),
          '{"from": null, "to": null, "snapshots": 0, "next_before": null}'::jsonb, 'a rerun of a done backfill does nothing');
select is((pg_temp.snap('2026-10-06')).id, (select id from snap_after), 'and rewrites no snapshot');
select throws_ok('update public.dish_cost_backfill set done_at = null, next_before = to_date + 2', '23514', null,
                 'the record cannot point past its range');

-- a price older than 400 days: the backfill stops at today - 399 and the audit row says so
select pg_temp.propose('ancient', 'ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.10", "effective_from": "2025-01-01", "source": "manual"}');
select is(pg_temp.tap('ancient', 'ancient', :OWNER) ->> 'code', 'applied', 'a price from long ago applies');
select is((select after -> 'backfill' from public.audit_log where pending_change_id = pg_temp.pc('ancient') and action = 'pending_change.apply'),
          '{"from": "2025-09-08", "to": "2026-10-11", "capped": true, "requested_from": "2025-01-01"}'::jsonb,
          'the audit row notes the 400-day cap');
select is(pg_temp.backfill('ancient'), '(2025-09-08,2026-10-11,2026-10-12,f)', 'the record holds the capped range');
-- N2: the backfill runs as the caller; service_role, the confirmation service, has what it needs
select pg_temp.pc('ancient') as ancient \gset
set local role service_role;
select is(app.backfill_dish_costs(:'ancient') - 'snapshots',
          '{"from": "2026-10-05", "to": "2026-10-11", "next_before": "2026-10-05"}'::jsonb, 'chunks are 7 days by default, as service_role');
reset role;
select is(pg_temp.backfill('ancient'), '(2025-09-08,2026-10-11,2026-10-05,f)', 'an unfinished backfill stays on record');
select throws_ok(format('update public.dish_cost_backfill set done_at = now() where pending_change_id = %L', pg_temp.pc('ancient')),
                 '23514', null, 'it cannot be marked done before it reaches its first day');

-- nothing to backfill: a price starting today, a future price, a batch get no record; refused: not applied, unknown
select is(app.backfill_dish_costs(pg_temp.pc('price')),
          '{"from": null, "to": null, "snapshots": 0, "next_before": null}'::jsonb, 'a price from today leaves nothing to backfill');
select is((select after -> 'backfill' from public.audit_log where pending_change_id = pg_temp.pc('price') and action = 'pending_change.apply'),
          'null'::jsonb, 'and its audit row says so');
select is(app.backfill_dish_costs(pg_temp.pc('future')) ->> 'from', null, 'nor does a future price');
select is((select count(*) from public.dish_cost_backfill where pending_change_id in (pg_temp.pc('price'), pg_temp.pc('future'))),
          0::bigint, 'neither gets a backfill record');
select throws_ok(format('select app.backfill_dish_costs(%L, 0)', pg_temp.pc('backdated')), '22023', null, 'max_days must be at least 1');
select throws_ok('select app.backfill_dish_costs(''eeeeeeee-0000-7000-8000-0000000000ff'')', 'P0002', null, 'an unknown change is refused');

-- menu_item_price.set -------------------------------------------------------------------------
select pg_temp.propose('menu', 'menu_item_price.set', 'menu_item', :PASTOR,
                       jsonb_build_object('price_gross', 9000, 'location_id', :CENTRO, 'effective_from', '2026-10-12'));
select is(pg_temp.tap('menu', 'menu', :OWNER) ->> 'code', 'applied', 'the owner sets the Centro menu price');
select is((select row(location_id, price_gross, tax_rate, effective_from)::text from public.menu_item_price
           where menu_item_id = :PASTOR and location_id = :CENTRO and effective_from = '2026-10-12'),
          format('(%s,9000,0.1600,2026-10-12)', :CENTRO), 'the price row is written with the location''s tax rate');
select is((select price_net from public.dish_cost_snapshot where menu_item_id = :PASTOR and location_id = :CENTRO and date = '2026-10-12'),
          7759::bigint, 'the snapshot uses the new menu price (9000 minus 16% IVA inside)');
select is(pg_temp.audits('menu', 'pending_change.apply'), 1::bigint, 'one apply audit row');
select is((select after ->> 'menu_item_price_id' from public.audit_log where pending_change_id = pg_temp.pc('menu') and action = 'pending_change.apply'),
          (select id::text from public.menu_item_price where menu_item_id = :PASTOR and location_id = :CENTRO and effective_from = '2026-10-12'),
          'the audit row names the price row it wrote');

select is(pg_temp.status('menu'), 'applied', 'the menu change is applied');

-- no price covers the date: the tax rate comes from the location's latest price for the item
insert into public.menu_item (id, tenant_id, name) values ('eeeeeeee-0000-7000-8000-0000000000c1', :TENANT, 'Gringa nueva');
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, tax_rate, effective_from)
values (:TENANT, :CENTRO, 'eeeeeeee-0000-7000-8000-0000000000c1', 5000, 0.08, '2026-11-01');
select pg_temp.propose('new dish', 'menu_item_price.set', 'menu_item', 'eeeeeeee-0000-7000-8000-0000000000c1',
                       jsonb_build_object('price_gross', 4800, 'location_id', :CENTRO, 'effective_from', '2026-10-12'));
select is(pg_temp.tap('new dish', 'new dish', :OWNER) ->> 'code', 'applied', 'a menu price before any earlier price applies');
select is((select tax_rate from public.menu_item_price
           where menu_item_id = 'eeeeeeee-0000-7000-8000-0000000000c1' and effective_from = '2026-10-12'),
          0.0800, 'with the tax rate of the location''s latest price for the item');
-- no price for the item at that location at all: no tax rate to keep, so it fails
select pg_temp.propose('no tax', 'menu_item_price.set', 'menu_item', 'eeeeeeee-0000-7000-8000-0000000000c1',
                       jsonb_build_object('price_gross', 4800, 'location_id', :POLANCO, 'effective_from', '2026-10-12'));
select is(pg_temp.tap('no tax', 'no tax', :OWNER) ->> 'code', 'failed', 'a menu price with no known tax rate fails');
select is((select count(*) from public.menu_item_price where menu_item_id = 'eeeeeeee-0000-7000-8000-0000000000c1' and location_id = :POLANCO),
          0::bigint, 'and writes nothing');
select matches((select after ->> 'error' from public.audit_log where pending_change_id = pg_temp.pc('no tax') and action = 'pending_change.fail'),
               'tax rate', 'the fail audit row says why');

-- conflict: another price for the same item and location arrived after the proposal
select pg_temp.propose('stale menu', 'menu_item_price.set', 'menu_item', :PASTOR,
                       jsonb_build_object('price_gross', 9500, 'location_id', :CENTRO, 'effective_from', '2026-10-12'));
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, tax_rate, effective_from)
values (:TENANT, :CENTRO, :PASTOR, 9100, 0.16, '2026-10-12');
select is(pg_temp.tap('stale menu', 'stale menu', :OWNER) ->> 'code', 'conflict', 'a menu price whose target moved is a conflict');
select is((select count(*) from public.menu_item_price where menu_item_id = :PASTOR and price_gross = 9500), 0::bigint, 'no price row');
select is(pg_temp.audits('stale menu', 'pending_change.conflict'), 1::bigint, 'with an audit row');

-- a menu price whose location_id is not a uuid: the version lookup raises, so it fails
insert into public.pending_change (tenant_id, kind, target_type, target_id, base_version, payload, proposed_by_user, proposed_via, expires_at)
values (:TENANT, 'menu_item_price.set', 'menu_item', :PASTOR, 1,
        '{"price_gross": 9000, "location_id": "Centro", "effective_from": "2026-10-12"}', :OWNER, 'agent', now() + interval '1 day');
insert into pc select 'bad location', id from public.pending_change where payload ->> 'location_id' = 'Centro';
select is(pg_temp.tap('bad location', 'bad location', :OWNER) ->> 'code', 'failed', 'a malformed location_id fails');
select is(pg_temp.status('bad location'), 'failed', 'its status is failed');
select is(pg_temp.audits('bad location', 'pending_change.fail'), 1::bigint, 'with a fail audit row');

-- import_batch.approve and import_batch.rollback ---------------------------------------------
select pg_temp.propose('approve', 'import_batch.approve', 'import_batch', 'eeeeeeee-0000-7000-8000-0000000000b1', '{}');
select is(pg_temp.tap('approve', 'approve', :LUPITA) ->> 'code', 'applied', 'the Centro manager approves a Centro batch');
select is((select status::text from public.import_batch where id = 'eeeeeeee-0000-7000-8000-0000000000b1'), 'applied', 'the batch is applied');
select is((select applied_by::text from public.import_batch where id = 'eeeeeeee-0000-7000-8000-0000000000b1'), :LUPITA, 'by her');
select is(pg_temp.audits('approve', 'pending_change.apply'), 1::bigint, 'one apply audit row for the change');
select is((select count(*) from public.audit_log where batch_id = 'eeeeeeee-0000-7000-8000-0000000000b1' and action = 'import_batch.apply'),
          1::bigint, 'and apply_batch''s own audit row');

select pg_temp.propose('rollback', 'import_batch.rollback', 'import_batch', 'eeeeeeee-0000-7000-8000-0000000000b1', '{}');
select is(pg_temp.tap('rollback', 'rollback', :LUPITA) ->> 'code', 'applied', 'she undoes it');
select is((select status::text from public.import_batch where id = 'eeeeeeee-0000-7000-8000-0000000000b1'), 'rolled_back', 'the batch is rolled back');
select is((select status::text from public.import_batch where id = :SEEDED_CENTRO), 'applied', 'the earlier batch is current again');
select is(pg_temp.audits('rollback', 'pending_change.apply'), 1::bigint, 'one apply audit row');

-- refusals: no write, no status change --------------------------------------------------------
create temp table prices_before as select count(*) as n from public.ingredient_price;

-- location: a Centro manager cannot approve a Polanco batch
select pg_temp.propose('polanco batch', 'import_batch.approve', 'import_batch', 'eeeeeeee-0000-7000-8000-0000000000b2', '{}');
select is(pg_temp.tap('polanco batch', 'polanco batch', :LUPITA),
          jsonb_build_object('code', 'forbidden_role', 'pending_change_id', pg_temp.pc('polanco batch'), 'status', 'pending', 'message', null),
          'a Centro manager on a Polanco batch is forbidden_role');
select is((select status::text from public.import_batch where id = 'eeeeeeee-0000-7000-8000-0000000000b2'), 'needs_review', 'the batch is untouched');
select is(pg_temp.status('polanco batch'), 'pending', 'the change stays pending');
select is(pg_temp.audits('polanco batch', 'pending_change.deny'), 1::bigint, 'the refusal is audit-logged');

-- can_approve: managers approve imports only (MR-30 defaults)
select pg_temp.propose('lupita price', 'ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.50", "effective_from": "2026-10-12", "source": "manual"}');
select is(pg_temp.tap('lupita price', 'lupita price', :LUPITA) ->> 'code', 'forbidden_role', 'a manager without the kind in can_approve is refused');

-- location of a menu price: Centro-only even when the kind is allowed
update public.membership set can_approve = can_approve || '{menu_item_price.set}'::text[] where user_id = :LUPITA;
select pg_temp.propose('polanco menu', 'menu_item_price.set', 'menu_item', :PASTOR,
                       jsonb_build_object('price_gross', 9900, 'location_id', :POLANCO, 'effective_from', '2026-10-12'));
select is(pg_temp.tap('polanco menu', 'polanco menu', :LUPITA) ->> 'code', 'forbidden_role', 'a Centro manager cannot set a Polanco price');
select is((select count(*) from public.menu_item_price where menu_item_id = :PASTOR and price_gross = 9900), 0::bigint, 'no price row');

-- a Polanco-only dish: a Centro manager cannot price it even at Centro
insert into public.menu_item (id, tenant_id, location_id, name) values ('eeeeeeee-0000-7000-8000-0000000000c2', :TENANT, :POLANCO, 'Especial Polanco');
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, tax_rate, effective_from)
values (:TENANT, :CENTRO, 'eeeeeeee-0000-7000-8000-0000000000c2', 7000, 0.16, '2026-10-01');
select pg_temp.propose('polanco dish', 'menu_item_price.set', 'menu_item', 'eeeeeeee-0000-7000-8000-0000000000c2',
                       jsonb_build_object('price_gross', 7500, 'location_id', :CENTRO, 'effective_from', '2026-10-12'));
select is(pg_temp.tap('polanco dish', 'polanco dish', :LUPITA) ->> 'code', 'forbidden_role',
          'the menu item''s own location counts too');
select is(pg_temp.audits('polanco dish', 'pending_change.deny'), 1::bigint, 'the refusal is audit-logged');
select is(pg_temp.status('polanco dish'), 'pending', 'the change stays pending');

-- support proposes but never approves (09 section 5.1)
select is(pg_temp.tap('support', 'lupita price', :SUPPORT) ->> 'code', 'forbidden_role', 'support is refused even with can_approve');

-- required_role owner
select pg_temp.propose('owner only', 'ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.50", "effective_from": "2026-10-12", "source": "manual"}', 'owner');
select is(pg_temp.tap('owner only', 'owner only', :ADMIN) ->> 'code', 'forbidden_role', 'required_role owner refuses an admin');
select is(pg_temp.status('owner only'), 'pending', 'and leaves the change pending');

-- apply_batch's own role check (owner, manager) refuses an admin: 42501 maps to forbidden_role
select is(pg_temp.tap('admin batch', 'polanco batch', :ADMIN) ->> 'code', 'forbidden_role', 'apply_batch refusing an admin is forbidden_role');
select is((select status::text from public.import_batch where id = 'eeeeeeee-0000-7000-8000-0000000000b2'), 'needs_review', 'the batch is untouched');
select is(pg_temp.audits('polanco batch', 'pending_change.deny'), 2::bigint, 'that refusal is audit-logged too');

-- another tenant's owner, or an unknown id, learns nothing
select is(pg_temp.tap('stranger', 'owner only', :STRANGER),
          jsonb_build_object('code', 'not_found', 'pending_change_id', pg_temp.pc('owner only'), 'status', null, 'message', null),
          'another tenant''s owner gets not_found');
select is((select count(*) from public.audit_log where actor_user_id = :STRANGER), 0::bigint, 'nothing is logged for them');
select is(app.apply_pending_change('eeeeeeee-0000-7000-8000-0000000000ff', :OWNER) ->> 'code', 'not_found', 'an unknown id is not_found');

select is((select n from prices_before), (select count(*) from public.ingredient_price), 'no refusal wrote a price');

-- not_pending: a rejected change
update public.pending_change set status = 'rejected' where id = pg_temp.pc('lupita price');
select is(pg_temp.tap('rejected', 'lupita price', :OWNER),
          jsonb_build_object('code', 'not_pending', 'pending_change_id', pg_temp.pc('lupita price'), 'status', 'rejected', 'message', null),
          'a rejected change is not_pending');

-- expired
select pg_temp.propose('old', 'ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.50", "effective_from": "2026-10-12", "source": "manual"}', null, now() - interval '1 minute');
select is(pg_temp.tap('old', 'old', :OWNER) ->> 'code', 'expired', 'a change past expires_at is expired');
select is(pg_temp.status('old'), 'expired', 'and its status moves to expired');
select is(pg_temp.audits('old', 'pending_change.expire'), 1::bigint, 'with an audit row');
select is(pg_temp.tap('old again', 'old', :OWNER) ->> 'code', 'not_pending', 'tapping it again is not_pending');

-- conflict: a CFDI price arrived after the proposal
select pg_temp.propose('stale', 'ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.50", "effective_from": "2026-10-12", "source": "manual"}');
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:TENANT, :CARNE, 0.21, '2026-10-12', 'cfdi');
select is(pg_temp.tap('stale', 'stale', :OWNER) ->> 'code', 'conflict', 'a change whose target moved is a conflict');
select is(pg_temp.status('stale'), 'conflict', 'its status is conflict');
select is(pg_temp.audits('stale', 'pending_change.conflict'), 1::bigint, 'with an audit row');
select is((select count(*) from public.ingredient_price where pending_change_id = pg_temp.pc('stale')), 0::bigint, 'no price row');

-- conflict: the loader moved the batch after the proposal
select pg_temp.propose('stale batch', 'import_batch.approve', 'import_batch', 'eeeeeeee-0000-7000-8000-0000000000b2', '{}');
update public.import_batch set version = version + 1 where id = 'eeeeeeee-0000-7000-8000-0000000000b2';
select is(pg_temp.tap('stale batch', 'stale batch', :OWNER) ->> 'code', 'conflict', 'a batch that moved is a conflict');
select is((select status::text from public.import_batch where id = 'eeeeeeee-0000-7000-8000-0000000000b2'), 'needs_review', 'the batch is untouched');
select is(pg_temp.audits('stale batch', 'pending_change.conflict'), 1::bigint, 'with an audit row');

-- transient errors (deadlock, serialization, lock timeout) escape, so a retry can apply the change
create function pg_temp.transient() returns trigger language plpgsql as $$
begin
  raise exception 'transient' using errcode = current_setting('test.errcode');
end
$$;
create trigger zz_transient after insert on public.ingredient_price for each row execute function pg_temp.transient();
select pg_temp.propose('transient', 'ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.60", "effective_from": "2026-10-12", "source": "manual"}');
set local test.errcode = '40P01';
select throws_ok(format('select app.apply_pending_change(%L, %L)', pg_temp.pc('transient'), :OWNER), '40P01', null, 'a deadlock escapes');
set local test.errcode = '40001';
select throws_ok(format('select app.apply_pending_change(%L, %L)', pg_temp.pc('transient'), :OWNER), '40001', null, 'a serialization failure escapes');
set local test.errcode = '55P03';
select throws_ok(format('select app.apply_pending_change(%L, %L)', pg_temp.pc('transient'), :OWNER), '55P03', null, 'a lock timeout escapes');
select is(pg_temp.status('transient'), 'pending', 'the change stays pending');
select is(pg_temp.audits('transient', 'pending_change.fail'), 0::bigint, 'with no fail audit row');
drop trigger zz_transient on public.ingredient_price;
select is(pg_temp.tap('transient retry', 'transient', :OWNER) ->> 'code', 'applied', 'and a retry applies it');

-- failed: the write raises after inserting; everything it did rolls back
create function pg_temp.boom() returns trigger language plpgsql as $$
begin
  raise exception 'boom' using errcode = 'P0001';
end
$$;
create trigger zz_boom after insert on public.ingredient_price for each row execute function pg_temp.boom();
select pg_temp.propose('boom', 'ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.60", "effective_from": "2026-10-12", "source": "manual"}');
select is(pg_temp.tap('boom', 'boom', :OWNER) ->> 'code', 'failed', 'a write that raises is failed');
select is(pg_temp.status('boom'), 'failed', 'its status is failed');
select is((select count(*) from public.ingredient_price where pending_change_id = pg_temp.pc('boom')), 0::bigint, 'the write rolled back');
select is(pg_temp.audits('boom', 'pending_change.apply'), 0::bigint, 'no apply audit row survives');
select is(pg_temp.audits('boom', 'pending_change.fail'), 1::bigint, 'one fail audit row');
drop trigger zz_boom on public.ingredient_price;

-- a backfill record exists only for an applied price change that left older days
select is((select count(*) from public.dish_cost_backfill where pending_change_id in (pg_temp.pc('approve'), pg_temp.pc('rollback'))),
          0::bigint, 'batch changes get no backfill record');
select pg_temp.propose('boom backdated', 'ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.70", "effective_from": "2026-10-01", "source": "manual"}');
create trigger zz_boom after insert on public.dish_cost_backfill for each row execute function pg_temp.boom();
select is(pg_temp.tap('boom backdated', 'boom backdated', :OWNER) ->> 'code', 'failed', 'a backfill record that cannot be written fails the apply');
select is((select count(*) from public.ingredient_price where pending_change_id = pg_temp.pc('boom backdated')), 0::bigint,
          'with the price write rolled back: the record and the apply commit together');
drop trigger zz_boom on public.dish_cost_backfill;

-- recipe.upsert is part 2: it fails cleanly for now
select pg_temp.propose('recipe', 'recipe.upsert', 'menu_item', :PASTOR,
                       '{"yield_qty": "1", "lines": [{"ingredient_name": "Carne al pastor (adobada)", "qty_base": "120", "unit": "g"}]}');
select is(pg_temp.tap('recipe', 'recipe', :OWNER) ->> 'code', 'failed', 'recipe.upsert is not applied yet (part 2)');
select is(pg_temp.audits('recipe', 'pending_change.fail'), 1::bigint, 'with a fail audit row');

-- MR-87: the sweep counts failures per record and gives up after MAX_BACKFILL_ATTEMPTS
select col_type_is('public', 'dish_cost_backfill', 'attempts', 'integer', 'a backfill counts its failed sweeps');
select col_not_null('public', 'dish_cost_backfill', 'attempts', 'the count is never null');
select col_default_is('public', 'dish_cost_backfill', 'attempts', '0', 'and starts at 0');
select col_type_is('public', 'dish_cost_backfill', 'last_error', 'text', 'the last error is kept as text');
select col_is_null('public', 'dish_cost_backfill', 'last_error', 'and is empty until a sweep fails');
select is(pg_temp.backfill('backdated') is not null, true, 'existing records are untouched');
select throws_ok(format('update public.dish_cost_backfill set attempts = -1 where pending_change_id = %L', pg_temp.pc('backdated')),
                 '23514', null, 'the count cannot go negative');
select is((select count(*) from pg_indexes where indexname = 'dish_cost_backfill_unfinished_idx'
           and indexdef like '%(attempts, created_at)%'), 1::bigint, 'the sweep pick is indexed by (attempts, created_at)');

select * from finish();
rollback;
