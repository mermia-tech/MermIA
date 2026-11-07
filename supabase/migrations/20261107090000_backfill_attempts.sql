-- MR-87: the crash-recovery sweep (mermia_api.confirm.backfill.resume_unfinished_backfills) gives
-- up on a backfill that keeps failing. `attempts` counts the sweep runs that raised a database
-- error for the record, `last_error` holds the last one as SQLSTATE and exception class (never
-- the message, which can carry payload values). The sweep picks rows by (attempts, created_at)
-- and skips those at MAX_BACKFILL_ATTEMPTS, so one poisoned row cannot starve newer ones.
-- No unit columns to tag. last_error carries the same not-blank check every text column has.
alter table public.dish_cost_backfill
  add column attempts int not null default 0 check (attempts >= 0),
  add column last_error text,
  add constraint last_error_not_blank check (last_error is null or last_error ~ '[^\t\n\v\f\r \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]');

drop index public.dish_cost_backfill_unfinished_idx;
create index dish_cost_backfill_unfinished_idx on public.dish_cost_backfill (attempts, created_at) where done_at is null;
