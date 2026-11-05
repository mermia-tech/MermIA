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

-- recipe.upsert is part 2: it fails cleanly for now
select pg_temp.propose('recipe', 'recipe.upsert', 'menu_item', :PASTOR,
                       '{"yield_qty": "1", "lines": [{"ingredient_name": "Carne al pastor (adobada)", "qty_base": "120", "unit": "g"}]}');
select is(pg_temp.tap('recipe', 'recipe', :OWNER) ->> 'code', 'failed', 'recipe.upsert is not applied yet (part 2)');
select is(pg_temp.audits('recipe', 'pending_change.fail'), 1::bigint, 'with a fail audit row');

select * from finish();
rollback;
