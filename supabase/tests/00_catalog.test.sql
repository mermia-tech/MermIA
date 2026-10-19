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
              array['current_tenant_id', 'can_see_location', 'has_all_locations', 'has_location_list', 'location_scope_ids',
                    -- MR-17: the read RPCs run as the caller, so the caller runs their helpers
                    'business_today', 'resolve_period', 'previous_period', 'scope_locations', 'fmt_money', 'fmt_number',
                    'fmt_pct', 'figure', 'data_as_of', 'rpc_ok', 'rpc_error', 'flag', 'sales_totals', 'item_rows', 'metric_value'],
              'authenticated executes only the policy helpers and the read-RPC helpers');
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
drop table public.zz_scratch;

-- enums (spec 5.3) -----------------------------------------------------------------
select is((
  with actual as (
    select t.typname::text as name, string_agg(e.enumlabel::text, ',' order by e.enumsortorder) as labels
    from pg_type t join pg_enum e on e.enumtypid = t.oid
    where t.typnamespace = 'app'::regnamespace group by t.typname),
  expected(name, labels) as (values
    ('actor_kind', 'user,system,agent'),
    ('base_unit', 'g,ml,pza'),
    ('batch_quality', 'file,push,ocr'),
    ('batch_status', 'received,rejected,parsed,needs_review,applied,rolled_back,superseded'),
    ('channel', 'whatsapp,web,pos'),
    ('cost_confidence', 'confirmed,estimated,missing'),
    ('fiscal_status', 'none,requested,in_global,stamped'),
    ('ingredient_price_source', 'cfdi,nota,sr_import,manual,benchmark'),
    ('issue_severity', 'info,warning,error'),
    ('llm_route', 'template,haiku,sonnet,fallback'),
    ('member_role', 'owner,manager,admin,support'),
    ('menu_item_kind', 'dish,drink,modifier,combo'),
    ('meta_pricing_category', 'marketing,utility,authentication,service'),
    ('payment_method', 'cash,card,transfer,voucher,other'),
    ('pending_change_status', 'pending,approved,rejected,expired,conflict,applied,failed'),
    ('proposed_via', 'agent,dashboard,import,pos'),
    ('purchase_doc_kind', 'cfdi,nota_photo,manual'),
    ('recipe_status', 'draft,confirmed'),
    ('report_kind', 'weekly,daily'),
    ('sale_channel', 'dine_in,takeout,delivery_app,delivery'),
    ('source_kind', 'sr_report,sr_corte_email,sr_erp_push,sr_connector,cfdi,photo_ocr,manual,mermia_pos'),
    ('supplier_kind', 'cfdi,market,other'),
    ('ticket_status', 'paid,cancelled'),
    ('yield_source', 'default,measured'))
  select count(*) from expected e full join actual a on a.name = e.name where e.labels is distinct from a.labels),
  0::bigint, 'enums in app match spec 5.3 (24 types, ordered labels)');

-- the 40 tables and their access class (spec 7.2.2) -------------------------------------------------------------
create temp table expected_class (tbl text primary key, cls text not null);
insert into expected_class values
  ('tenant','rls_class=T'),('supplier','rls_class=T'),('ingredient','rls_class=T'),('ingredient_alias','rls_class=T'),
  ('unit_conversion','rls_class=T'),('purchase_doc','rls_class=T'),('purchase_line','rls_class=T'),
  ('ingredient_price','rls_class=T'),('recipe','rls_class=T'),('recipe_line','rls_class=T'),
  ('location','rls_class=L;loc_col=id'),('source','rls_class=L;loc_col=location_id'),
  ('import_batch','rls_class=L;loc_col=location_id'),('menu_item_price','rls_class=L;loc_col=location_id'),
  ('sale_ticket','rls_class=L;loc_col=location_id'),('sale_line','rls_class=L;loc_col=location_id'),
  ('payment','rls_class=L;loc_col=location_id'),('item_sales_agg','rls_class=L;loc_col=location_id'),
  ('daily_sales_agg','rls_class=L;loc_col=location_id'),('dish_cost_snapshot','rls_class=L;loc_col=location_id'),
  ('menu_category','rls_class=L;loc_col=location_id'),('menu_item','rls_class=L;loc_col=location_id'),
  ('modifier_link','rls_class=L;loc_col=location_id'),('staff','rls_class=L;loc_col=location_id'),
  ('daily_location_metrics','rls_class=L;loc_col=location_id'),('alert','rls_class=L;loc_col=location_id'),
  ('price_suggestion','rls_class=L;loc_col=location_id'),
  ('import_issue','rls_class=LP'),
  ('pending_change','rls_class=F'),('audit_log','rls_class=F'),
  ('app_user','rls_class=X'),('channel_identity','rls_class=X'),('consent_log','rls_class=X'),
  ('membership','rls_class=X'),('raw_file','rls_class=X'),('report_run','rls_class=X'),
  ('external_ref','rls_class=X'),('conversation','rls_class=X'),('llm_usage','rls_class=X'),('message_log','rls_class=X');

select is((select count(*) from expected_class), 40::bigint, 'the expected list has 40 tables');
select is((select count(*) from pg_class c full join expected_class e on e.tbl = c.relname
           where (c.relnamespace = 'public'::regnamespace and c.relkind = 'r' and e.tbl is null)
              or (e.tbl is not null and c.oid is null)),
          0::bigint, 'public holds exactly the 40 domain tables');
select is((select count(*) from pg_class c join expected_class e on e.tbl = c.relname
           where c.relnamespace = 'public'::regnamespace and obj_description(c.oid, 'pg_class') is distinct from e.cls),
          0::bigint, 'every table carries the access class of spec 7.2.2');
select is((select count(*) from pg_class where relnamespace = 'public'::regnamespace and relkind not in ('r', 'i')),
          0::bigint, 'no view, sequence or other relation in public');
select is((select count(*) from pg_proc where pronamespace = 'public'::regnamespace), 0::bigint, 'no function in public (spec 7.5.3)');
select is((select count(*) from pg_proc where pronamespace in ('public'::regnamespace, 'app'::regnamespace)
           and (prosrc ilike '%request.jwt%' or prosrc ilike '%set_config%')),
          0::bigint, 'no function in public or app reads or sets request.jwt settings directly');

-- RLS and policies ------------------------------------------------------------------------------------------------
select is((select count(*) from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r' and not c.relrowsecurity),
          0::bigint, 'RLS is enabled on every table');
select is((select count(*) from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r' and c.relforcerowsecurity),
          0::bigint, 'no table forces RLS (definers check tenant themselves)');
select is((select count(*) from expected_class e join pg_class c on c.relname = e.tbl and c.relnamespace = 'public'::regnamespace
           where (e.cls = 'rls_class=X') <> (not exists (select 1 from pg_policy p where p.polrelid = c.oid))),
          0::bigint, 'class X tables have no policy and every other table has one');
select is((select count(*) from pg_policy p join pg_class c on c.oid = p.polrelid where c.relnamespace = 'public'::regnamespace
           and (p.polcmd <> 'r' or p.polname <> 'rls_select' or p.polroles <> array['authenticated'::regrole]::oid[])),
          0::bigint, 'every policy is a SELECT policy for authenticated named rls_select');
select is((select count(*) from (select polrelid from pg_policy group by polrelid having count(*) > 1) x), 0::bigint, 'at most one policy per table');
select is((select count(*) from pg_policy p join pg_class c on c.oid = p.polrelid join expected_class e on e.tbl = c.relname
           where not (case
             when e.cls like '%loc_col=%' then pg_get_expr(p.polqual, p.polrelid) like '%location_scope_ids%' and pg_get_expr(p.polqual, p.polrelid) like '%has_location_list%'
                  and pg_get_expr(p.polqual, p.polrelid) like '%has_all_locations%' and pg_get_expr(p.polqual, p.polrelid) like '%current_tenant_id%'
             when e.cls = 'rls_class=F' then pg_get_expr(p.polqual, p.polrelid) like '%has_all_locations%' and pg_get_expr(p.polqual, p.polrelid) like '%current_tenant_id%'
             when e.cls = 'rls_class=LP' then pg_get_expr(p.polqual, p.polrelid) ilike '%exists%' and pg_get_expr(p.polqual, p.polrelid) like '%import_batch%'
             else pg_get_expr(p.polqual, p.polrelid) like '%current_tenant_id%' end)),
          0::bigint, 'each policy expression matches its class (tenant, location, all-locations, parent)');
-- MR-14: claim helpers run once per statement (init plan), never per row (MR-53 item 7)
select is((select count(*) from pg_policy p join pg_class c on c.oid = p.polrelid where c.relnamespace = 'public'::regnamespace
           and (pg_get_expr(p.polqual, p.polrelid) like '%can_see_location%'
                or regexp_replace(pg_get_expr(p.polqual, p.polrelid), 'SELECT app\.', 'SELECT x.', 'g')
                   ~ 'app\.(current_tenant_id|has_all_locations|has_location_list|location_scope_ids)\(')),
          0::bigint, 'policies call the claim helpers only inside (select ...)');

-- privileges (spec 7.1) --------------------------------------------------------------------------------------------------
select is((select count(*) from expected_class e where has_any_column_privilege('anon', ('public.' || e.tbl)::regclass, 'select,insert,update,references')),
          0::bigint, 'anon holds no privilege on any table');
select is((select count(*) from expected_class e where has_any_column_privilege('authenticated', ('public.' || e.tbl)::regclass, 'insert,update,references')
                or has_table_privilege('authenticated', ('public.' || e.tbl)::regclass, 'delete,truncate,trigger')),
          0::bigint, 'authenticated holds no write or structural privilege on any table');
select is((select count(*) from expected_class e where e.cls = 'rls_class=X' and has_any_column_privilege('authenticated', ('public.' || e.tbl)::regclass, 'select')),
          0::bigint, 'authenticated reads no class X table');
select is((select count(*) from expected_class e where e.cls <> 'rls_class=X' and e.tbl <> 'source' and not has_table_privilege('authenticated', ('public.' || e.tbl)::regclass, 'select')),
          0::bigint, 'authenticated can select every client-readable table except source, which is column-limited');
select is((select count(*) from expected_class e where e.tbl <> 'audit_log' and not has_table_privilege('service_role', ('public.' || e.tbl)::regclass, 'select,insert,update,delete')),
          0::bigint, 'service_role keeps full access to every table except audit_log');

-- units, notes and text integrity (spec 5.1, 5.4) ---------------------------------------------------------------------
select is((select count(*) from pg_attribute a join pg_class c on c.oid = a.attrelid
           where c.relnamespace = 'public'::regnamespace and c.relkind = 'r' and a.attnum > 0 and not a.attisdropped
             and a.atttypid in ('bigint'::regtype, 'numeric'::regtype)
             and col_description(c.oid, a.attnum) is null
             and (c.relname, a.attname) not in (('alert','value'),('alert','threshold'),('price_suggestion','value'),('price_suggestion','threshold'))),
          0::bigint, 'every bigint and numeric column carries a unit tag (alert and suggestion values are the documented exceptions)');
select is((select count(*) from pg_attribute a join pg_class c on c.oid = a.attrelid
           where c.relnamespace = 'public'::regnamespace and c.relkind = 'r' and a.attnum > 0 and not a.attisdropped
             and a.atttypid in ('bigint'::regtype, 'numeric'::regtype) and col_description(c.oid, a.attnum) is not null
             and not (
               (a.atttypid = 'bigint'::regtype and col_description(c.oid, a.attnum) in ('unit=centavos', 'unit=bytes'))
               or (format_type(a.atttypid, a.atttypmod) = 'numeric(20,6)' and col_description(c.oid, a.attnum) in ('unit=pesos_per_base_unit', 'unit=pesos_per_purchase_unit'))
               or (format_type(a.atttypid, a.atttypmod) = 'numeric(18,6)' and col_description(c.oid, a.attnum) = 'unit=quantity')
               or (format_type(a.atttypid, a.atttypmod) = 'numeric(20,10)' and col_description(c.oid, a.attnum) = 'unit=quantity')
               or (format_type(a.atttypid, a.atttypmod) = 'numeric(7,4)' and col_description(c.oid, a.attnum) = 'unit=percent_points')
               or (format_type(a.atttypid, a.atttypmod) = 'numeric(5,4)' and col_description(c.oid, a.attnum) = 'unit=fraction')
               or (format_type(a.atttypid, a.atttypmod) = 'numeric(12,6)' and col_description(c.oid, a.attnum) = 'unit=usd')
               or (c.relname in ('alert', 'price_suggestion') and a.attname in ('value', 'threshold')))),
          0::bigint, 'each unit tag matches its column type (centavos bigint, pesos numeric(20,6), percent points numeric(7,4), ...)');
select is((select count(*) from pg_attribute a join pg_class c on c.oid = a.attrelid
           where c.relnamespace = 'public'::regnamespace and c.relkind = 'r' and a.attnum > 0 and not a.attisdropped
             and a.atttypid in ('text'::regtype, 'character varying'::regtype)
             and not exists (select 1 from pg_constraint k where k.conrelid = c.oid and k.contype = 'c' and k.conname = a.attname || '_not_blank'
                             and position('~ ''[^\t\n\v\f\r \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]''' in pg_get_constraintdef(k.oid)) > 0)),
          0::bigint, 'every text column rejects blank strings (Unicode whitespace, as the contract''s Text)');

-- composite foreign keys (D18) ---------------------------------------------------------------------------------------------
select is((select count(*) from pg_constraint k
           join pg_class child on child.oid = k.conrelid and child.relnamespace = 'public'::regnamespace
           join pg_class parent on parent.oid = k.confrelid and parent.relnamespace = 'public'::regnamespace
           where k.contype = 'f'
             and exists (select 1 from pg_attribute a where a.attrelid = parent.oid and a.attname = 'tenant_id' and not a.attisdropped)
             and not (select a.attnum from pg_attribute a where a.attrelid = child.oid and a.attname = 'tenant_id') = any (k.conkey)),
          0::bigint, 'every foreign key into a tenant-scoped table includes tenant_id');
select is((select count(*) from pg_constraint k
           join pg_class child on child.oid = k.conrelid and child.relnamespace = 'public'::regnamespace
           join pg_class parent on parent.oid = k.confrelid and parent.relnamespace = 'public'::regnamespace
           where k.contype = 'f' and k.confdeltype <> 'r'),
          0::bigint, 'every foreign key restricts deletes');
select is((select count(*) from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
           and exists (select 1 from pg_attribute a where a.attrelid = c.oid and a.attname = 'tenant_id' and not a.attisdropped)
           and not exists (select 1 from pg_constraint k where k.conrelid = c.oid and k.contype in ('u','p')
                           and (select array_agg(att.attname::text order by att.attname) from pg_attribute att where att.attrelid = c.oid and att.attnum = any (k.conkey)) = array['id','tenant_id'])),
          0::bigint, 'every tenant-scoped table has unique (tenant_id, id) as composite-FK parent key');

select * from finish();
rollback;
