-- Creative Ops MVP schema
-- Multi-tenant via tenant_id column + RLS using app.current_tenant_id GUC

create extension if not exists "uuid-ossp";
create extension if not exists vector;

-- App role that the API connects as (non-owner so FORCE RLS applies).
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_user') then
    create role app_user nologin;
  end if;
end$$;

-- =========================================================
-- Tables
-- =========================================================

create table if not exists tenants (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  owner_user_id uuid not null,
  created_at timestamptz not null default now()
);

create table if not exists brand_kits (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  brand_name text not null,
  tone text,
  values text,
  colours jsonb not null default '[]'::jsonb,
  fonts jsonb not null default '[]'::jsonb,
  logo_paths jsonb not null default '[]'::jsonb,
  persona_definitions jsonb not null default '[]'::jsonb,
  asset_permission_accepted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists brand_kits_tenant_idx on brand_kits(tenant_id);

create table if not exists campaigns (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  goal text not null,
  persona_segment text,
  brief jsonb,
  status text not null default 'briefing',
  created_at timestamptz not null default now()
);
create index if not exists campaigns_tenant_idx on campaigns(tenant_id);

create table if not exists creatives (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  campaign_id uuid not null references campaigns(id) on delete cascade,
  channel text not null,
  dimensions text not null,
  copy_headline text,
  copy_body text,
  copy_cta text,
  storage_path text,
  embedding vector(512),
  governance_status text not null default 'pending',
  governance_issues jsonb,
  human_status text not null default 'pending',
  human_rejection_reason text,
  human_rejection_tag text,
  created_at timestamptz not null default now()
);
create index if not exists creatives_tenant_idx on creatives(tenant_id);
create index if not exists creatives_campaign_idx on creatives(campaign_id);
create index if not exists creatives_status_idx on creatives(governance_status, human_status);

create table if not exists deployments (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  creative_id uuid not null references creatives(id) on delete cascade,
  channel text not null,
  status text not null default 'stubbed',
  payload jsonb,
  external_id text,
  error text,
  created_at timestamptz not null default now()
);
create index if not exists deployments_tenant_idx on deployments(tenant_id);

create table if not exists audit_log (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  user_id uuid,
  action text not null,
  entity text not null,
  entity_id uuid,
  meta jsonb,
  created_at timestamptz not null default now()
);
create index if not exists audit_log_tenant_idx on audit_log(tenant_id, created_at desc);

-- =========================================================
-- RLS
-- =========================================================

alter table tenants enable row level security;
alter table tenants force row level security;
alter table brand_kits enable row level security;
alter table brand_kits force row level security;
alter table campaigns enable row level security;
alter table campaigns force row level security;
alter table creatives enable row level security;
alter table creatives force row level security;
alter table deployments enable row level security;
alter table deployments force row level security;
alter table audit_log enable row level security;
alter table audit_log force row level security;

-- Helper: read current tenant from GUC; null => block.
create or replace function app_current_tenant() returns uuid
language sql stable as $$
  select nullif(current_setting('app.current_tenant_id', true), '')::uuid
$$;

-- tenants: a row is visible if its id matches the GUC.
drop policy if exists tenants_isolation on tenants;
create policy tenants_isolation on tenants
  using (id = app_current_tenant())
  with check (id = app_current_tenant());

-- generic policy factory pattern (inline per table):
drop policy if exists brand_kits_isolation on brand_kits;
create policy brand_kits_isolation on brand_kits
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());

drop policy if exists campaigns_isolation on campaigns;
create policy campaigns_isolation on campaigns
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());

drop policy if exists creatives_isolation on creatives;
create policy creatives_isolation on creatives
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());

drop policy if exists deployments_isolation on deployments;
create policy deployments_isolation on deployments
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());

drop policy if exists audit_log_isolation on audit_log;
create policy audit_log_isolation on audit_log
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());

-- Grant app role minimal CRUD; RLS enforces tenant isolation.
grant usage on schema public to app_user;
grant select, insert, update, delete on
  tenants, brand_kits, campaigns, creatives, deployments, audit_log
to app_user;
