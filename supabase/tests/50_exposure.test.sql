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

-- relationships from client-readable tables into backend-only tables (spec 7.2.5) -----------------------------
-- A client may try to embed these (for example import_batch?select=*,raw_file(*)). The target tables are
-- class X, so the embedded data is refused; this snapshot makes a new relationship a reviewed change.
select is((
  with cls as (select c.oid, c.relname, split_part(split_part(obj_description(c.oid, 'pg_class'), ';', 1), '=', 2) as k
              from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r')
  select string_agg(rel, '; ' order by rel) from (
    select child.relname || '.' || (select string_agg(a.attname, '+' order by a.attnum) from pg_attribute a
                    where a.attrelid = child.oid and a.attnum = any (k.conkey) and a.attname <> 'tenant_id') || ' -> ' || parent.relname as rel
    from pg_constraint k join cls child on child.oid = k.conrelid join cls parent on parent.oid = k.confrelid
    where k.contype = 'f' and child.k <> 'X' and parent.k = 'X') q),
  'audit_log.actor_user_id -> app_user; import_batch.applied_by -> app_user; import_batch.raw_file_id -> raw_file; import_batch.rolled_back_by -> app_user; ingredient_alias.confirmed_by -> app_user; pending_change.proposed_by_user -> app_user; pending_change.resolved_by -> app_user; purchase_doc.raw_file_id -> raw_file',
  'the foreign keys from readable tables into backend-only tables are exactly the reviewed ones');
select is((select count(*) from (values ('app_user'), ('raw_file')) t(x)
           where has_any_column_privilege('authenticated', ('public.' || x)::regclass, 'select')), 0::bigint,
          'the targets of those relationships are not readable by authenticated');

-- no view, function or sequence can bypass the table privileges (spec 7.2.5) --------------------------------
select is((select count(*) from pg_class where relnamespace = 'public'::regnamespace and relkind in ('v', 'm', 'S', 'f', 'p')), 0::bigint, 'public has no view, materialized view, sequence, foreign table or partitioned table');
select is((select count(*) from pg_proc where pronamespace = 'public'::regnamespace), 0::bigint, 'public has no function');
-- MR-17: views live in `app` and run as the caller, so RLS applies (spec 8.1)
select is((select count(*) from pg_class c where c.relnamespace = 'app'::regnamespace and c.relkind in ('v', 'm')
           and not coalesce('security_invoker=true' = any (c.reloptions), false)), 0::bigint, 'every view in app is security_invoker');
select set_eq($$select relname::text from pg_class where relnamespace = 'app'::regnamespace and relkind in ('v', 'm')$$,
              array['v_ticket_days', 'v_daily_agg', 'v_daily_sales', 'v_item_sales_daily'], 'app holds the reviewed views only');
-- MR-17: the read RPCs live in `api`, the one schema besides public the Data API exposes for us
select is((select count(*) from pg_class where relnamespace = 'api'::regnamespace), 0::bigint, 'api has no table, view or sequence');
select set_eq($$select proname::text from pg_proc where pronamespace = 'api'::regnamespace$$,
              array['get_sales_summary', 'compare_periods', 'get_top_dishes', 'get_data_status'], 'api holds the read RPCs only');
select is((select count(*) from pg_proc where pronamespace = 'api'::regnamespace and prosecdef), 0::bigint,
          'every RPC is SECURITY INVOKER, so RLS applies (09 section 4.1)');
select is((select count(*) from pg_proc where pronamespace = 'api'::regnamespace
           and (has_function_privilege('anon', oid, 'execute') or not has_function_privilege('authenticated', oid, 'execute')
                or proacl is null or exists (select 1 from aclexplode(proacl) a where a.grantee = 0))), 0::bigint,
          'only authenticated runs the RPCs (not anon, not PUBLIC)');
select ok(not has_schema_privilege('anon', 'api', 'usage'), 'anon has no usage on api');
select is((select count(*) from pg_proc where pronamespace in ('api'::regnamespace, 'app'::regnamespace)
           and (prosrc ilike '%request.jwt%' or prosrc ilike '%set_config%')), 0::bigint, 'no RPC reads or sets request.jwt settings directly');
select is((select count(*) from pg_trigger t join pg_class c on c.oid = t.tgrelid where c.relnamespace = 'public'::regnamespace and not t.tgisinternal
           and t.tgname not in ('touch_row', 'membership_locations', 'audit_log_no_row_mutation', 'audit_log_no_truncate',
                              'recipe_line_structure')), 0::bigint,
          'only the reviewed triggers exist');

-- membership scope: the explicit flag (A12, A19) -----------------------------------------------------------------
select is((select pg_get_expr(adbin, adrelid) from pg_attrdef d join pg_attribute a on a.attrelid = d.adrelid and a.attnum = d.adnum
           where a.attrelid = 'public.membership'::regclass and a.attname = 'all_locations'), 'false', 'all_locations defaults to false');
select is((select pg_get_expr(adbin, adrelid) from pg_attrdef d join pg_attribute a on a.attrelid = d.adrelid and a.attnum = d.adnum
           where a.attrelid = 'public.membership'::regclass and a.attname = 'location_ids'), '''{}''::uuid[]', 'location_ids defaults to the empty list');

-- the audit trail cannot be bypassed by a function in the schema either (spec 7.2.6) ----------------------
-- The owner role can still switch replica mode or disable a trigger by hand; the database cannot
-- prevent that, so no function we ship may do it.
select is((select count(*) from pg_proc where pronamespace in ('public'::regnamespace, 'app'::regnamespace)
           and (prosrc ilike '%session_replication_role%' or prosrc ilike '%disable trigger%'
                or prosrc ilike '%enable always%' or prosrc ilike '%enable replica%')), 0::bigint,
          'no function in public or app switches replica mode or disables triggers');

select * from finish();
rollback;
