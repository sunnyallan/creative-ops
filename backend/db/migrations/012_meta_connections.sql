-- v4.0 Phase C: Meta connections + tokens (encrypted at rest)
-- Also adds a couple of columns to social_posts populated by the watcher.

create table if not exists meta_connections (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,

  -- OAuth account
  meta_user_id text not null,               -- Facebook user id whose token we hold
  meta_user_name text,

  -- Encrypted long-lived user access token (Fernet). Never store plaintext.
  encrypted_access_token bytea not null,
  token_scopes text[] not null default '{}',
  token_expires_at timestamptz,             -- Meta long-lived ≈ 60d; refresh loop TBD

  -- Selected ad account + page + IG account (a tenant may connect multiple; we pick a default)
  selected_ad_account_id text,              -- act_1234...
  selected_page_id text,
  selected_page_name text,
  selected_page_access_token bytea,         -- encrypted page token (never expires until user changes password)
  selected_ig_user_id text,
  selected_ig_username text,

  status text not null default 'connected', -- connected | disconnected | error
  last_error text,
  last_verified_at timestamptz,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, meta_user_id)
);
create index if not exists meta_connections_tenant_idx on meta_connections(tenant_id);

alter table meta_connections enable row level security;
alter table meta_connections force row level security;
drop policy if exists meta_connections_isolation on meta_connections;
create policy meta_connections_isolation on meta_connections
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());
grant select, insert, update, delete on meta_connections to app_user;

-- social_posts already exists from migration 011 — add columns the watcher populates
alter table social_posts
  add column if not exists connection_id uuid references meta_connections(id) on delete set null,
  add column if not exists origin text not null default 'watched'; -- 'authored' | 'watched'
