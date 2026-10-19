-- Layers: privilege, policy, privileged role. Client roles cannot write any table; each layer
-- fails with its own error (spec 7.1, 10.4).
begin;
select * from no_plan();

create function pg_temp.attempt(r text, stmt text) returns text language plpgsql as $$
begin
  execute format('set local role %I', r);
  perform set_config('request.jwt.claims', '{"role":"authenticated","tenant_id":"aaaaaaaa-0000-7000-8000-000000000001","location_ids":null}', true);
  begin
    execute stmt;
    reset role;
    return 'OK';
  exception when others then
    reset role;
    return 'ERR ' || sqlstate || ' ' || sqlerrm;
  end;
end $$;

-- 1. SQL-privilege layer: every client role, every write, every table
create temp table ops (op text primary key, tpl text not null);
insert into ops values
  ('insert',   'insert into public.%I default values'),
  ('update',   'update public.%I set id = id'),
  ('delete',   'delete from public.%I where false'),
  ('truncate', 'truncate public.%I');
create temp table roles (r text primary key);
insert into roles values ('anon'), ('authenticated');
create temp table denial as
select c.relname::text as tbl, r.r, o.op, pg_temp.attempt(r.r, format(o.tpl, c.relname)) as outcome
from pg_class c cross join roles r cross join ops o
where c.relnamespace = 'public'::regnamespace and c.relkind = 'r';
select diag(format('NOT DENIED: %s %s on %s -> %s', r, op, tbl, outcome))
from denial where outcome is distinct from format('ERR 42501 permission denied for table %s', tbl);
select is((select count(*) from denial), 320::bigint, '40 tables x 2 client roles x 4 write operations were attempted');
select is((select count(*) from denial where outcome is distinct from format('ERR 42501 permission denied for table %s', tbl)),
          0::bigint, 'every client write is refused at the privilege layer (permission denied for table)');

-- 2. RLS layer: a table with a grant but no policy refuses the row, with a different error
create table public.zz_rls (id uuid primary key default gen_random_uuid(), tenant_id uuid not null);
alter table public.zz_rls enable row level security;
grant select, insert on public.zz_rls to authenticated;
select is(pg_temp.attempt('authenticated', $$insert into public.zz_rls (tenant_id) values ('aaaaaaaa-0000-7000-8000-000000000001')$$),
          'ERR 42501 new row violates row-level security policy for table "zz_rls"', 'RLS layer: the row is refused by policy, not by privilege');

-- 3. Privileged roles: service_role writes (bypasses RLS), but keys still hold
select is(pg_temp.attempt('service_role', $$insert into public.tenant (id, name) values ('aaaaaaaa-0000-7000-8000-000000000001', 'A')$$), 'OK', 'service_role can write a tenant row');
select is(pg_temp.attempt('service_role', $$insert into public.location (tenant_id, name, timezone) values ('aaaaaaaa-0000-7000-8000-000000000001', 'Centro', 'America/Mexico_City')$$), 'OK', 'service_role can write through the uuid default');
select ok(pg_temp.attempt('service_role', $$insert into public.location (tenant_id, name, timezone) values ('bbbbbbbb-0000-7000-8000-000000000002', 'Orphan', 'America/Mexico_City')$$) like 'ERR 23503%',
          'service_role cannot create a location for a tenant that does not exist (foreign key)');

-- 4. audit_log: append-only for every role
select is(pg_temp.attempt('service_role', $$insert into public.audit_log (tenant_id, actor_kind, action) values ('aaaaaaaa-0000-7000-8000-000000000001', 'system', 'test')$$), 'OK', 'service_role can append to audit_log');
select is(pg_temp.attempt('service_role', 'update public.audit_log set action = action'), 'ERR 42501 permission denied for table audit_log', 'service_role cannot update audit_log (privilege)');
select is(pg_temp.attempt('service_role', 'delete from public.audit_log'), 'ERR 42501 permission denied for table audit_log', 'service_role cannot delete from audit_log (privilege)');
select is(pg_temp.attempt('service_role', 'truncate public.audit_log'), 'ERR 42501 permission denied for table audit_log', 'service_role cannot truncate audit_log (privilege)');
select is(pg_temp.attempt('postgres', 'update public.audit_log set action = action'), 'ERR 42501 audit_log is append-only', 'the owner role cannot update audit_log (trigger)');
select is(pg_temp.attempt('postgres', 'delete from public.audit_log'), 'ERR 42501 audit_log is append-only', 'the owner role cannot delete from audit_log (trigger)');
select is(pg_temp.attempt('postgres', 'truncate public.audit_log'), 'ERR 42501 audit_log is append-only', 'the owner role cannot truncate audit_log (trigger)');

-- 5. role membership. SET ROLE is decided by the *session* user, not the current role: PostgREST
-- connects as authenticator, which is a member of service_role by design (V28). So an escalation
-- is only prevented by the absence of any raw-SQL path (spec 7.5.3); these checks pin what the
-- database itself guarantees.
select ok(not pg_has_role('authenticated', 'service_role', 'member'), 'authenticated is not a member of service_role');
select ok(not pg_has_role('anon', 'service_role', 'member'), 'anon is not a member of service_role');
select ok(not pg_has_role('authenticated', 'postgres', 'member'), 'authenticated is not a member of postgres');
select ok(not pg_has_role('authenticator', 'postgres', 'member'), 'the PostgREST login role is not a member of postgres');
select ok(pg_has_role('authenticator', 'service_role', 'member'), 'the PostgREST login role can switch to service_role (so no client may ever reach raw SQL)');

-- 6. the privileged-function pattern future tickets must follow (spec 7.5.7)
create function app.zz_definer(p uuid) returns text language plpgsql security definer set search_path = ''
as $$ begin return 'applied for ' || p::text; end $$;
revoke all on function app.zz_definer(uuid) from public, anon, authenticated;
grant execute on function app.zz_definer(uuid) to service_role;
select is(pg_temp.attempt('authenticated', $$select app.zz_definer(gen_random_uuid())$$), 'ERR 42501 permission denied for function zz_definer', 'a definer function is not executable by authenticated');
select is(pg_temp.attempt('anon', $$select app.zz_definer(gen_random_uuid())$$), 'ERR 42501 permission denied for schema app', 'a definer function is not reachable by anon');
select is(pg_temp.attempt('service_role', $$select app.zz_definer(gen_random_uuid())$$), 'OK', 'a definer function is executable by service_role');

select * from finish();
rollback;
