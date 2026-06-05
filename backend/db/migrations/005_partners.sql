-- v1.8: reusable partner directory per tenant

create table if not exists partners (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null,
  logo_path text,
  primary_colour text,
  products_or_services text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, name)
);
create index if not exists partners_tenant_idx on partners(tenant_id);

alter table partners enable row level security;
alter table partners force row level security;

drop policy if exists partners_isolation on partners;
create policy partners_isolation on partners
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());

grant select, insert, update, delete on partners to app_user;
