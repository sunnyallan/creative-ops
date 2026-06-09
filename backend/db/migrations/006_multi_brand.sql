-- v2.0: Multi-brand per tenant + structured brand setup + references
-- Replaces single brand_kits per tenant with a brands table.

-- ============================================================
-- 1. Move template_config from brand_kits to tenants (tenant-wide)
-- ============================================================

alter table tenants
  add column if not exists template_config jsonb not null default '{
    "logo_position": "top_right",
    "title_bar": "auto",
    "title_position": "bottom",
    "cta_style": "pill",
    "cta_colour": null
  }'::jsonb;

-- ============================================================
-- 2. brands — one tenant, many brands
-- ============================================================

create table if not exists brands (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null,
  -- Identity
  tone text,
  brand_values text,
  -- Visual
  primary_colour text,                  -- hex
  secondary_colour text,                -- hex
  accent_colour text,                   -- hex (optional)
  heading_font text,                    -- storage path or system family
  body_font text,                       -- storage path or system family
  logo_path text,                       -- single logo for now (storage path)
  -- Personas (same shape as old persona_definitions)
  persona_definitions jsonb not null default '[]'::jsonb,
  -- Brand rules
  brand_rules_do text,                  -- "what we can do"
  brand_rules_dont text,                -- "what to avoid"
  brand_feel text,                      -- "minimal, warm, premium" etc
  -- Style description aggregated from references (or user-typed if no images)
  style_description text,
  -- Permission
  asset_permission_accepted_at timestamptz,
  -- Bookkeeping
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists brands_tenant_idx on brands(tenant_id);

alter table brands enable row level security;
alter table brands force row level security;
drop policy if exists brands_isolation on brands;
create policy brands_isolation on brands
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());
grant select, insert, update, delete on brands to app_user;

-- ============================================================
-- 3. brand_references — uploaded reference banners per brand
-- ============================================================

create table if not exists brand_references (
  id uuid primary key default uuid_generate_v4(),
  brand_id uuid not null references brands(id) on delete cascade,
  tenant_id uuid not null references tenants(id) on delete cascade,
  image_path text not null,                     -- storage path
  extracted_style_description text,             -- populated by vision extraction
  extraction_status text not null default 'pending',  -- pending | done | failed
  extraction_error text,
  created_at timestamptz not null default now()
);
create index if not exists brand_references_brand_idx on brand_references(brand_id);
create index if not exists brand_references_tenant_idx on brand_references(tenant_id);

alter table brand_references enable row level security;
alter table brand_references force row level security;
drop policy if exists brand_references_isolation on brand_references;
create policy brand_references_isolation on brand_references
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());
grant select, insert, update, delete on brand_references to app_user;

-- ============================================================
-- 4. campaigns — add brand_id + product_image_path
-- ============================================================

alter table campaigns
  add column if not exists brand_id uuid references brands(id) on delete set null,
  add column if not exists product_image_path text;
create index if not exists campaigns_brand_idx on campaigns(brand_id);

-- ============================================================
-- 5. creatives — add brand_id (denormalised for query speed)
-- ============================================================

alter table creatives
  add column if not exists brand_id uuid references brands(id) on delete set null;
create index if not exists creatives_brand_idx on creatives(brand_id);

-- ============================================================
-- Note: brand_kits is NOT dropped here — Commit C handles it after
-- the rest of the code stops referencing it.
-- ============================================================
