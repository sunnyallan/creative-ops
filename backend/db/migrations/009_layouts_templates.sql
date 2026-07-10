-- v3.0: Layout styles + custom templates (Penpot-backed)

-- ============================================================
-- 1. Campaigns + creatives carry the chosen layout / template
-- ============================================================

alter table campaigns
  add column if not exists layout_style text not null default 'auto',
  add column if not exists template_id uuid;

alter table creatives
  add column if not exists layout_style text,
  add column if not exists template_id uuid;

-- ============================================================
-- 2. Custom templates — designed in Penpot, synced as SVG
-- ============================================================

create table if not exists templates (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null,
  -- Penpot source coordinates
  penpot_file_id text,
  penpot_page_id text,
  penpot_frame_id text,
  -- Synced artefacts
  svg_source text,                              -- exported SVG with #placeholder layers
  zones jsonb,                                  -- parsed placeholder map {headline: {...}, image: {...}}
  preview_path text,                            -- rendered dummy-content preview in Storage
  sync_status text not null default 'pending',  -- pending | synced | failed
  sync_error text,
  last_synced_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists templates_tenant_idx on templates(tenant_id);

alter table templates enable row level security;
alter table templates force row level security;
drop policy if exists templates_isolation on templates;
create policy templates_isolation on templates
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());
grant select, insert, update, delete on templates to app_user;

-- campaigns.template_id FK added after templates exists
do $$
begin
  if not exists (
    select 1 from information_schema.table_constraints
    where constraint_name = 'campaigns_template_id_fkey'
  ) then
    alter table campaigns
      add constraint campaigns_template_id_fkey
      foreign key (template_id) references templates(id) on delete set null;
  end if;
end$$;
