-- MR-32: apply_pending_change (09 section 5; MR-10 spec 7.5.7; MR-11 spec 3). Part 1 of 2:
-- ingredient_price.set, menu_item_price.set, import_batch.approve, import_batch.rollback.
-- recipe.upsert comes in part 2; until then it returns `failed`.
--
-- app.apply_pending_change(id, user_id) is SECURITY DEFINER, executable by service_role only (the
-- confirmation service). user_id is the approver's app_user.id, resolved by the backend. The tenant
-- comes from the pending_change row. Checks, in this order (MR-11 spec 3.3):
--   1. the row exists and the user is a member of its tenant      else not_found (nothing revealed)
--   2. authorization (D1): not support, kind in can_approve, required_role owner needs the owner,
--      the member's locations cover the target                    else forbidden_role + audit deny
--   3. status: applied -> already_applied; anything but pending -> not_pending
--   4. expires_at passed                                          -> expired + audit
--   5. the target's version equals base_version (D2)              else conflict + audit
--   6. the write, the status and the apply audit row in one block; if it raises, all of it rolls
--      back and the change becomes failed + audit (42501 from apply_batch is forbidden_role).
--      Transient errors (deadlock, serialization failure, lock timeout, cancel) are raised instead:
--      the whole tap rolls back, the change stays pending and a retry can apply it.
-- Only an authorized approver causes a state change. A price write recomputes today's dish costs
-- in the same transaction, so the reply shows fresh numbers (D3). The older days, from the
-- effective date (at most 400 days back) to yesterday, are recomputed after commit by
-- app.backfill_dish_costs, in short chunks. Business outcomes are returned as the C5 ApplyResult
-- shape {code, pending_change_id, status, message}, never raised.

-- Indexes the version lookup and the costing engine need: these tables' indexes lead with
-- tenant_id, but price_of_record, recipe_of_record, recipe_cost and pending_base_version filter by
-- the ingredient, item or recipe alone (without them a 400-day recompute ran about 6x slower).
create index ingredient_price_ingredient_date_idx on public.ingredient_price (ingredient_id, effective_from);
create index menu_item_price_item_location_idx on public.menu_item_price (menu_item_id, location_id, effective_from);
create index recipe_menu_item_idx on public.recipe (menu_item_id);
create index recipe_produces_idx on public.recipe (produces_ingredient_id);
create index recipe_line_recipe_only_idx on public.recipe_line (recipe_id);

-- The version a proposal must carry in base_version (D2), and the one apply compares it with:
--   ingredient_price.set   number of ingredient_price rows of the ingredient
--   menu_item_price.set    number of menu_item_price rows of the item at payload.location_id
--   recipe.upsert          recipe_version of the dish's recipe of record today (null: none)
--   import_batch.*         import_batch.version
-- Prices are insert-only, so a new price row (a CFDI, another approved change) moves the count.
-- The tenant is not checked here: apply checks it on the write.
create function app.tenant_today(tenant uuid) returns date
language sql stable set search_path = ''
as $$
  select app.business_today((select l.id from public.location l where l.tenant_id = tenant order by l.id limit 1))
$$;

create function app.pending_base_version(kind text, target_id uuid, payload jsonb) returns int
language sql stable set search_path = ''
as $$
  select case kind
    when 'ingredient_price.set' then
      (select count(*)::int from public.ingredient_price p where p.ingredient_id = target_id)
    when 'menu_item_price.set' then
      (select count(*)::int from public.menu_item_price p
       where p.menu_item_id = target_id and p.location_id = (payload ->> 'location_id')::uuid)
    when 'recipe.upsert' then
      (select r.recipe_version from public.recipe r
       where r.id = app.recipe_of_record(target_id, null,
                                         app.tenant_today((select m.tenant_id from public.menu_item m where m.id = target_id))))
    when 'import_batch.approve' then
      (select b.version from public.import_batch b where b.id = target_id)
    when 'import_batch.rollback' then
      (select b.version from public.import_batch b where b.id = target_id)
  end
$$;

-- Helpers (run only inside apply_pending_change) ------------------------------------------------
create function app.pending_change_result(code text, pc_id uuid, status app.pending_change_status, message text default null)
returns jsonb
language sql immutable set search_path = ''
as $$
  select jsonb_build_object('code', code, 'pending_change_id', pc_id, 'status', status, 'message', message)
$$;

create function app.pending_change_log(pc public.pending_change, actor uuid, action text, before jsonb, after jsonb)
returns void
language sql set search_path = ''
as $$
  insert into public.audit_log (tenant_id, actor_user_id, actor_kind, action, entity_type, entity_id, before, after, pending_change_id)
  values (pc.tenant_id, actor, 'user', action, pc.target_type, pc.target_id, before, after, pc.id)
$$;

create function app.pending_change_resolve(pc_id uuid, new_status app.pending_change_status, actor uuid) returns void
language sql set search_path = ''
as $$
  update public.pending_change set status = new_status, resolved_by = actor, resolved_at = now() where id = pc_id
$$;

-- The write failed or could not be prepared: mark the change failed and log the error.
create function app.pending_change_fail(pc public.pending_change, actor uuid, state text, error text) returns jsonb
language plpgsql set search_path = ''
as $$
begin
  perform app.pending_change_resolve(pc.id, 'failed', actor);
  perform app.pending_change_log(pc, actor, 'pending_change.fail', null, jsonb_build_object('sqlstate', state, 'error', error));
  return app.pending_change_result('failed', pc.id, 'failed', format('the change could not be applied (SQLSTATE %s)', state));
end
$$;

-- D1: why this member may not approve this change, or null when they may. Location rules: a
-- menu price touches payload.location_id (and the item's own location, if it has one); a batch
-- touches its location; an ingredient price is tenant-level (no location dimension, 09 5.1).
create function app.pending_change_denial(pc public.pending_change, m public.membership) returns text
language plpgsql stable set search_path = ''
as $$
declare
  locs uuid[];
  payload_location uuid;
begin
  if m.role = 'support' then
    return 'support';  -- MermIA staff propose but never approve
  end if;
  if not (pc.kind = any (m.can_approve)) then
    return 'can_approve';
  end if;
  if pc.required_role = 'owner' and m.role <> 'owner' then
    return 'required_role';
  end if;
  if m.all_locations then
    return null;
  end if;
  if pc.kind = 'menu_item_price.set' then
    if not coalesce((pc.payload ->> 'location_id') ~* '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$', false) then
      return 'location';  -- no readable location: only an all-locations member may go on
    end if;
    payload_location := (pc.payload ->> 'location_id')::uuid;
    locs := array[payload_location];
  end if;
  if pc.target_type = 'menu_item' then
    locs := locs || (select m2.location_id from public.menu_item m2 where m2.id = pc.target_id and m2.tenant_id = pc.tenant_id);
  elsif pc.target_type = 'import_batch' then
    locs := array[(select b.location_id from public.import_batch b where b.id = pc.target_id and b.tenant_id = pc.tenant_id)];
  end if;
  if not (array_remove(locs, null) <@ coalesce(m.location_ids, '{}')) then
    return 'location';
  end if;
  return null;
end
$$;

-- D3: the days a change effective from `effective_from` leaves to the backfill: from its date, at
-- most 400 days back counting today, to yesterday. Empty (from_date > to_date) when it starts today
-- or later.
create function app.dish_cost_backfill_range(tenant uuid, effective_from date, out from_date date, out to_date date)
language sql stable set search_path = ''
as $$
  select greatest(effective_from, t.today - 399), t.today - 1 from (select app.tenant_today(tenant) as today) t
$$;

-- D3, in the tap: rewrite today's dish_cost_snapshot (nothing when the change starts in the
-- future). Returns {snapshots, backfill} for the apply audit row: the snapshots written today (or
-- null) and the days left to app.backfill_dish_costs (or null), with `capped` when the 400-day
-- limit cut the range short of `requested_from`.
create function app.recompute_after_change(tenant uuid, effective_from date) returns jsonb
language plpgsql set search_path = ''
as $$
declare
  today date := app.tenant_today(tenant);
  r record;
begin
  if effective_from > today then
    return jsonb_build_object('snapshots', null, 'backfill', null);
  end if;
  select * into r from app.dish_cost_backfill_range(tenant, effective_from);
  return jsonb_build_object(
    'snapshots', app.compute_dish_costs(tenant, today, today),
    'backfill', case when r.from_date <= r.to_date then
      jsonb_build_object('from', r.from_date, 'to', r.to_date, 'requested_from', effective_from,
                         'capped', effective_from < r.from_date) end);
end
$$;

-- The writes, one per kind. Each returns {before, after} for the apply audit row and raises on
-- any problem (the caller rolls back and marks the change failed).
create function app.apply_ingredient_price(pc public.pending_change) returns jsonb
language plpgsql set search_path = ''
as $$
declare
  unit app.base_unit;
  eff date := (pc.payload ->> 'effective_from')::date;
  previous numeric;
  p public.ingredient_price;
begin
  select i.base_unit into unit from public.ingredient i where i.id = pc.target_id and i.tenant_id = pc.tenant_id;
  if not found then
    raise exception 'ingredient % not found in the tenant', pc.target_id using errcode = 'P0002';
  end if;
  if eff is null or not coalesce((pc.payload ->> 'unit_price')::numeric > 0, false) then
    raise exception 'ingredient_price.set needs a positive unit_price and an effective_from' using errcode = '22023';
  end if;
  select r.unit_price_net into previous from app.price_of_record(pc.target_id, eff) r;
  insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source, pending_change_id)
  values (pc.tenant_id, pc.target_id, (pc.payload ->> 'unit_price')::numeric, eff,
          coalesce(pc.payload ->> 'source', 'manual')::app.ingredient_price_source, pc.id)
  returning * into p;
  return jsonb_build_object(
    'before', jsonb_build_object('unit_price_net', previous),
    -- D4: the unit the price is per, so a $/kg figure stored as $/g is visible on record
    'after', jsonb_build_object('ingredient_price_id', p.id, 'unit_price_net', p.unit_price_net, 'base_unit', unit,
                                'effective_from', p.effective_from, 'source', p.source)
             || app.recompute_after_change(pc.tenant_id, eff));
end
$$;

create function app.apply_menu_item_price(pc public.pending_change) returns jsonb
language plpgsql set search_path = ''
as $$
declare
  loc uuid := (pc.payload ->> 'location_id')::uuid;
  eff date := (pc.payload ->> 'effective_from')::date;
  gross bigint := (pc.payload ->> 'price_gross')::bigint;
  previous public.menu_item_price;
  tax numeric;
  p public.menu_item_price;
begin
  if loc is null or eff is null or not coalesce(gross > 0, false) then
    raise exception 'menu_item_price.set needs a positive price_gross, a location_id and an effective_from' using errcode = '22023';
  end if;
  -- the price in effect that day at that location; the new row keeps its tax rate
  select * into previous from public.menu_item_price x
  where x.tenant_id = pc.tenant_id and x.menu_item_id = pc.target_id and x.location_id = loc
    and x.effective_from <= eff and (x.effective_to is null or x.effective_to >= eff)
  order by x.effective_from desc, x.created_at desc
  limit 1;
  -- no tax rate on it (no price covers the date): the latest known one for the item there
  tax := coalesce(previous.tax_rate,
                  (select x.tax_rate from public.menu_item_price x
                   where x.tenant_id = pc.tenant_id and x.menu_item_id = pc.target_id and x.location_id = loc
                     and x.tax_rate is not null
                   order by x.effective_from desc, x.created_at desc
                   limit 1));
  if tax is null then
    raise exception 'no tax rate known for menu item % at location %: it has no earlier price there', pc.target_id, loc
      using errcode = '22023';
  end if;
  insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, tax_rate, effective_from, source)
  values (pc.tenant_id, loc, pc.target_id, gross, tax, eff, 'manual')
  returning * into p;
  return jsonb_build_object(
    'before', jsonb_build_object('price_gross', previous.price_gross),
    'after', jsonb_build_object('menu_item_price_id', p.id, 'price_gross', p.price_gross, 'location_id', p.location_id,
                                'effective_from', p.effective_from, 'tax_rate', p.tax_rate)
             || app.recompute_after_change(pc.tenant_id, eff));
end
$$;

-- apply_batch / rollback_batch check the actor again and write their own audit rows.
create function app.apply_batch_change(pc public.pending_change, actor uuid) returns jsonb
language plpgsql set search_path = ''
as $$
declare
  previous app.batch_status;
  b public.import_batch;
begin
  select x.status into previous from public.import_batch x where x.id = pc.target_id and x.tenant_id = pc.tenant_id;
  if not found then
    raise exception 'batch % not found in the tenant', pc.target_id using errcode = 'P0002';
  end if;
  if pc.kind = 'import_batch.approve' then
    b := app.apply_batch(pc.target_id, actor);
  else
    b := app.rollback_batch(pc.target_id, actor);
  end if;
  return jsonb_build_object('before', jsonb_build_object('status', previous), 'after', jsonb_build_object('status', b.status));
end
$$;

create function app.pending_change_write(pc public.pending_change, actor uuid) returns jsonb
language plpgsql set search_path = ''
as $$
begin
  case pc.kind
    when 'ingredient_price.set' then
      return app.apply_ingredient_price(pc);
    when 'menu_item_price.set' then
      return app.apply_menu_item_price(pc);
    when 'import_batch.approve', 'import_batch.rollback' then
      return app.apply_batch_change(pc, actor);
    else
      raise exception 'kind % is not applied yet', pc.kind using errcode = '0A000';  -- recipe.upsert: part 2
  end case;
end
$$;

-- The function ---------------------------------------------------------------------------------
create function app.apply_pending_change(id uuid, user_id uuid) returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
  pc public.pending_change;
  m public.membership;
  denial text;
  current_version int;
  written jsonb;
begin
  -- 1. tenant from the row, membership in it; a second tap waits here for the first
  select * into pc from public.pending_change p where p.id = apply_pending_change.id for update;
  if not found then
    return app.pending_change_result('not_found', apply_pending_change.id, null);
  end if;
  select * into m from public.membership x where x.tenant_id = pc.tenant_id and x.user_id = apply_pending_change.user_id;
  if not found then
    return app.pending_change_result('not_found', pc.id, null);
  end if;

  -- 2. authorization
  denial := app.pending_change_denial(pc, m);
  if denial is not null then
    perform app.pending_change_log(pc, m.user_id, 'pending_change.deny', null, jsonb_build_object('reason', denial));
    return app.pending_change_result('forbidden_role', pc.id, pc.status);
  end if;

  -- 3. status, 4. expiry
  if pc.status = 'applied' then
    return app.pending_change_result('already_applied', pc.id, pc.status);
  elsif pc.status <> 'pending' then
    return app.pending_change_result('not_pending', pc.id, pc.status);
  end if;
  if pc.expires_at <= now() then
    perform app.pending_change_resolve(pc.id, 'expired', m.user_id);
    perform app.pending_change_log(pc, m.user_id, 'pending_change.expire', null, jsonb_build_object('expires_at', pc.expires_at));
    return app.pending_change_result('expired', pc.id, 'expired');
  end if;

  -- 5. version: one change per target at a time; a batch is also locked against the loader
  perform pg_advisory_xact_lock(hashtextextended('pending_change_target:' || coalesce(pc.target_id::text, ''), 0));
  if pc.target_type = 'import_batch' then
    perform 1 from public.import_batch b where b.id = pc.target_id and b.tenant_id = pc.tenant_id for update;
  end if;
  begin
    current_version := app.pending_base_version(pc.kind, pc.target_id, pc.payload);
  exception
    when deadlock_detected or serialization_failure or lock_not_available then
      raise;  -- transient: the tap rolls back and the change stays pending for a retry
    when others then
      return app.pending_change_fail(pc, m.user_id, sqlstate, sqlerrm);
  end;
  if current_version is distinct from pc.base_version then
    perform app.pending_change_resolve(pc.id, 'conflict', m.user_id);
    perform app.pending_change_log(pc, m.user_id, 'pending_change.conflict',
                                   jsonb_build_object('version', pc.base_version), jsonb_build_object('version', current_version));
    return app.pending_change_result('conflict', pc.id, 'conflict');
  end if;

  -- 6. the write, the status and the audit row commit together or not at all
  begin
    written := app.pending_change_write(pc, m.user_id);
    perform app.pending_change_resolve(pc.id, 'applied', m.user_id);
    perform app.pending_change_log(pc, m.user_id, 'pending_change.apply',
                                   jsonb_build_object('version', pc.base_version) || coalesce(written -> 'before', '{}'),
                                   written -> 'after');
  exception
    when insufficient_privilege then  -- apply_batch / rollback_batch refused the actor
      perform app.pending_change_log(pc, m.user_id, 'pending_change.deny', null, jsonb_build_object('reason', 'batch_actor'));
      return app.pending_change_result('forbidden_role', pc.id, pc.status);
    when deadlock_detected or serialization_failure or lock_not_available then
      raise;  -- transient: the tap rolls back and the change stays pending for a retry
    when others then  -- (query_canceled is not caught by others: it escapes too)
      return app.pending_change_fail(pc, m.user_id, sqlstate, sqlerrm);
  end;
  return app.pending_change_result('applied', pc.id, 'applied');
end
$$;

-- D3, after commit: recompute the older days of an applied price change, one chunk per call so
-- the per-tenant dish_cost_snapshot lock (taken by compute_dish_costs) is held for a few seconds
-- at most and a concurrent tap's today-recompute waits little. The confirmation service calls it
-- in the background, one transaction per call (mermia_api.confirm.backfill), walking back from
-- yesterday: `before` is the exclusive upper end (null: start at yesterday), `max_days` the chunk
-- size. Returns {from, to, snapshots, next_before}: the days recomputed, the snapshots written and
-- the `before` of the next call (null: done). {from: null, ...} when nothing is left to do (a batch,
-- a price starting today or later). Idempotent: compute_dish_costs rewrites each day, so a rerun
-- gives the same numbers. Raises P0002 for an unknown change and 55000 for one that is not applied.
create function app.backfill_dish_costs(pending_change_id uuid, before date default null, max_days int default 7)
returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
  pc public.pending_change;
  r record;
  hi date;
  lo date;
  nothing constant jsonb := jsonb_build_object('from', null, 'to', null, 'snapshots', 0, 'next_before', null);
begin
  if max_days is null or max_days not between 1 and 31 then
    raise exception 'max_days must be between 1 and 31' using errcode = '22023';
  end if;
  select * into pc from public.pending_change p where p.id = backfill_dish_costs.pending_change_id;
  if not found then
    raise exception 'pending change % not found', backfill_dish_costs.pending_change_id using errcode = 'P0002';
  end if;
  if pc.status <> 'applied' then
    raise exception 'pending change % is %, not applied', pc.id, pc.status using errcode = '55000';
  end if;
  if pc.kind not in ('ingredient_price.set', 'menu_item_price.set') then
    return nothing;
  end if;
  select * into r from app.dish_cost_backfill_range(pc.tenant_id, (pc.payload ->> 'effective_from')::date);
  hi := least(r.to_date, before - 1);  -- least ignores a null before
  if hi < r.from_date then
    return nothing;
  end if;
  lo := greatest(r.from_date, hi - (max_days - 1));
  return jsonb_build_object('from', lo, 'to', hi, 'snapshots', app.compute_dish_costs(pc.tenant_id, lo, hi),
                            'next_before', case when lo > r.from_date then lo end);
end
$$;

revoke all on function app.tenant_today(uuid), app.pending_base_version(text, uuid, jsonb),
  app.pending_change_result(text, uuid, app.pending_change_status, text),
  app.pending_change_log(public.pending_change, uuid, text, jsonb, jsonb),
  app.pending_change_resolve(uuid, app.pending_change_status, uuid),
  app.pending_change_fail(public.pending_change, uuid, text, text),
  app.pending_change_denial(public.pending_change, public.membership),
  app.dish_cost_backfill_range(uuid, date), app.recompute_after_change(uuid, date),
  app.apply_ingredient_price(public.pending_change),
  app.apply_menu_item_price(public.pending_change), app.apply_batch_change(public.pending_change, uuid),
  app.pending_change_write(public.pending_change, uuid), app.apply_pending_change(uuid, uuid),
  app.backfill_dish_costs(uuid, date, int)
  from public, anon, authenticated;
-- the proposer (confirmation service, importer) computes base_version with the same function
grant execute on function app.tenant_today(uuid), app.pending_base_version(text, uuid, jsonb),
  app.apply_pending_change(uuid, uuid), app.backfill_dish_costs(uuid, date, int) to service_role;
