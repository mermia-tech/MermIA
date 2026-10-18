-- Layer: all. Structure, privileges, helper grants (spec 7.1, 7.4, 10.4).
begin;
select * from no_plan();

-- helper functions and grants (foundations) --------------------------------
select is((select count(*) from pg_proc p where p.pronamespace = 'app'::regnamespace
           and (p.proacl is null or exists (select 1 from aclexplode(p.proacl) a where a.grantee = 0))),
          0::bigint, 'no function in app is executable by PUBLIC');
select is((select count(*) from pg_proc p where p.pronamespace = 'app'::regnamespace and has_function_privilege('anon', p.oid, 'execute')),
          0::bigint, 'anon executes nothing in app');
select set_eq($$select p.proname::text from pg_proc p where p.pronamespace = 'app'::regnamespace and has_function_privilege('authenticated', p.oid, 'execute')$$,
              array['current_tenant_id', 'can_see_location', 'has_all_locations'], 'authenticated executes only the three policy helpers');
select ok(has_function_privilege('service_role', 'app.uuid_v7(timestamptz)', 'execute'), 'service_role can run the uuid default');
select ok(has_schema_privilege('authenticated', 'app', 'usage'), 'authenticated has usage on app');
select ok(has_schema_privilege('service_role', 'app', 'usage'), 'service_role has usage on app');
select ok(not has_schema_privilege('anon', 'app', 'usage'), 'anon has no usage on app');

-- roles ------------------------------------------------------------------------
select ok((select rolbypassrls from pg_roles where rolname = 'service_role'), 'service_role bypasses RLS');
select ok((select rolbypassrls from pg_roles where rolname = 'postgres'), 'postgres bypasses RLS (so definers must check tenant themselves)');
select ok(not (select rolbypassrls from pg_roles where rolname = 'authenticated'), 'authenticated does not bypass RLS');
select ok(not (select rolbypassrls from pg_roles where rolname = 'anon'), 'anon does not bypass RLS');

-- default privileges on public are revoked for client roles ---------------------
create table public.zz_scratch (id int);
select ok(not has_any_column_privilege('anon', 'public.zz_scratch', 'select,insert,update,references'), 'new public table: anon has no privilege');
select ok(not has_any_column_privilege('authenticated', 'public.zz_scratch', 'select,insert,update,references'), 'new public table: authenticated has no privilege');
select ok(has_table_privilege('service_role', 'public.zz_scratch', 'select,insert,update,delete'), 'new public table: service_role keeps its privileges');

select * from finish();
rollback;
