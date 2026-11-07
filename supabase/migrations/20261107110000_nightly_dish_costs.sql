-- MR-100: the nightly dish-cost job. Every tenant gets a dish_cost_snapshot row for every active dish
-- at each location's own business today (and a short catch-up window before it), even on a day
-- nobody approves a change. The job (apps/api mermia_api.costing.nightly) runs tenants one at a time
-- and calls app.fill_dish_costs once per chunk of at most 31 days, each in its own transaction.
--
-- Insert only, like MR-86's app.fill_dish_costs_today: a row that exists keeps its id and values
-- (a tap or a backfill already rewrote it from the inputs it changed), a rerun writes nothing. The
-- rows it writes are the ones app.compute_dish_costs writes for those days: same change days, same
-- app.write_dish_cost_rows.

-- The job's window for a tenant: from the earliest location's today minus (days - 1) to the latest
-- location's today. Nulls for a tenant without locations (nothing to cost).
create function app.nightly_dish_cost_range(tenant uuid, days int, out from_date date, out to_date date)
language plpgsql stable set search_path = ''
as $$
begin
  if days is null or days not between 1 and 400 then
    raise exception 'days must be between 1 and 400' using errcode = '22023';
  end if;
  select min(x.d) - (days - 1), max(x.d) into from_date, to_date
  from (select app.business_today(l.id) as d from public.location l where l.tenant_id = tenant) x;
end
$$;

-- Fill [from_date, to_date] (at most 31 days), capped at each location's own today, for every
-- active item with a menu price on a day there that has no snapshot yet. Takes the per-tenant lock
-- (held to commit). Returns the number of rows written.
create function app.fill_dish_costs(tenant uuid, from_date date, to_date date) returns int
language plpgsql set search_path = ''
as $$
declare
  g record;
  hi date;
  item uuid;
  days date[];
  written int := 0;
begin
  if from_date is null or to_date is null or from_date > to_date or to_date - from_date >= 31 then
    raise exception 'invalid range % .. % (at most 31 days)', from_date, to_date using errcode = '22023';
  end if;
  perform app.lock_dish_costs(tenant);
  for g in  -- the locations that share a business today, never filled past it
    select x.d, array_agg(x.id order by x.id) as locations
    from (select l.id, app.business_today(l.id) as d from public.location l where l.tenant_id = tenant) x
    where x.d >= from_date
    group by x.d
    order by x.d
  loop
    hi := least(to_date, g.d);
    for item in
      select m.id from public.menu_item m
      where m.tenant_id = tenant and m.is_active
        and exists (  -- a (location, day) with a menu price and no snapshot
          select 1
          from public.menu_item_price p
          cross join lateral generate_series(
            0, least(coalesce(p.effective_to, hi), hi) - greatest(p.effective_from, from_date)) k
          where p.tenant_id = tenant and p.menu_item_id = m.id and p.location_id = any (g.locations)
            and p.effective_from <= hi and (p.effective_to is null or p.effective_to >= from_date)
            and not exists (select 1 from public.dish_cost_snapshot s
                            where s.tenant_id = tenant and s.menu_item_id = m.id and s.location_id = p.location_id
                              and s.date = greatest(p.effective_from, from_date) + k))
      order by m.id
    loop
      days := app.dish_cost_change_days(item, from_date, hi);
      for i in 1 .. cardinality(days) loop
        -- the inputs hold until the next change day; existing rows are kept (on conflict do nothing)
        written := written + app.write_dish_cost_rows(tenant, item, days[i], coalesce(days[i + 1] - 1, hi), g.locations);
      end loop;
    end loop;
  end loop;
  return written;
end
$$;

revoke all on function app.nightly_dish_cost_range(uuid, int), app.fill_dish_costs(uuid, date, date)
  from public, anon, authenticated;
-- the job runs as service_role (invoker rights); it needs each location's business today, which
-- clients (authenticated) can already read
grant execute on function app.nightly_dish_cost_range(uuid, int), app.fill_dish_costs(uuid, date, date),
  app.business_today(uuid)
  to service_role;
