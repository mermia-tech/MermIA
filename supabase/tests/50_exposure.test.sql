-- Layer: all. Indirect exposure paths and column privileges (spec 7.2.5, 10.4).
begin;
select * from no_plan();

-- source: hidden columns (A1) --------------------------------------------------------------
select ok(not has_column_privilege('authenticated', 'public.source', 'config', 'select'), 'source.config is not readable by authenticated');
select ok(not has_column_privilege('authenticated', 'public.source', 'api_key_hash', 'select'), 'source.api_key_hash is not readable by authenticated');
select ok(has_column_privilege('authenticated', 'public.source', 'kind', 'select'), 'source.kind is readable by authenticated');
select ok(not has_table_privilege('authenticated', 'public.source', 'select'), 'source has no table-level select for authenticated');
select ok(not has_any_column_privilege('anon', 'public.source', 'select'), 'anon reads no column of source');

-- audit_log privileges are explicit (spec 7.2.6) ----------------------------------------------
select ok(has_table_privilege('authenticated', 'public.audit_log', 'select'), 'authenticated may read audit_log through the class F policy');
select ok(not has_table_privilege('authenticated', 'public.audit_log', 'insert,update,delete,truncate,references,trigger'), 'authenticated has no write or structural privilege on audit_log');
select ok(has_table_privilege('service_role', 'public.audit_log', 'select'), 'service_role may read audit_log');
select ok(has_table_privilege('service_role', 'public.audit_log', 'insert'), 'service_role may append to audit_log');
select ok(not has_table_privilege('service_role', 'public.audit_log', 'update'), 'service_role cannot update audit_log');
select ok(not has_table_privilege('service_role', 'public.audit_log', 'delete'), 'service_role cannot delete audit_log');
select ok(not has_table_privilege('service_role', 'public.audit_log', 'truncate'), 'service_role cannot truncate audit_log');
select ok(not has_table_privilege('service_role', 'public.audit_log', 'references'), 'service_role cannot add references to audit_log');
select ok(not has_table_privilege('service_role', 'public.audit_log', 'trigger'), 'service_role cannot add triggers to audit_log');
select ok(not has_any_column_privilege('anon', 'public.audit_log', 'select,insert,update,references'), 'anon has no privilege on audit_log');

select * from finish();
rollback;
