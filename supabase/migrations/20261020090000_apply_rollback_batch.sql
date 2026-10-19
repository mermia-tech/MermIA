-- MR-16: apply_batch and rollback_batch (09 sections 2.6 and 6; MR-10 spec 7.5.7).
--
-- Facts are insert-only and batch-scoped (09 D3): the loader (apps/api ingestion) inserts a
-- batch's rows with the batch in status parsed or needs_review, where no view reads them. These
-- functions only move batch status:
--   apply_batch:    parsed | needs_review -> applied, and rolled_back -> applied ("restore",
--                   an undone Deshacer); the applied batch of the same slice -> superseded,
--                   remembered in supersedes_batch_id.
--   rollback_batch: applied -> rolled_back; the batch it superseded, if still superseded ->
--                   applied again ("Deshacer" restores the earlier numbers).
-- Both are SECURITY DEFINER, executable by service_role only (the backend), and take the acting
-- user: null means the system (a clean upload auto-applies); a user must be an owner or manager of
-- the batch's tenant whose membership covers the batch's location (spec 7.5.7 items 3-4). The
-- tenant comes from the batch row, never from an argument. Each call writes its audit_log row.

-- The acting user may approve or undo this batch: owner or manager of its tenant, with the batch's
-- location in the membership (09 section 5.1: import_batch.approve / rollback = owner, manager).
create function app.check_batch_actor(b public.import_batch, actor_user_id uuid) returns void
language plpgsql stable set search_path = ''
as $$
begin
  if actor_user_id is null then
    return;  -- the system: only the backend can call, and it decides when to auto-apply
  end if;
  if not exists (
    select 1 from public.membership m
    where m.tenant_id = b.tenant_id and m.user_id = actor_user_id
      and m.role in ('owner', 'manager')
      and (m.all_locations or b.location_id is null or b.location_id = any (m.location_ids))
  ) then
    raise exception 'user % may not change batch %', actor_user_id, b.id using errcode = '42501';
  end if;
end
$$;

create function app.apply_batch(batch_id uuid, actor_user_id uuid default null)
returns public.import_batch
language plpgsql security definer set search_path = ''
as $$
declare
  b public.import_batch;
  previous_status app.batch_status;
  current_id uuid;
begin
  select * into b from public.import_batch where id = batch_id for update;
  if not found then
    raise exception 'batch % not found', batch_id using errcode = 'P0002';
  end if;
  if b.status not in ('parsed', 'needs_review', 'rolled_back') then
    raise exception 'batch % is %, only parsed, needs_review or rolled_back batches apply', batch_id, b.status
      using errcode = '55000';
  end if;
  perform app.check_batch_actor(b, actor_user_id);
  previous_status := b.status;

  -- the unique index on applied slices is checked per statement: flip the old batch first
  select ib.id into current_id from public.import_batch ib
  where ib.tenant_id = b.tenant_id and ib.slice_key = b.slice_key and ib.status = 'applied'
  for update;
  if current_id is not null then
    update public.import_batch set status = 'superseded' where id = current_id;
  end if;
  update public.import_batch
  set status = 'applied', supersedes_batch_id = current_id, applied_by = actor_user_id, applied_at = now()
  where id = batch_id
  returning * into b;

  insert into public.audit_log (tenant_id, actor_user_id, actor_kind, action, entity_type, entity_id, before, after, batch_id)
  values (b.tenant_id, actor_user_id, case when actor_user_id is null then 'system' else 'user' end::app.actor_kind,
          'import_batch.apply', 'import_batch', b.id,
          jsonb_build_object('status', previous_status),
          jsonb_build_object('status', b.status, 'supersedes_batch_id', current_id), b.id);
  return b;
end
$$;

create function app.rollback_batch(batch_id uuid, actor_user_id uuid default null)
returns public.import_batch
language plpgsql security definer set search_path = ''
as $$
declare
  b public.import_batch;
  restored_id uuid;
begin
  select * into b from public.import_batch where id = batch_id for update;
  if not found then
    raise exception 'batch % not found', batch_id using errcode = 'P0002';
  end if;
  if b.status <> 'applied' then
    raise exception 'batch % is %, only an applied batch rolls back', batch_id, b.status
      using errcode = '55000';
  end if;
  perform app.check_batch_actor(b, actor_user_id);

  update public.import_batch
  set status = 'rolled_back', rolled_back_by = actor_user_id, rolled_back_at = now()
  where id = batch_id
  returning * into b;
  if b.supersedes_batch_id is not null then
    update public.import_batch set status = 'applied'
    where id = b.supersedes_batch_id and tenant_id = b.tenant_id and status = 'superseded'
    returning id into restored_id;
  end if;

  insert into public.audit_log (tenant_id, actor_user_id, actor_kind, action, entity_type, entity_id, before, after, batch_id)
  values (b.tenant_id, actor_user_id, case when actor_user_id is null then 'system' else 'user' end::app.actor_kind,
          'import_batch.rollback', 'import_batch', b.id,
          jsonb_build_object('status', 'applied'),
          jsonb_build_object('status', b.status, 'restored_batch_id', restored_id), b.id);
  return b;
end
$$;

revoke all on function app.check_batch_actor(public.import_batch, uuid), app.apply_batch(uuid, uuid),
  app.rollback_batch(uuid, uuid) from public, anon, authenticated;
grant execute on function app.apply_batch(uuid, uuid), app.rollback_batch(uuid, uuid) to service_role;
