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
select is(pg_temp.eval('{"location_ids":null}', 'app.can_see_location(null::uuid)'), 'true', 'a null location column is tenant-level and visible');

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

select * from finish();
rollback;
