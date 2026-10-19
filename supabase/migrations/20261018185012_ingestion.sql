-- MR-10 ingestion (09 sections 2.2 and 2.6; spec 5.7).

create table public.raw_file (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  storage_path text not null,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  mime text,
  filename text,
  size bigint check (size >= 0),
  received_via text,
  sender_user_id uuid references public.app_user (id) on delete restrict,
  received_at timestamptz not null default now(),
  retention_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  unique (tenant_id, sha256)
);
create index raw_file_sender_idx on public.raw_file (sender_user_id);
select app.tag('public.raw_file', 'unit=bytes', array['size']);
select app.tag('public.raw_file', 'values not yet specified', array['received_via']);
select app.finish_table('public.raw_file', 'backend');

-- location_id is added to 09 section 2.2: slice_key includes a location and the location filter
-- needs a column (spec 5.6).
create table public.import_batch (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  source_id uuid not null,
  raw_file_id uuid,
  location_id uuid,
  parser text not null check (parser ~ '^[a-z0-9_.]+@v[0-9]+$'),
  slice_key text not null,
  status app.batch_status not null default 'received',
  stats jsonb not null default '{}',
  supersedes_batch_id uuid,
  quality app.batch_quality not null default 'file',
  applied_by uuid references public.app_user (id) on delete restrict,
  applied_at timestamptz,
  rolled_back_by uuid references public.app_user (id) on delete restrict,
  rolled_back_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, source_id) references public.source (tenant_id, id) on delete restrict,
  foreign key (tenant_id, raw_file_id) references public.raw_file (tenant_id, id) on delete restrict,
  foreign key (tenant_id, location_id) references public.location (tenant_id, id) on delete restrict,
  foreign key (tenant_id, supersedes_batch_id) references public.import_batch (tenant_id, id) on delete restrict
);
create index import_batch_source_idx on public.import_batch (tenant_id, source_id);
create index import_batch_raw_file_idx on public.import_batch (tenant_id, raw_file_id);
create index import_batch_location_idx on public.import_batch (tenant_id, location_id);
create index import_batch_supersedes_idx on public.import_batch (tenant_id, supersedes_batch_id);
-- One current batch per slice (09 section 2.6). Unique indexes are checked per statement, so the
-- apply functions must flip the old batch before applying the new one.
create unique index import_batch_one_applied_per_slice
  on public.import_batch (tenant_id, slice_key) where status = 'applied';
select app.finish_table('public.import_batch', 'location', 'location_id');

create table public.import_issue (
  id uuid primary key default app.uuid_v7(),
  tenant_id uuid not null references public.tenant (id) on delete restrict,
  batch_id uuid not null,
  severity app.issue_severity not null,
  code text not null check (code ~ '^[a-z0-9_.]+$'),
  message_es text not null,
  row_ref text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version int not null default 1,
  unique (tenant_id, id),
  foreign key (tenant_id, batch_id) references public.import_batch (tenant_id, id) on delete restrict
);
create index import_issue_batch_idx on public.import_issue (tenant_id, batch_id);
-- No location of its own: visibility follows the batch (class LP, V19).
select app.finish_table('public.import_issue', 'parent', null, 'public.import_batch', 'batch_id');
