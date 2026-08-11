alter table verity.runs add column if not exists workspace_id text not null default 'default';
alter table verity.runs add column if not exists idempotency_key text not null default '';
create index if not exists runs_workspace_key_idx on verity.runs (workspace_id, idempotency_key);
