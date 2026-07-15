-- v4.0 Phase A: Learning store — persistent memory of what works
-- Requires pgvector (already installed via migration 001).

-- ============================================================
-- experiments — the goal+budget autonomous loop instances
-- ============================================================
create table if not exists experiments (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  brand_id uuid references brands(id) on delete set null,

  goal text not null,                       -- freeform: "grow IG followers for launch"
  goal_metric text not null,                -- ctr | reach | conversions | engagement | followers | clicks
  goal_target numeric,                      -- e.g. 5000 followers; NULL = "as much as possible in budget"

  budget_total numeric not null,            -- media spend cap (INR/USD, tenant-consistent)
  budget_spent numeric not null default 0,  -- ledger sum
  budget_committed numeric not null default 0, -- planned but not yet spent
  per_iteration_cap numeric,                -- hybrid guardrail; NULL = full auto

  channels text[] not null default '{mock_ads}',   -- mock_ads | meta_ads | instagram_organic | facebook_organic

  status text not null default 'draft',
    -- draft | running | paused | awaiting_approval | goal_met | budget_exhausted | stopped | failed

  report jsonb,
  report_path text,

  metric_window_hours int not null default 48,   -- how long to measure each iteration
  min_spend_for_verdict numeric not null default 100,
  max_iterations int not null default 20,        -- safety net

  langgraph_thread_id text,                 -- for PostgresSaver checkpointing

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists experiments_tenant_status_idx on experiments(tenant_id, status);
create index if not exists experiments_brand_idx on experiments(brand_id);

alter table experiments enable row level security;
alter table experiments force row level security;
drop policy if exists experiments_isolation on experiments;
create policy experiments_isolation on experiments
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());
grant select, insert, update, delete on experiments to app_user;

-- ============================================================
-- experiment_iterations — one row per plan→publish→measure→analyze cycle
-- ============================================================
create table if not exists experiment_iterations (
  id uuid primary key default uuid_generate_v4(),
  experiment_id uuid not null references experiments(id) on delete cascade,
  tenant_id uuid not null references tenants(id) on delete cascade,

  index int not null,                       -- 1-based, dense per experiment
  hypothesis text,                          -- Gemini's rationale for THIS iteration
  applied_learnings jsonb,                  -- [{learning_id, statement, confidence}] used to shape the brief

  brief jsonb,                              -- final brief passed to generation
  campaign_id uuid references campaigns(id) on delete set null,
  format text,                              -- static | carousel | video
  channel text not null,
  persona text,

  spend_planned numeric not null default 0,
  spend_actual numeric not null default 0,

  publish_ref jsonb,                        -- {ad_id, adset_id, post_id, permalink…}
  status text not null default 'planning',
    -- planning | generating | awaiting_approval | publishing | published |
    -- measuring | analyzed | skipped | failed

  metrics jsonb,                            -- final snapshot: impressions, ctr, cpc, conversions, engagement, saves…
  metrics_history jsonb,                    -- [{polled_at, metrics}]
  verdict jsonb,                            -- {beat_hypothesis:bool, magnitude:num, dimensions:[…], summary:text}

  measure_deadline timestamptz,             -- published_at + experiment.metric_window_hours
  published_at timestamptz,
  measured_at timestamptz,
  error text,

  created_at timestamptz not null default now(),
  unique (experiment_id, index)
);
create index if not exists iter_experiment_idx on experiment_iterations(experiment_id);
create index if not exists iter_status_idx on experiment_iterations(status);
create index if not exists iter_measure_due_idx on experiment_iterations(measure_deadline)
  where status = 'measuring';

alter table experiment_iterations enable row level security;
alter table experiment_iterations force row level security;
drop policy if exists iter_isolation on experiment_iterations;
create policy iter_isolation on experiment_iterations
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());
grant select, insert, update, delete on experiment_iterations to app_user;

-- ============================================================
-- learnings — distilled, embedding-indexed knowledge that compounds
-- ============================================================
create table if not exists learnings (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  brand_id uuid references brands(id) on delete cascade,   -- NULL = cross-brand (rare)

  dimension text not null,
    -- visual_style | copy_angle | format | persona | channel | timing | tags | audience | cta

  statement text not null,                  -- "Pastel iPhone-mockup visuals outperform photographic ~2.1x CTR for Young Professionals"
  confidence numeric not null default 0.5,  -- 0..1; grows w/ corroboration, decays w/ contradiction
  evidence jsonb not null default '[]'::jsonb,  -- [{iteration_id, metric, delta, direction:'up'|'down'}]

  embedding vector(768),                    -- gemini-embedding-001

  times_applied int not null default 0,
  last_validated_at timestamptz,
  superseded_by uuid references learnings(id) on delete set null,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists learnings_brand_dim_idx on learnings(brand_id, dimension);
create index if not exists learnings_tenant_idx on learnings(tenant_id);
-- ivfflat needs a populated table; use HNSW which handles empty gracefully.
create index if not exists learnings_embedding_idx on learnings
  using hnsw (embedding vector_cosine_ops);

alter table learnings enable row level security;
alter table learnings force row level security;
drop policy if exists learnings_isolation on learnings;
create policy learnings_isolation on learnings
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());
grant select, insert, update, delete on learnings to app_user;

-- ============================================================
-- social_posts — organic watcher raw data (feeds learnings via distill)
-- ============================================================
create table if not exists social_posts (
  id uuid primary key default uuid_generate_v4(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  brand_id uuid references brands(id) on delete cascade,

  platform text not null,                   -- instagram | facebook | twitter…
  post_ref text not null,                   -- platform's post id
  permalink text,
  posted_at timestamptz,

  post_type text,                           -- feed | carousel | reel | story
  caption text,
  tags text[],
  creative_id uuid references creatives(id) on delete set null,  -- when we authored it

  metrics jsonb,                            -- most recent poll
  metrics_history jsonb not null default '[]'::jsonb,
  last_polled_at timestamptz,

  created_at timestamptz not null default now(),
  unique (tenant_id, platform, post_ref)
);
create index if not exists social_posts_brand_idx on social_posts(brand_id);
create index if not exists social_posts_platform_idx on social_posts(platform, posted_at desc);

alter table social_posts enable row level security;
alter table social_posts force row level security;
drop policy if exists social_posts_isolation on social_posts;
create policy social_posts_isolation on social_posts
  using (tenant_id = app_current_tenant())
  with check (tenant_id = app_current_tenant());
grant select, insert, update, delete on social_posts to app_user;
