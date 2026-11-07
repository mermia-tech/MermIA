-- MR-98 (A1): get_sales_summary answers invalid_args only from its argument check (the period).
-- A 22023 raised after it (an unknown location time zone in app.business_today, a nested helper)
-- is bad data or a bug of ours, so it now comes back as internal, as build_weekly_report does.
-- The body is the one from 20261019200000_read_rpcs_first4.sql, unchanged except that the business
-- date is read before the argument block and the period is resolved inside it.
--
-- Left for after the unmerged stack (#77 -> #91 -> #94 -> #97) lands, because it redefines them:
-- api.compare_periods and api.get_top_dishes (#77, 20261104090200_iva_by_tax_rate.sql), and the
-- read RPCs it adds. api.get_data_status (#97) has no 22023 handler.

create or replace function api.get_sales_summary(period jsonb, location_id uuid default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  today date;
  r date[];
  p date[];
  s record;
  prev record;
  change numeric;
  missing text[] := '{}';
  flags jsonb := '[]';
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  today := app.business_today(location_id);
  -- the arguments: a 22023 here is the caller's
  begin
    r := app.resolve_period(period, today);
  exception when sqlstate '22023' then
    return app.rpc_error('invalid_args', sqlerrm, locs);
  end;
  select * into s from app.sales_totals(locs, r[1], r[2]);
  if s.covered_days = 0 then
    return app.rpc_error('no_data', 'No sales loaded for the period', locs);
  end if;

  p := app.previous_period(period, r);
  select * into prev from app.sales_totals(locs, p[1], p[2]);
  if prev.covered_days > 0 and prev.net_sales > 0 then
    change := round(100.0 * (s.net_sales - prev.net_sales) / prev.net_sales, 4);
    if prev.expected_covered < prev.expected_days then
      flags := flags || app.flag('previous_partial', 'Faltan días en el periodo anterior: la comparación es aproximada.');
    end if;
  end if;

  if s.expected_covered < s.expected_days then
    flags := flags || app.flag('missing_days',
      format('Faltan datos de %s de %s días del periodo.', s.expected_days - s.expected_covered, s.expected_days));
  end if;
  if s.tickets is null then missing := missing || 'tickets'::text; end if;
  if s.guests is null then missing := missing || 'comensales'::text; end if;
  if s.discounts is null then missing := missing || 'descuentos'::text; end if;
  if s.cancellations is null then missing := missing || 'cancelaciones'::text; end if;
  if cardinality(missing) > 0 then
    flags := flags || app.flag('partial_data', 'La fuente no reporta: ' || array_to_string(missing, ', ') || '.');
  end if;

  return app.rpc_ok(
    jsonb_build_object(
      'net_sales', jsonb_build_object('raw', s.net_sales, 'text', app.fmt_money(s.net_sales)),
      'tickets', s.tickets,
      'avg_ticket', case when s.tickets > 0 then jsonb_build_object(
        'raw', round(s.net_sales::numeric / s.tickets),
        'text', app.fmt_money(round(s.net_sales::numeric / s.tickets))) end,
      'guests', s.guests,
      'discounts', case when s.discounts is not null then
        jsonb_build_object('raw', s.discounts, 'text', app.fmt_money(s.discounts)) end,
      'cancellations', case when s.cancellations is not null then
        jsonb_build_object('raw', s.cancellations, 'text', app.fmt_money(s.cancellations)) end,
      'change_vs_previous', case when change is not null then
        jsonb_build_object('raw', trim_scale(change), 'text', app.fmt_pct(change, true)) end),
    locs, flags, 100.0 * s.expected_covered / nullif(s.expected_days, 0), r);
exception when sqlstate '22023' then
  -- past the argument check: bad data or a bug of ours (a location time zone, a helper)
  return app.rpc_error('internal', sqlerrm, coalesce(locs, '{}'));
end
$$;
