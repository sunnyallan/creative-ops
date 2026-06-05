-- v1.1: template editor, custom channels, persona library, copy length constraints

-- 1. Template config + custom channels on brand kit
alter table brand_kits
  add column if not exists template_config jsonb not null default '{
    "logo_position": "top_right",
    "title_bar": "auto",
    "title_position": "bottom",
    "cta_style": "pill"
  }'::jsonb;

-- 2. Per-tenant custom channels (overrides built-in defaults if present)
create table if not exists channels (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  key text not null,                 -- e.g. "linkedin_feed"
  display_name text not null,        -- e.g. "LinkedIn Feed"
  width int not null,
  height int not null,
  channel_kind text not null default 'image',  -- image | story | email
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  unique (tenant_id, key)
);
create index if not exists channels_tenant_idx on channels(tenant_id);
alter table channels enable row level security;
alter table channels force row level security;
drop policy if exists channels_isolation on channels;
create policy channels_isolation on channels
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());

-- 3. Predefined persona library (global, read-only to all tenants)
create table if not exists personas_library (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  age_range text,
  income_tier text,
  lifestyle text,
  preferred_imagery text,
  tags text[] not null default '{}'
);
-- Library is global — no RLS, all tenants can read.
grant select on personas_library to app_user;

-- Seed library (idempotent)
insert into personas_library (name, age_range, income_tier, lifestyle, preferred_imagery, tags)
values
  ('Urban Millennials', '28-38', 'middle-high', 'city dwellers, foodies, weekend brunchers, travel-curious', 'modern cafés, candid moments, warm light', '{food,travel,lifestyle}'),
  ('Gen Z Students', '18-24', 'low-middle', 'social-first, value-led, trend-aware, eco-conscious', 'bold colours, dynamic poses, peer groups', '{value,trend,social}'),
  ('Young Professionals', '25-35', 'middle', 'career-focused, productivity-driven, fitness aware', 'clean workspaces, athleisure, transit shots', '{career,fitness}'),
  ('New Parents', '28-40', 'middle-high', 'family-first, time-poor, convenience-seeking', 'soft tones, family scenes, home interiors', '{family,home}'),
  ('Empty Nesters Premium', '50-65', 'high', 'leisure travel, fine dining, premium brands', 'aspirational lifestyle, golden hour, hospitality', '{premium,travel}'),
  ('Suburban Families', '32-45', 'middle', 'weekend-oriented, kid-focused, value bundles', 'outdoor scenes, group settings, bright colours', '{family,value}'),
  ('Tech Enthusiasts', '22-40', 'middle-high', 'early adopters, gadget-led, online-first', 'sleek product shots, dark mode UI, futuristic', '{tech,trend}'),
  ('Fitness Buffs', '20-40', 'middle-high', 'gym regulars, supplements, athleisure, tracking', 'high-energy, action shots, gym/outdoor', '{fitness,wellness}'),
  ('Wellness Seekers', '28-50', 'middle-high', 'mindfulness, organic, holistic health', 'natural light, soft palettes, plants, calm', '{wellness,premium}'),
  ('Small Business Owners', '30-55', 'middle-high', 'time-poor, ROI-focused, B2B-savvy', 'workplace authenticity, hands-on, real customers', '{b2b,career}'),
  ('Foodies & Diners', '25-45', 'middle-high', 'social media driven, restaurant explorers', 'plated dishes, warm interiors, chef close-ups', '{food,lifestyle}'),
  ('Eco-Conscious Buyers', '24-45', 'middle-high', 'sustainability-led, willing to pay premium for ethics', 'natural materials, earthy tones, transparency', '{eco,premium}')
on conflict do nothing;

-- 4. Copy length constraints on campaign
alter table campaigns
  add column if not exists copy_constraints jsonb not null default '{
    "headline_max_chars": 60,
    "body_max_chars": 120,
    "cta_max_chars": 25
  }'::jsonb;
