-- MR-98: location.timezone only takes real IANA zone names.
begin;
select * from no_plan();

select is(app.is_valid_timezone('America/Mexico_City'), true, 'a real zone is valid');
select is(app.is_valid_timezone('UTC'), true, 'UTC is valid');
select is(app.is_valid_timezone('America/Mexico City'), false, 'a space instead of underscore is invalid');
select is(app.is_valid_timezone('Mars/Olympus'), false, 'an unknown zone is invalid');
select is(app.is_valid_timezone(''), false, 'empty is invalid');
select is(app.is_valid_timezone('+05'), false, 'a bare offset is invalid');
select is(app.is_valid_timezone(null), false, 'null is not valid');

select ok(has_function_privilege('service_role', 'app.is_valid_timezone(text)', 'execute')
          and not has_function_privilege('authenticated', 'app.is_valid_timezone(text)', 'execute')
          and not has_function_privilege('anon', 'app.is_valid_timezone(text)', 'execute'),
          'only the backend (the one writer of location) can run the check');

select is((select count(*) from public.location where not app.is_valid_timezone(timezone)), 0::bigint,
          'every seeded location passes');
select is((select convalidated from pg_constraint where conname = 'location_timezone_valid'), true,
          'the constraint is validated');

insert into public.tenant (id, name) values ('aaaaaaaa-0000-7000-8000-0000000000e1', 'TZ tenant');
select lives_ok($$insert into public.location (tenant_id, name, timezone)
                  values ('aaaaaaaa-0000-7000-8000-0000000000e1', 'Ok', 'America/Mexico_City')$$,
                'a valid zone is accepted');
select throws_ok($$insert into public.location (tenant_id, name, timezone)
                   values ('aaaaaaaa-0000-7000-8000-0000000000e1', 'Bad', 'Mars/Olympus')$$,
                 '23514', 'new row for relation "location" violates check constraint "location_timezone_valid"',
                 'an unknown zone is rejected');
select throws_ok($$insert into public.location (tenant_id, name, timezone)
                   values ('aaaaaaaa-0000-7000-8000-0000000000e1', 'Bad', '')$$,
                 '23514', null, 'empty is rejected');
select throws_ok($$insert into public.location (tenant_id, name, timezone)
                   values ('aaaaaaaa-0000-7000-8000-0000000000e1', 'Bad', '+05')$$,
                 '23514', null, 'a bare offset is rejected');
select throws_ok($$update public.location set timezone = 'America/Mexico City'
                   where tenant_id = 'aaaaaaaa-0000-7000-8000-0000000000e1'$$,
                 '23514', null, 'an update to a bad zone is rejected');

select * from finish();
rollback;
