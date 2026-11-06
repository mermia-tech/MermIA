-- MR-32 part 2: apply_pending_change applies an approved recipe.upsert (09 section 5; MR-25 decision 3).
-- A new confirmed recipe version from the approval day, lines from diff.after.lines (written by the
-- MR-25 importer), new ingredients created or reused by name, tenant-wide approval only.
begin;
select * from no_plan();

\set TENANT '''03299e41-28bd-5779-bcc6-0e5e76580fad'''
\set CENTRO '''705e8e51-376b-5785-adbb-405eff4e2a22'''
\set OWNER '''eb52f6ad-4d75-5b06-9881-9f68f4fb05a0'''
\set LUPITA '''240e45f0-ef48-5654-a835-8fbc70de15bc'''
\set PASTOR '''f496f051-9f85-5f8a-a4b6-c1a814d37c73'''
\set BISTEC '''f6fdf947-ec26-5cd9-90c2-4255b53ceae8'''
\set SUADERO '''78384b44-f9b6-59d0-88c6-e8a5ac27de63'''
\set PASTOR_RECIPE '''685360b3-e141-5c71-9180-a95eae3076e6'''
\set SUADERO_RECIPE '''75c687ec-a6ad-5c54-be29-71f1eb4ca13c'''
\set SALSA_RECIPE '''46faac9d-fc08-5876-af8d-6b3b958b52b3'''
\set CARNE '''356dfff4-d912-542b-b8b0-8ae42068eb7e'''
\set ADMIN '''eeeeeeee-0000-7000-8000-000000000002'''

set local app.today = '2026-10-12';

-- people: an admin with the MR-30 defaults (no recipes) ----------------------------------------
insert into public.app_user (id, name) values (:ADMIN, 'Admin');
insert into public.membership (tenant_id, user_id, role, location_ids, all_locations, can_approve) values
  (:TENANT, :ADMIN, 'admin', null, true, '{ingredient_price.set,menu_item_price.set,import_batch.approve,import_batch.rollback}');

-- helpers ----------------------------------------------------------------------------------------
create temp table pc (name text primary key, id uuid not null);
create temp table tap (name text primary key, res jsonb not null);

-- A dish's recipe of record today as importer lines (diff.after.lines, MR-25 _Line.as_json).
create function pg_temp.lines_of(item uuid) returns jsonb language sql stable as $$
  select jsonb_agg(jsonb_build_object(
           'ingredient_name', i.name, 'ingredient_external_id', null,
           'ingredient_id', coalesce(rl.ingredient_id, sr.produces_ingredient_id), 'sub_recipe_id', rl.sub_recipe_id,
           'new_ingredient', false, 'qty_base', rl.qty_base::text, 'unit', i.base_unit,
           'yield_override_pct', rl.yield_override_pct::text) order by rl.created_at, rl.id)
  from public.recipe_line rl
  left join public.recipe sr on sr.id = rl.sub_recipe_id
  join public.ingredient i on i.id = coalesce(rl.ingredient_id, sr.produces_ingredient_id)
  where rl.recipe_id = app.recipe_of_record(item, null, '2026-10-12')
$$;
create function pg_temp.new_line(name text, qty text, unit text) returns jsonb language sql immutable as $$
  select jsonb_build_object('ingredient_name', name, 'ingredient_external_id', null, 'ingredient_id', null,
                            'sub_recipe_id', null, 'new_ingredient', true, 'qty_base', qty, 'unit', unit,
                            'yield_override_pct', null)
$$;
-- lines with one ingredient's quantity changed
create function pg_temp.set_qty(ls jsonb, ingredient uuid, qty text) returns jsonb language sql immutable as $$
  select jsonb_agg(case when x ->> 'ingredient_id' = ingredient::text then jsonb_set(x, '{qty_base}', to_jsonb(qty)) else x end
                   order by n)
  from jsonb_array_elements(ls) with ordinality as t (x, n)
$$;

-- File a recipe.upsert the way the importer does: payload = RecipeUpsertProposal, diff.after = the
-- resolved lines, base_version from app.pending_base_version (D2).
create function pg_temp.propose(name text, target uuid, ls jsonb, required app.member_role default 'manager')
returns uuid
language sql as $$
  with x as (
    insert into public.pending_change (tenant_id, kind, target_type, target_id, base_version, payload, diff,
                                       proposed_by_user, proposed_via, required_role, expires_at)
    values ('03299e41-28bd-5779-bcc6-0e5e76580fad', 'recipe.upsert', 'menu_item', target,
            app.pending_base_version('recipe.upsert', target, '{}'),
            jsonb_build_object('kind', 'recipe.upsert', 'target_id', target, 'values', jsonb_build_object(
              'yield_qty', '1.000000',
              'lines', (select jsonb_agg(jsonb_build_object('ingredient_name', l ->> 'ingredient_name',
                                                            'ingredient_external_id', l -> 'ingredient_external_id',
                                                            'qty_base', l ->> 'qty_base', 'unit', l ->> 'unit',
                                                            'yield_override_pct', l -> 'yield_override_pct') order by n)
                        from jsonb_array_elements(ls) with ordinality as t (l, n)))),
            jsonb_build_object('after', jsonb_build_object('yield_qty', '1.000000', 'lines', ls)),
            '240e45f0-ef48-5654-a835-8fbc70de15bc', 'import', required, now() + interval '1 day')
    returning id)
  insert into pc select name, id from x
  returning id
$$;
create function pg_temp.pc(name text) returns uuid language sql stable as $$ select id from pc where pc.name = $1 $$;
create function pg_temp.tap(name text, change text, user_id uuid) returns jsonb
language sql as $$
  insert into tap select name, app.apply_pending_change(pg_temp.pc(change), user_id) returning res
$$;
create function pg_temp.status(change text) returns text language sql stable as $$
  select status::text from public.pending_change where id = pg_temp.pc(change)
$$;
create function pg_temp.audits(change text, action text) returns bigint language sql stable as $$
  select count(*) from public.audit_log where pending_change_id = pg_temp.pc(change) and audit_log.action = $2
$$;
create function pg_temp.audit_after(change text, action text) returns jsonb language sql stable as $$
  select after from public.audit_log where pending_change_id = pg_temp.pc(change) and audit_log.action = $2
$$;
create function pg_temp.recipes(item uuid) returns bigint language sql stable as $$
  select count(*) from public.recipe where menu_item_id = item
$$;
create function pg_temp.snap(d date) returns public.dish_cost_snapshot language sql stable as $$
  select * from public.dish_cost_snapshot
  where menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and location_id = '705e8e51-376b-5785-adbb-405eff4e2a22' and date = d
$$;

-- an ingredient the catalog gained after the proposal was filed (another recipe created it)
insert into public.ingredient (id, tenant_id, name, base_unit) values ('eeeeeeee-0000-7000-8000-0000000000e1', :TENANT, 'Epazote', 'g');
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:TENANT, 'eeeeeeee-0000-7000-8000-0000000000e1', 0.20, '2026-10-01', 'cfdi');

select is(app.compute_dish_costs(:TENANT, '2026-10-10', '2026-10-12') > 0, true, 'snapshots exist for today and the days before');
create temp table snap_before as
select date, id, cost from public.dish_cost_snapshot where menu_item_id = :PASTOR and location_id = :CENTRO and date between '2026-10-10' and '2026-10-12';
select is((select count(*) from snap_before), 3::bigint, 'the pastor has a snapshot each day');

-- the version a recipe proposal carries is the recipe of record's recipe_version (D2)
select is(app.pending_base_version('recipe.upsert', :PASTOR, '{}'), 1, 'the pastor recipe is version 1');

-- applied: more meat, plus epazote (proposed as new, now in the catalog: reused) -----------------
select pg_temp.propose('pastor', :PASTOR,
                       pg_temp.set_qty(pg_temp.lines_of(:PASTOR), :CARNE, '80.000000') || pg_temp.new_line('epazote', '2.000000', 'g'));
select pg_temp.propose('stale', :PASTOR, pg_temp.set_qty(pg_temp.lines_of(:PASTOR), :CARNE, '90.000000'));
select is(pg_temp.tap('pastor', 'pastor', :OWNER),
          jsonb_build_object('code', 'applied', 'pending_change_id', pg_temp.pc('pastor'), 'status', 'applied', 'message', null),
          'the owner applies a recipe change');
create temp table v2 as
select r.* from public.recipe r where r.menu_item_id = :PASTOR and r.recipe_version = 2;
select is((select row(recipe_version, status, effective_from, effective_to, yield_qty, tenant_id)::text from v2),
          format('(2,confirmed,2026-10-12,,1.000000,%s)', :TENANT), 'a confirmed version 2 starts on the approval day');
select is((select row(status, effective_from, effective_to)::text from public.recipe where id = :PASTOR_RECIPE),
          '(confirmed,2026-08-17,)', 'version 1 is kept as it was');
select is(app.recipe_of_record(:PASTOR, null, '2026-10-12'), (select id from v2), 'version 2 is the recipe of record today');
select is(app.recipe_of_record(:PASTOR, null, '2026-10-11'), :PASTOR_RECIPE::uuid, 'and version 1 the day before');
select is(app.pending_base_version('recipe.upsert', :PASTOR, '{}'), 2, 'the recipe version moved to 2');
select is((select count(*) from public.recipe_line where recipe_id = (select id from v2)), 8::bigint, 'it has the 7 lines plus epazote');
select is((select qty_base from public.recipe_line where recipe_id = (select id from v2) and ingredient_id = :CARNE), 80.000000,
          'with the new quantity of meat');
select is((select row(ingredient_id, qty_base, yield_override_pct)::text from public.recipe_line
           where recipe_id = (select id from v2) and sub_recipe_id = :SALSA_RECIPE),
          '(,30.000000,)', 'the salsa verde line stays a sub-recipe line (no ingredient_id)');
select is((select ingredient_id from public.recipe_line where recipe_id = (select id from v2) and qty_base = 2),
          'eeeeeeee-0000-7000-8000-0000000000e1'::uuid, 'the new epazote line reuses the catalog''s Epazote by name');
select is((select count(*) from public.ingredient where tenant_id = :TENANT and lower(name) = 'epazote'), 1::bigint,
          'and no second Epazote is created');
select is((select count(*) from public.recipe_line where recipe_id = :PASTOR_RECIPE), 7::bigint, 'version 1 keeps its 7 lines');

-- the tap recomputes today only; the older days keep the costs of version 1
select cmp_ok((pg_temp.snap('2026-10-12')).cost, '>', (select cost from snap_before where date = '2026-10-12'),
              'today''s pastor cost uses version 2');
select is((select array_agg(row(s.id, s.cost)::text order by s.date) from public.dish_cost_snapshot s
           where s.menu_item_id = :PASTOR and s.location_id = :CENTRO and s.date in ('2026-10-10', '2026-10-11')),
          (select array_agg(row(b.id, b.cost)::text order by b.date) from snap_before b where b.date < '2026-10-12'),
          'past pastor snapshots are not touched');
select is((select count(*) from public.dish_cost_backfill where pending_change_id = pg_temp.pc('pastor')), 0::bigint,
          'a recipe from today leaves nothing to backfill');

-- one apply audit row with the versions, the lines and the ingredients
select is(pg_temp.audits('pastor', 'pending_change.apply'), 1::bigint, 'one apply audit row');
select is((select row(before ->> 'version', before ->> 'recipe_version', before ->> 'recipe_id', jsonb_array_length(before -> 'lines'))::text
           from public.audit_log where pending_change_id = pg_temp.pc('pastor') and action = 'pending_change.apply'),
          format('(1,1,%s,7)', :PASTOR_RECIPE), 'before: the replaced version and its lines');
select is((select row(a ->> 'recipe_id', a ->> 'recipe_version', a ->> 'effective_from', jsonb_array_length(a -> 'lines'),
                      a -> 'created_ingredient_ids', a -> 'reused_ingredient_ids', a -> 'backfill')::text
           from (select pg_temp.audit_after('pastor', 'pending_change.apply') as a) x),
          format('(%s,2,2026-10-12,8,[],"[""eeeeeeee-0000-7000-8000-0000000000e1""]",null)', (select id from v2)),
          'after: the new version, its lines and the reused ingredient');
select ok((pg_temp.audit_after('pastor', 'pending_change.apply') ->> 'snapshots')::int > 0, 'and the snapshots rewritten today');

-- a second tap changes nothing
select is(pg_temp.tap('pastor again', 'pastor', :OWNER) ->> 'code', 'already_applied', 'a second tap is already_applied');
select is(pg_temp.recipes(:PASTOR), 2::bigint, 'no third version');
select is(pg_temp.audits('pastor', 'pending_change.apply'), 1::bigint, 'no second audit row');

-- stale: filed against version 1, the recipe moved to version 2
select is(pg_temp.tap('stale', 'stale', :OWNER) ->> 'code', 'conflict', 'a recipe change filed against an older version is a conflict');
select is(pg_temp.status('stale'), 'conflict', 'its status is conflict');
select is(pg_temp.audits('stale', 'pending_change.conflict'), 1::bigint, 'with an audit row');
select is(pg_temp.recipes(:PASTOR), 2::bigint, 'and no new version');

-- a new ingredient is created with the line's unit -------------------------------------------
select pg_temp.propose('bistec', :BISTEC, pg_temp.lines_of(:BISTEC) || pg_temp.new_line('Chile habanero', '3.000000', 'g')
                                            || pg_temp.new_line('Hoja de aguacate', '1.000000', 'pza'));
select is(pg_temp.tap('bistec', 'bistec', :OWNER) ->> 'code', 'applied', 'a recipe with new ingredients applies');
select is((select array_agg(row(name, base_unit, default_yield_pct, category)::text order by name) from public.ingredient
           where tenant_id = :TENANT and name in ('Chile habanero', 'Hoja de aguacate')),
          array['("Chile habanero",g,100.0000,)', '("Hoja de aguacate",pza,100.0000,)'],
          'each new ingredient is created with the line''s unit as its base unit');
select is((select count(*) from public.recipe_line rl join public.recipe r on r.id = rl.recipe_id
           join public.ingredient i on i.id = rl.ingredient_id
           where r.menu_item_id = :BISTEC and r.recipe_version = 2 and i.name in ('Chile habanero', 'Hoja de aguacate')),
          2::bigint, 'and used by the new version''s lines');
select is((select jsonb_array_length(pg_temp.audit_after('bistec', 'pending_change.apply') -> 'created_ingredient_ids')), 2,
          'the audit row lists the created ingredients');
select is((select count(*) from public.audit_log where pending_change_id = pg_temp.pc('bistec')
           and action = 'pending_change.apply' and entity_id = :BISTEC::uuid), 1::bigint, 'the audit row is on the dish');

-- same name, another unit: failed, nothing written -------------------------------------------
create temp table ingredients_before as select count(*) as n from public.ingredient;
select pg_temp.propose('epazote pza', :SUADERO, pg_temp.lines_of(:SUADERO) || pg_temp.new_line('Hoja santa', '1.000000', 'pza')
                                                  || pg_temp.new_line('EPAZOTE', '1.000000', 'pza'));
select is(pg_temp.tap('epazote pza', 'epazote pza', :OWNER) ->> 'code', 'failed', 'a new ingredient whose name exists in another unit fails');
select is(pg_temp.status('epazote pza'), 'failed', 'its status is failed');
select matches(pg_temp.audit_after('epazote pza', 'pending_change.fail') ->> 'error', 'Epazote.*\mg\M.*pza|pza.*Epazote',
               'the fail audit row names the ingredient and both units');
select is(pg_temp.recipes(:SUADERO), 1::bigint, 'no recipe version is written');
select is((select count(*) from public.ingredient), (select n from ingredients_before), 'and no ingredient (Hoja santa rolled back)');

-- cycles: the dish's own recipe as a sub-recipe ----------------------------------------------
select pg_temp.propose('cycle', :SUADERO, pg_temp.lines_of(:SUADERO) || jsonb_build_object(
  'ingredient_name', 'Tacos de suadero', 'ingredient_external_id', null, 'ingredient_id', null,
  'sub_recipe_id', :SUADERO_RECIPE, 'new_ingredient', false, 'qty_base', '1.000000', 'unit', 'pza', 'yield_override_pct', null));
select is(pg_temp.tap('cycle', 'cycle', :OWNER) ->> 'code', 'failed', 'a recipe that uses itself fails');
select matches(pg_temp.audit_after('cycle', 'pending_change.fail') ->> 'error', 'sub-recipe', 'and says why');
select is(pg_temp.recipes(:SUADERO), 1::bigint, 'nothing is written');

-- the importer's diff and the payload must describe the same recipe --------------------------
select pg_temp.propose('tampered', :SUADERO, pg_temp.lines_of(:SUADERO));
update public.pending_change set diff = jsonb_set(diff, '{after,lines,0,qty_base}', '"999.000000"') where id = pg_temp.pc('tampered');
select is(pg_temp.tap('tampered', 'tampered', :OWNER) ->> 'code', 'failed', 'a diff that differs from the payload fails');
select is(pg_temp.recipes(:SUADERO), 1::bigint, 'nothing is written');

-- an existing ingredient in the wrong unit
select pg_temp.propose('wrong unit', :SUADERO,
                       jsonb_set(pg_temp.lines_of(:SUADERO), '{0,unit}', '"ml"'));
select is(pg_temp.tap('wrong unit', 'wrong unit', :OWNER) ->> 'code', 'failed', 'a line whose unit is not its ingredient''s base unit fails');

-- authorization: recipes are tenant-wide ------------------------------------------------------
select pg_temp.propose('suadero', :SUADERO, pg_temp.set_qty(pg_temp.lines_of(:SUADERO), '02e0d236-956a-5fb2-a6fb-c4d1f4630a53', '100.000000'));
select is(pg_temp.tap('manager', 'suadero', :LUPITA) ->> 'code', 'forbidden_role', 'a manager (imports only, MR-30) is refused');
select is(pg_temp.tap('admin', 'suadero', :ADMIN) ->> 'code', 'forbidden_role', 'a default admin (no recipes, MR-30) is refused');
update public.membership set can_approve = can_approve || '{recipe.upsert}'::text[] where user_id = :LUPITA;
select is(pg_temp.tap('centro manager', 'suadero', :LUPITA) ->> 'code', 'forbidden_role',
          'a Centro-only member with recipe.upsert is refused: recipes are tenant-wide');
select is((select array_agg(after ->> 'reason' order by after ->> 'reason') from public.audit_log
           where pending_change_id = pg_temp.pc('suadero') and action = 'pending_change.deny'),
          array['can_approve', 'can_approve', 'location'], 'the refusals say why: can_approve twice, then the location scope');
select is(pg_temp.audits('suadero', 'pending_change.deny'), 3::bigint, 'every refusal is audit-logged');
select is(pg_temp.status('suadero'), 'pending', 'the change stays pending');
select is(pg_temp.recipes(:SUADERO), 1::bigint, 'and nothing is written');

-- an admin allowed recipes applies a manager-level change; required_role owner still needs the owner
update public.membership set can_approve = can_approve || '{recipe.upsert}'::text[] where user_id = :ADMIN;
select is(pg_temp.tap('admin manager', 'suadero', :ADMIN) ->> 'code', 'applied', 'an admin allowed recipes applies a manager-level change');
select pg_temp.propose('owner only', :SUADERO, pg_temp.set_qty(pg_temp.lines_of(:SUADERO), '02e0d236-956a-5fb2-a6fb-c4d1f4630a53', '95.000000'), 'owner');
select is(pg_temp.tap('admin owner only', 'owner only', :ADMIN) ->> 'code', 'forbidden_role', 'required_role owner refuses an admin');
select is(pg_temp.recipes(:SUADERO), 2::bigint, 'leaving one new suadero version');
select is(pg_temp.tap('owner owner only', 'owner only', :OWNER) ->> 'code', 'applied', 'the owner applies an owner-only change');
select is((select max(recipe_version) from public.recipe where menu_item_id = :SUADERO), 3, 'as version 3');

-- new ingredients match by the importer's normalized name (keys.normalize_name) ------------------
select is(app.normalize_name(' Tacos al  pastor (Orden de 3) '), 'tacos al pastor orden de 3',
          'normalize_name: lower case, no parentheses, single spaces');
select is(app.normalize_name('Chile JALAPEÑO'), 'chile jalapeno', 'normalize_name: no accents, ñ is n');
select is((select count(*) from pg_indexes where tablename = 'ingredient'
           and indexdef like '%app.normalize_name(name)%'), 1::bigint, 'the ingredient lookup has an expression index');
select pg_temp.propose('orégano', :PASTOR, pg_temp.lines_of(:PASTOR) || pg_temp.new_line('Orégano', '5.000000', 'g'));
select pg_temp.propose('oregano', :BISTEC, pg_temp.lines_of(:BISTEC) || pg_temp.new_line(' OREGANO  ()', '4.000000', 'g'));
select is(pg_temp.tap('orégano', 'orégano', :OWNER) ->> 'code', 'applied', 'the first spelling creates the ingredient');
select is(pg_temp.tap('oregano', 'oregano', :OWNER) ->> 'code', 'applied', 'another spelling of the same name applies');
select is((select array_agg(name) from public.ingredient where tenant_id = :TENANT and app.normalize_name(name) = 'oregano'),
          array['Orégano'], 'and reuses it: one ingredient, the first spelling');
select is(pg_temp.audit_after('oregano', 'pending_change.apply') -> 'reused_ingredient_ids',
          (select jsonb_agg(id) from public.ingredient where tenant_id = :TENANT and name = 'Orégano'),
          'the audit row lists it as reused');
select pg_temp.propose('orégano ml', :SUADERO, pg_temp.lines_of(:SUADERO) || pg_temp.new_line('oregano', '1.000000', 'ml'));
select is(pg_temp.tap('orégano ml', 'orégano ml', :OWNER) ->> 'code', 'failed', 'the normalized name in another unit fails');
select matches(pg_temp.audit_after('orégano ml', 'pending_change.fail') ->> 'error', 'Orégano.*\mg\M.*ml',
               'naming the catalog spelling and both units');

-- what the approver saw is what is written: an id must carry its catalog name ----------------
create temp table recipes_before as select count(*) as n from public.recipe;
-- the line names Sal fina but points at Tortilla de maíz
select pg_temp.propose('renamed', :SUADERO,
  (select jsonb_agg(case when x ->> 'ingredient_name' = 'Tortilla de maíz' then jsonb_set(x, '{ingredient_name}', '"Sal fina"') else x end
                    order by n)
   from jsonb_array_elements(pg_temp.lines_of(:SUADERO)) with ordinality as t (x, n)));
select is(pg_temp.tap('renamed', 'renamed', :OWNER) ->> 'code', 'failed', 'a line whose name is not its ingredient''s fails');
select matches(pg_temp.audit_after('renamed', 'pending_change.fail') ->> 'error', 'Sal fina.*Tortilla de maíz',
               'the fail audit row names both');
-- a sub-recipe line named after another ingredient
select pg_temp.propose('renamed sub', :PASTOR,
  (select jsonb_agg(case when x ->> 'sub_recipe_id' is not null then jsonb_set(x, '{ingredient_name}', '"Sal fina"') else x end
                    order by n)
   from jsonb_array_elements(pg_temp.lines_of(:PASTOR)) with ordinality as t (x, n)));
select is(pg_temp.tap('renamed sub', 'renamed sub', :OWNER) ->> 'code', 'failed', 'a sub-recipe line under another name fails');
select matches(pg_temp.audit_after('renamed sub', 'pending_change.fail') ->> 'error', 'Sal fina.*Salsa verde', 'and says why');
-- a sub-recipe line without the ingredient it produces
select pg_temp.propose('sub no ingredient', :PASTOR,
  (select jsonb_agg(case when x ->> 'sub_recipe_id' is not null then jsonb_set(x, '{ingredient_id}', 'null') else x end
                    order by n)
   from jsonb_array_elements(pg_temp.lines_of(:PASTOR)) with ordinality as t (x, n)));
select is(pg_temp.tap('sub no ingredient', 'sub no ingredient', :OWNER) ->> 'code', 'failed',
          'a sub-recipe line without ingredient_id fails');
select matches(pg_temp.audit_after('sub no ingredient', 'pending_change.fail') ->> 'error', 'does not produce', 'and says why');
select is((select count(*) from public.recipe), (select n from recipes_before), 'none of them writes a recipe');

-- quantities that are not finite or round to 0 when stored ------------------------------------
create function pg_temp.with_value(ls jsonb, path text[], value text) returns jsonb language sql immutable as $$
  select jsonb_set(ls, path, to_jsonb(value))
$$;
select pg_temp.propose('qty nan', :SUADERO, pg_temp.with_value(pg_temp.lines_of(:SUADERO), '{0,qty_base}', 'NaN'));
select pg_temp.propose('qty inf', :SUADERO, pg_temp.with_value(pg_temp.lines_of(:SUADERO), '{0,qty_base}', 'Infinity'));
select pg_temp.propose('qty tiny', :SUADERO, pg_temp.with_value(pg_temp.lines_of(:SUADERO), '{0,qty_base}', '0.0000001'));
select pg_temp.propose('pct nan', :SUADERO, pg_temp.with_value(pg_temp.lines_of(:SUADERO), '{0,yield_override_pct}', 'NaN'));
select pg_temp.propose('pct inf', :SUADERO, pg_temp.with_value(pg_temp.lines_of(:SUADERO), '{0,yield_override_pct}', 'Infinity'));
select pg_temp.propose('pct tiny', :SUADERO, pg_temp.with_value(pg_temp.lines_of(:SUADERO), '{0,yield_override_pct}', '0.00001'));
select pg_temp.propose('pct over 100', :SUADERO, pg_temp.with_value(pg_temp.lines_of(:SUADERO), '{0,yield_override_pct}', '120.0000'));
select pg_temp.propose('yield nan', :SUADERO, pg_temp.lines_of(:SUADERO));
select pg_temp.propose('yield inf', :SUADERO, pg_temp.lines_of(:SUADERO));
select pg_temp.propose('yield tiny', :SUADERO, pg_temp.lines_of(:SUADERO));
update public.pending_change p set payload = jsonb_set(payload, '{values,yield_qty}', to_jsonb(v.y)),
                                   diff = jsonb_set(diff, '{after,yield_qty}', to_jsonb(v.y))
from (values ('yield nan', 'NaN'), ('yield inf', 'Infinity'), ('yield tiny', '0.0000001')) as v (name, y)
where p.id = pg_temp.pc(v.name);
select is((select array_agg(pg_temp.tap(n, n, :OWNER) ->> 'code' order by n) from unnest(array[
             'pct inf', 'pct nan', 'pct tiny', 'qty inf', 'qty nan', 'qty tiny', 'yield inf', 'yield nan', 'yield tiny']) as n),
          array_fill('failed'::text, array[9]), 'NaN, Infinity and values that round to 0 when stored fail');
select is((select count(*) from public.audit_log a join pc on pc.id = a.pending_change_id
           where pc.name in ('pct inf', 'pct nan', 'pct tiny', 'qty inf', 'qty nan', 'qty tiny', 'yield inf', 'yield nan', 'yield tiny')
             and a.action = 'pending_change.fail' and a.after ->> 'error' ~ 'positive'), 9::bigint,
          'each with a fail audit row that says the value must be positive');
select is((select count(*) from public.recipe), (select n from recipes_before), 'and none writes a recipe');
select is(pg_temp.tap('pct over 100', 'pct over 100', :OWNER) ->> 'code', 'applied', 'a yield override over 100 % still applies');

select * from finish();
rollback;
