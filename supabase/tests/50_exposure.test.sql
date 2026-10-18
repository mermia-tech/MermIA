-- Layer: all. Indirect exposure paths and column privileges (spec 7.2.5, 10.4).
begin;
select * from no_plan();

-- source: hidden columns (A1) --------------------------------------------------------------
select ok(not has_column_privilege('authenticated', 'public.source', 'config', 'select'), 'source.config is not readable by authenticated');
select ok(not has_column_privilege('authenticated', 'public.source', 'api_key_hash', 'select'), 'source.api_key_hash is not readable by authenticated');
select ok(has_column_privilege('authenticated', 'public.source', 'kind', 'select'), 'source.kind is readable by authenticated');
select ok(not has_table_privilege('authenticated', 'public.source', 'select'), 'source has no table-level select for authenticated');
select ok(not has_any_column_privilege('anon', 'public.source', 'select'), 'anon reads no column of source');

select * from finish();
rollback;
