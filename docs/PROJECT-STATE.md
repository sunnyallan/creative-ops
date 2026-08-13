# PROJECT-STATE — Creative Ops platform

> **Purpose of this file:** durable knowledge base. This document is the single source of
> truth for what exists in this codebase, how it fits together, what shipped, what didn't,
> and every trap we hit along the way. Any engineer or AI session picking this up cold
> should be able to work productively from this doc alone.
>
> **Current state (2026-08-13):** codebase is complete through v4.0 with all fixes and
> perf improvements shipped. All external services (Railway, hosted Supabase project,
> Vercel) have been torn down to zero cost. Code lives on GitHub. See
> **[REVIVAL-RUNBOOK.md](REVIVAL-RUNBOOK.md)** for the step-by-step to bring it back.

---

## 1. What this product is

Creative Ops is a multi-tenant AI creative-operations SaaS. A brand manager configures a
brand once (colours, personas, reference banners, rules), then either:

- **Manually** generates on-brand creatives (banners, social posts, carousels, videos) from
  a one-line goal — AI writes the brief and copy, generates imagery, composites text/logos,
  runs brand-safety governance, and queues results for human review, editing, and stubbed
  platform deployment.
- **Autonomously** runs a goal + budget "growth engine" — the orchestrator loops
  plan → research → brief → generate → publish → measure → analyse → learn → decide until
  the goal is met or budget is spent, then delivers a report of what worked and what to
  try next.

A persistent, brand-scoped **learning store** with pgvector-indexed embeddings makes the
system genuinely smarter over time — every iteration's verdict distils into learnings
that get injected as prompt priors on all future briefs.

### Product surfaces
- **Sidebar app shell** with dark/light mode toggle (dark-first for ops surfaces)
- **/dashboard** — KPI cards, active experiments, recent learnings, review queue
- **/experiments** — list + create form
- **/experiments/[id]** — mission control with iteration timeline, budget gauge, approval
  banner, kill switch, live polling
- **/learnings** — searchable/filterable library with evidence drill-down
- **/review** — creatives queue (paginated) with inline video playback + canvas editor
- **/creatives/[id]/edit** — text-only in-app editor (drag to move, double-click to edit)
- **/campaigns/new** — content-type tabs (banner/post/carousel), 20-layout picker or
  custom Penpot templates, brand-scoped personas
- **/brands** wizard (6-step) + references gallery
- **/settings/connections** — Meta OAuth flow with per-brand binding

---

## 2. Deployment status (as of teardown — 2026-08-13)

**Everything external is torn down. Code lives on GitHub.**

| Surface | Status |
|---|---|
| GitHub | ✅ `sunnyallan/creative-ops` — all commits, all docs, all migrations |
| Railway (API + worker + beat + Redis + Postgres + Penpot stack) | 🛑 Deleted |
| Supabase project `iqmajludgkcvzgqegxds` | 🛑 Data deleted (or project deleted, per user choice) |
| Vercel frontend `creative-ops-xi.vercel.app` | Optional — may still exist on free tier |
| Meta Developer App (App ID `2289944078434402`) | ✅ Still registered on developers.facebook.com — reusable on next deploy |
| Meta Business Manager + FB Page "Project Briyt" + ad account `act_324096390` | ✅ Still on Meta side — reusable |

**Compromised credentials to rotate before next deploy:**
See `docs/PROJECT-STATE.md` history — the following were pasted in chat during this
session and must be regenerated before redeployment:
- `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL` (password `dk5QymePF6X0F7f7`)
- `GEMINI_API_KEY` starting `AQ.Ab8RN6IpZ...`
- `SIGHTENGINE_API_SECRET` starting `T6c2icRD...`
- `META_APP_SECRET` `c943745225f426034e631feb0517b53c`
- `TOKEN_ENCRYPTION_KEY` `qLE4NOMk_zaSxRL7hUv4qniBJiRi_cQ-I9fuzhDY6XU=`

---

## 3. Backend architecture (`/backend`)

Stack: FastAPI + Celery + LangGraph. Python 3.12, `python:3.12-slim` base
(Debian Trixie — `libgdk-pixbuf-2.0-0` is the hyphenated package name).
Fonts (Geist + DejaVu), rembg u2net model (~170 MB), and ffmpeg all baked into the image
at build time.

### Entry + platform
- **`main.py`** — FastAPI app, CORS `*`, wires every router
- **`auth.py`** — verifies Supabase bearer tokens via `{SUPABASE_URL}/auth/v1/user`
  (60s in-proc cache). Do NOT decode JWTs locally — Supabase uses asymmetric keys.
  `_ensure_tenant` auto-creates one tenant per auth user. `_allowed_email()` gates
  access to only `ALLOWED_EMAILS` (comma-separated env). 403 (not 401) for
  non-allowlisted users so frontend can distinguish "no session" from "wrong account."
- **`db/session.py`** — psycopg3 pool; `tenant_connection(tenant_id)` sets
  `app.current_tenant_id` GUC per txn (RLS enforcement point).
- **`db/sql_runner.py`** — the Alembic helper that reads raw `.sql` files from
  `db/migrations/` and executes them statement-by-statement inside the Alembic
  transaction. **Must NOT live under `backend/alembic/`** — Python's `alembic` package
  name shadows a local folder of the same name and breaks the imports. See
  `backend/alembic/versions/*.py`; each imports `from db.sql_runner import run_sql_file`.
- **`config.py`** — pydantic-settings; env inventory in §7.
- **`storage.py`** — Supabase Storage (service role). Memoised client via `lru_cache`
  (perf — was 100× slower). `signed_urls_batch(paths)` for the batched signing API used
  by list endpoints.
- **`observability.py`** — `traced_generate()`: Langfuse-wrapped Gemini calls.
- **`token_crypto.py`** — Fernet symmetric encryption for stored OAuth tokens.
  `TOKEN_ENCRYPTION_KEY` env must be identical across API + worker + beat services;
  tokens encrypted on one can't be decrypted on another otherwise.
- **`meta_client.py`** — thin httpx-based Meta Graph API client (deliberately not the
  1.8 GB facebook-business SDK). Handles OAuth exchange, long-lived swap,
  ad/page/IG listing, campaign+adset+creative+ad create, insights ingestion, IG media
  publishing, page-post enumeration. Handles Facebook Login for Business `config_id`
  mode via `META_LOGIN_CONFIG_ID`.
- **`penpot_client.py`** — RPC `get-file` + `/api/export`. Parked with Penpot.
- **`layouts.py`** — 20-layout registry: `asset_plan` (`none | full | subject_cutout | multi:N`),
  `image_prompt_fragment`, `compositor_mode`, `mode_params`. Helpers:
  `get_layout`, `asset_plan_of`, `registry_for_prompt`, `registry_for_api`.
- **`learning_store.py`** (Phase A) — distill/retrieve. Embeddings via
  `gemini-embedding-001` (768-d). Deduped by cosine similarity ≥0.86; near-duplicates
  get corroborated/contradicted with confidence updates. `learnings_prompt_block()` is
  the shared PROVEN LEARNINGS injection format.

### Agents
- **`agents/briefing_agent.py`** — LangGraph `StateGraph` with PostgresSaver on Supabase.
  Nodes: `read_brand_kit → analyse_persona → pick_layout → retrieve_learnings →
  generate_brief → persist_brief`. Retry+pad on undercount (Gemini undergen defence).
  Layout auto-pick uses `gemini-2.5-flash-lite`. `retrieve_learnings` uses Phase A store
  and injects the PROVEN LEARNINGS block at the top of the brief prompt.
- **`agents/orchestrator.py`** (Phase B) — imperative-over-LangGraph durable loop.
  `run_next_step()` is idempotent per node; safe to re-invoke on retries.
  Nodes: `plan_iteration → spend_gate → generate → publish → measuring (parks) →
  analyze → distill → decide → report`.
  Budget ledger with `spent + committed <= total` invariant enforced via FOR UPDATE
  row lock in `commit_planned_spend()`. Auto-tick chain: governance and creative worker
  kick `orchestrator_tick.delay()` immediately on completion — no waiting for the 15-min
  beat cadence.

### Workers (Celery; all registered in `workers/celery_app.py`)
- **`creative.py`** — task `creative.generate(tenant_id, campaign_id, brief_index)`:
  1. Load campaign + brand
  2. Carousel anchored coherence (slide 0 first; slides 1+ receive slide-0 PNG as
     conditioning; requeue w/ countdown=10 if anchor missing)
  3. **Asset planner** by layout/template: `none` (~$0.01 typography creatives),
     `full` (Nano Banana Pro), `subject_cutout` (white-bg prompt + rembg → RGBA),
     `multi:N` (first anchors the rest); template image slots override
  4. `_gen_image` prompt stack (order matters): BRAND STYLE ABSOLUTE LAW block →
     product-image conditioning → layout fragment → cutout mode → persona&scene →
     subject (partner products lock) → composition (aspect-aware) → hard bans
  5. Render via `render_layout()` or `render_template()` → WebP q82
  6. **v3.1:** second render with blank copy → `*_bg.webp` → `edit_background_path`
     (in-app editor base)
  7. **v4.0 perf:** skip governance for `campaigns.skip_governance=true` (orchestrator
     sets this on mock/sandbox iterations) — saves 15–25s per iteration
  8. Insert creative row → kick `governance.run` OR (if skipped) mark passed + kick
     orchestrator tick directly
  - `IMAGE_MODEL_ID` env swaps Nano Banana Pro for a faster/cheaper Gemini image model
    (~10-15s vs 30-60s per image)
  - Internal brief keys are `_`-prefixed (bytes etc.) and must be stripped before
    `json.dumps` (`default=str` everywhere — recurring bug class)
- **`video.py`** (Phase D) — task `video.generate`: Veo generation (`VEO_MODEL_ID` env,
  default `veo-3.0-generate-001`) → ffmpeg mux with end-card (typo-layout WebP →
  normalised to matching x264/yuv420p/30fps/AAC-stereo) → thumbnail (first frame) +
  3 sampled frames (start/mid/near-end). Sampled frames run through the existing
  Sightengine pipeline; worst frame wins.
- **`compositor.py`** — Pillow. `composite()` = legacy overlay mode (aspect-aware,
  variance-guarded safe zone, WCAG auto text colour, CTA pill bbox-true centring +
  reverse-fill, dual logo plates, SVG logos via cairosvg). `render_layout()` dispatches
  to modes: typo, quote, stat, split_h/v, cutout (polaroid/minimal), meme, grid,
  collage, before_after, editorial, duotone. All WebP q82.
- **`governance.py`** → `governance/pipeline.py` — Sightengine
  (nudity-2.1/gore/weapon/offensive/text; >0.5 blocks) then Gemini judge (knows body
  copy is NOT on image; judge severity 'block' is downgraded to 'warn' — **only
  Sightengine can hard-block**). Auto-kicks `orchestrator_tick.delay()` on completion
  if the creative belongs to a status='generating' iteration.
- **`research.py`** — `research.gather`: Gemini + Google search grounding → 250-400
  word notes on `campaigns.research_notes`.
- **`style_extractor.py`** — `brand.extract_reference_style`: vision-describe each
  reference banner → aggregate into `brands.style_description`.
- **`template_sync.py`** / **`template_renderer.py`** — Penpot board → SVG sync;
  placeholder fill + cairosvg rasterize. Blocked only by Penpot hosting failure.
- **`orchestrator_tick.py`** — task `orchestrator.tick`, scheduled every 15 min via
  Celery beat. Sweeps every `running` experiment and calls `run_next_step()`. Also
  invoked ad-hoc from creative/governance completion hooks and API endpoints.
- **`social_watcher.py`** (Phase C) — task `social.watch`, scheduled hourly. Sweeps
  every connected Meta account, pulls last 25 IG media + FB posts, upserts into
  `social_posts`, polls insights for posts within 30-day recency window.

### Integrations (`integrations/`)
Publisher Protocol: `publish(tenant_id, iteration_id, creative_id, storage_path, copy,
format, persona, spend_planned, brand_id=None) → publish_ref`;
`poll_metrics(publish_ref, ...) → metrics_dict`; `cancel(publish_ref) → None`.
`get_adapter(channel)` in `mock_ads` lazy-imports the real adapters on demand.

- **`mock_ads.py`** — deterministic-noise simulator. Format bias (video > carousel >
  static), persona interactions, hypothesis-quality boost. Metrics grow on S-curve
  over `elapsed_hours`. Zero external calls.
- **`meta_ads.py`** — real Meta Marketing API adapter. Both legacy `.deploy()` and
  orchestrator `.publish()/.poll_metrics()/.cancel()`. Persona → targeting map,
  goal metric → optimization goal. Ads paused-by-default in sandbox
  (`META_USE_SANDBOX=true`). **WebP → JPEG transcode** on upload (Meta rejects WebP
  with subcode 1487411 "Ad image must be JPEG or PNG"). `_step()` wraps every Meta call
  to raise labelled errors (e.g. `meta_ads create_campaign failed: (subcode=…)`) so
  failures are diagnosable without reading Railway logs. Per-brand connection routing
  via `_load_connection(tenant_id, brand_id)`.
- **`instagram_organic.py`** — real IG Content Publishing API. Feed images work; Reels
  video path scaffolded via `media_type=REELS`. Cancel is a documented no-op (organic
  posts can't be un-published programmatically).

### Alembic (auto-apply migrations, `alembic/` + `entrypoint-api.sh`)
- On API boot, `entrypoint-api.sh` runs `alembic upgrade head` before Uvicorn starts.
  If migrations fail, API refuses to start (fail-fast).
- Only the **API service** runs migrations. Worker + beat use plain Celery commands
  set in the deploy platform UI (to avoid racing on `alembic_version`).
- Each migration is a wrapper Python file under `alembic/versions/mNNN_*.py` that calls
  `run_sql_file("NNN_*.sql")` from `db/sql_runner.py`.
- **NEVER put the sql_runner helper under a folder named `alembic/`** — Python's
  installed `alembic` package name shadows a local folder of the same name; migration
  imports fail with `ModuleNotFoundError`. It lives at `db/sql_runner.py`.
- **Statement splitter caveat:** `sql_runner` reads whole files, splits on `;` outside
  `$$…$$` blocks. A leading comment block on a multi-line statement was previously
  dropped as pure comment — fixed in migration 016-era commit
  (`fix(alembic): sql_runner dropped statements whose first line was a comment`).
  Any new migration with leading comments now works cleanly.

### API endpoints summary
`/health` · `/me` · `/brands` CRUD + `/brands/{id}/references` (+`/regenerate`) ·
`/campaigns` (POST creates + research + briefs + fans out creatives;
`{id}/regenerate-missing`) · `/layouts` ·
`/channels` CRUD (+`CONTENT_TYPE_CHANNELS` map) ·
`/creatives` (list w/ `pending_review` filter, batch-signed URLs, limit+offset
pagination; approve→dispatch, reject, `{id}/edit-data`, `{id}/edit`) ·
`/partners` CRUD (auto-upsert on campaign use) ·
`/personas/library` ·
`/template` (tenant-wide asset placement incl. `cta_colour`) ·
`/templates` (Penpot; +`/penpot-info`) ·
`/experiments` CRUD + `/tick` (manual advance) + `/pause` + `/resume` + `/stop`
(kill switch cancels in-flight + refunds committed) + `/approve-iteration` + `/report` ·
`/learnings` CRUD ·
`/connections` (Meta OAuth: `/meta/oauth-url?brand_id=…` + `/meta/callback` +
`/meta/select` + list + `/refresh` + delete).

---

## 4. Frontend (`/frontend`) — Next.js 14 App Router, Tailwind, TanStack Query

### Design system (Phase E)
- **`app/globals.css`** — CSS custom-property token layer with light + dark palettes.
  Primitive utility classes (`.surface`, `.btn`, `.chip`, `.input`, `.gauge`,
  `.timeline-dot`) so pages inherit the palette without per-page restyling.
- **`lib/theme.tsx`** — `ThemeProvider` persists theme in localStorage, defaults to
  `prefers-color-scheme`, toggles `.dark` on `<html>`.
- **`components/app-shell.tsx`** — persistent left sidebar on desktop (Workspace /
  Intelligence / Setup groups) with brand switcher + theme toggle at the foot.
  Mobile drawer at `<lg`. Replaces the old `top-nav.tsx` (removed).

### Core libraries
- **`lib/api.ts`** — fetch wrapper w/ Supabase bearer token. **On 403 signs the user
  out via Supabase browser client and redirects to `/login?forbidden=1`** —
  distinguishes "no session" (401 → login) from "session valid but email not
  allowlisted" (403 → forbidden banner).
- **`lib/supabase.ts`** — Supabase browser client
- **`lib/brand-context.tsx`** — BrandProvider: fetches `/brands`, active brand in
  localStorage
- **`components/status-chip.tsx`** — shared status chip. **Do NOT export named
  components from `app/**/page.tsx`** — App Router rejects unknown route exports.

### Pages
- `/` → redirects signed-in users to `/dashboard`; else marketing shell
- `/login` — magic link. `?forbidden=1` shows "not allowed on this workspace"
- `/onboarding` → redirect to `/brands/new`
- `/dashboard` — KPI cards, active experiments strip, recent learnings, review queue
- `/experiments` — list + inline create form (metric window in **minutes**,
  converts to hours at submit)
- `/experiments/[id]` — **mission control**: budget gauge, iteration timeline,
  awaiting-approval banner, Pause/Resume/Advance/Stop, auto-polls every 6s while
  in-flight, report block on terminal state
- `/learnings` — searchable/filterable library. Scope toggle (active brand vs all),
  dimension filter, confidence slider, evidence drawer
- `/brands` list · `/brands/new` 6-step wizard · `/brands/[id]` edit ·
  `/brands/[id]/references` (upload, extraction status polling)
- `/campaigns/new` — content-type tabs, Design section (Penpot template strip OR
  Auto + 20-layout grid w/ "fast" chip on zero-image styles), brand-scoped persona
  checkboxes, product-image upload, copy sliders, partner picker
- `/campaigns/[id]` — content chip, research notes, brief JSON, carousel strips
  by persona
- `/review` — **paginated** (24 at a time, "Load more"), poll-slowed (12s active / 60s
  idle), poster-first video (video only mounts on click), carousel strips w/ approve-all
- `/creatives/[id]/edit` — canvas editor: text-free bg + draggable text layers
  (fractional coords), drag=move / double-click=edit text / blur=commit,
  inspector (size/colour/weight/CTA pill), full-res canvas composite
- `/settings` hub · `/settings/templates` (Penpot gallery) ·
  `/settings/template` (asset placement) · `/settings/channels` ·
  `/settings/partners` · `/settings/connections` (Meta OAuth w/ per-brand binding)
- `/connections/meta/callback` — post-OAuth landing (Suspense-wrapped `useSearchParams`,
  `dynamic = "force-dynamic"`)

---

## 5. Database (Postgres; migrations 001–016 in `backend/db/migrations/`)

**RLS pattern everywhere:** `tenant_id` column; `app_current_tenant()` reads GUC;
policy USING+CHECK; `FORCE ROW LEVEL SECURITY`; grants to `app_user`. Storage paths
namespaced `tenants/{id}/...`. Alembic auto-applies on API boot.

| # | File | What it adds |
|---|---|---|
| 001 | `001_init.sql` | tenants (w/ template_config), brands, brand_references, campaigns, creatives (w/ embedding vector(512) reserved), partners, channels, personas_library (global, ~32 rows), audit_log, deployments. `app_user` role. pgvector + uuid-ossp extensions. RLS + FORCE + policies for every tenant-scoped table. |
| 002 | `002_v1_1.sql` | Template config + custom channels + persona library + copy constraints |
| 003 | `003_partner_brand.sql` | Partner brand JSON on campaigns |
| 004 | `004_creative_persona.sql` | `creatives.persona_segment` |
| 005 | `005_partners.sql` | Partners directory (name UNIQUE per tenant, w/ products_or_services) |
| 006 | `006_multi_brand.sql` | Multi-brand: brands + brand_references tables; template_config moved to tenants |
| 007 | `007_drop_brand_kits.sql` | Cleanup — drop legacy brand_kits |
| 008 | `008_social_content.sql` | content_type / research / carousel columns + slide_index + 20 Indian personas |
| 009 | `009_layouts_templates.sql` | campaigns.layout_style + template_id; creatives.layout_style + template_id; templates table (RLS) |
| 010 | `010_creative_editor.sql` | creatives.edit_background_path + edit_layout (jsonb) |
| 011 | `011_learning_store.sql` | experiments + experiment_iterations + learnings (w/ vector(768) + HNSW cosine index) + social_posts. RLS everywhere. |
| 012 | `012_meta_connections.sql` | meta_connections (encrypted tokens) + social_posts.connection_id + origin |
| 013 | `013_video_creatives.sql` | creatives.media_type + video_path + thumbnail_path + duration_seconds; campaigns.media_type; index on media_type |
| 014 | `014_audit_entity_text.sql` | audit_log.entity_id → text (was uuid, blocked Meta OAuth state tokens) |
| 015 | `015_meta_conn_per_brand.sql` | meta_connections.brand_id (nullable FK to brands) + index on (tenant_id, brand_id) |
| 016 | `016_experiment_speed.sql` | experiments.metric_window_hours → numeric (was int; allows sub-hour windows); campaigns.skip_governance (bool) |

### Key tables (post-016)
- `tenants` (id, name, owner_user_id, template_config jsonb)
- `brands` (id, tenant_id, name, tone, colours, logo_path, persona_definitions jsonb,
  brand_rules_do/dont, brand_feel, style_description, asset_permission_accepted_at)
- `brand_references` (brand_id, image_path, extracted_style_description, extraction_status)
- `campaigns` (brand_id, goal, persona_segment, brief jsonb, status, copy_constraints,
  partner_brand jsonb, product_image_path, content_type, research_topic/notes,
  carousel_slide_count, layout_style, template_id, media_type, skip_governance)
- `creatives` (campaign_id, brand_id, channel, dimensions, copy_*, storage_path,
  embedding vector(512) reserved, governance_status/issues, human_status/rejection,
  persona_segment, slide_index, layout_style, template_id, edit_background_path,
  edit_layout, media_type, video_path, thumbnail_path, duration_seconds)
- `experiments` (brand_id, goal, goal_metric, goal_target, budget_total, budget_spent,
  budget_committed, per_iteration_cap, channels, status, metric_window_hours (numeric),
  min_spend_for_verdict, max_iterations, langgraph_thread_id, report jsonb)
- `experiment_iterations` (experiment_id, index, hypothesis, applied_learnings,
  brief, campaign_id, format, channel, persona, spend_planned/actual, publish_ref,
  status, metrics, metrics_history, verdict, measure_deadline, published_at,
  measured_at, error)
- `learnings` (brand_id, dimension, statement, confidence, evidence, embedding
  vector(768), times_applied, last_validated_at, superseded_by)
- `meta_connections` (brand_id, meta_user_id, encrypted_access_token, token_scopes,
  token_expires_at, selected_ad_account_id, selected_page_id, selected_page_name,
  selected_page_access_token, selected_ig_user_id, selected_ig_username, status,
  last_error, last_verified_at)
- `social_posts` (connection_id, brand_id, platform, post_ref, permalink, posted_at,
  post_type, caption, tags[], creative_id, metrics, metrics_history, last_polled_at,
  origin ('authored' | 'watched'))
- `templates` (name, penpot_file_id, penpot_page_id, penpot_frame_id, svg_source,
  zones jsonb, preview_path, sync_status/error)
- `partners`, `channels`, `personas_library`, `deployments`, `audit_log`
- `alembic_version`
- LangGraph PostgresSaver tables: `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`

---

## 6. Models & costs (as of Aug 2026)

| Use | Model | Notes |
|---|---|---|
| LLM (brief, copy, judge, layout pick, analysis) | `gemini-2.5-flash` (`-lite` for layout pick) | Free-tier OK |
| Image gen | `gemini-3-pro-image` (Nano Banana Pro) | ~$0.12–0.15/img; aspect via `image_config`; supports image conditioning |
| Fast image gen (demos) | `gemini-2.5-flash-image` | ~10-15s per image (vs Pro's 30-60s); set `IMAGE_MODEL_ID` env |
| Vision (judge, style extraction) | `gemini-2.5-flash` | |
| Research grounding | `gemini-2.5-flash` + `google_search_retrieval` tool | ~$0.005–0.01/call |
| Embeddings | `gemini-embedding-001` | 768-d for learnings pgvector cosine |
| Video | `veo-3.0-generate-001` (`VEO_MODEL_ID` env) | ~$3–6 per 8s clip |
| Background removal | rembg u2net local | free; baked in image |
| Speech (planned) | `whisper-large-v3` (faster-whisper) | in the video auditor sibling notebook |
| OCR (planned) | PaddleOCR v3 | in the video auditor sibling notebook |
| Brand safety | Sightengine (`nudity-2.1,gore,weapon,offensive,text`) | ~$0.001/img |

**Never use:** `gemini-1.5/2.0` (shut down), Imagen (deprecated), `gemini-3.1-pro`,
`gemini-2.5-pro` — history of 404s / zero free quota / renamed to Flash.

Typical costs: banner campaign (2 creatives) ≈ $0.30; typography layouts ≈ $0.01;
5-slide carousel ≈ $0.75; 8s video ≈ $5.

---

## 7. Prompt architecture (hard-won rules — do not regress)

1. **Brand style = ABSOLUTE LAW** — `style_description` >150 chars gets top-of-prompt
   priority framing; illustrative cues (illustrat/vector/pastel/mockup/…) trigger
   explicit anti-photography override
2. **Partner products lock the hero object** (`products_or_services`); persona changes
   styling/mood only — never the object category
3. Personas need **concrete example `image_direction`s** in the briefing prompt
   (abstract "tailor to persona" fails)
4. Composition contract: square → subject centred upper + bottom 35% clean; wide →
   subject right + left 50% clean; no torn-paper transitions; corners clear for logo
   plates
5. No text/cards/fake brands inside generated images — branding is composited after
6. Structured-output undercount: count-check → reinforced retry (temp 0.5) → pad
7. `json.dumps` of briefs/brand dicts: strip `_`-prefixed keys + `default=str`
   (bytes/UUID crash class)
8. Brand kit JSON at prompt start (Gemini implicit caching)
9. **v4.0 orchestrator:** brief prompts get a `=== PROVEN LEARNINGS FOR THIS BRAND ===`
   block from the learning store, right after the brand style block

---

## 8. Env var inventory

Backend (identical on API + worker + beat unless noted):

```
# AI
GEMINI_API_KEY=
FAL_KEY=                                    # fallback image gen; optional
IMAGE_MODEL_ID=                             # optional; defaults to gemini-3-pro-image
VEO_MODEL_ID=                               # optional; defaults to veo-3.0-generate-001
VEO_DURATION_SECONDS=8                      # optional

# Brand safety
SIGHTENGINE_API_USER=
SIGHTENGINE_API_SECRET=

# Supabase (auth + DB + storage)
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_DB_URL=                            # SESSION POOLER URL (postgres.{ref}:pw@aws-*.pooler.supabase.com:5432)
                                            # direct db.* host is IPv6-only, unreachable from Railway
SUPABASE_JWT_SECRET=                        # legacy; unused by auth path
SUPABASE_STORAGE_BUCKET=tenant-assets

# Celery
REDIS_URL=

# Observability
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

# Meta (Phase C)
META_APP_ID=
META_APP_SECRET=
META_REDIRECT_URI=                          # https://<vercel-domain>/connections/meta/callback (NOT api!)
META_API_VERSION=v21.0
META_USE_SANDBOX=true                       # keeps ads PAUSED even after publish
META_LOGIN_CONFIG_ID=                       # required for Business apps (FBL for Business)
TOKEN_ENCRYPTION_KEY=                       # Fernet key; IDENTICAL across API+worker+beat
API_BASE_URL=

# Penpot (parked)
PENPOT_BASE_URL=
PENPOT_ACCESS_TOKEN=

# Auth allowlist (Phase v4.0 hardening)
ALLOWED_EMAILS=                             # comma-separated; empty = allow all; API-only
```

Vercel (frontend):
```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_API_URL=                        # https://<api-domain>
```

---

## 9. Known issues / deferred

### Deferred (v4.1+ material)
- **Meta App Review filings** — Business Verification pending; live spend needs
  App Review approval for ads_management, ads_read, pages_show_list,
  pages_read_engagement, pages_manage_posts, pages_read_user_content,
  instagram_basic, instagram_content_publish, instagram_manage_insights,
  business_management. External timeline 2–6 weeks. Runbook:
  `docs/meta-approval-filings.md`
- **Video ads on Meta** — chunked video upload (`/act_x/advideos` + video_id-based
  creative) not wired. Adapter raises cleanly for `format='video'` on `meta_ads`
  channel. Use `instagram_organic` for video (Reels path works).
- **Google Ads adapter** — stub only
- **Report PDF export** — JSON report + inline HTML view work; reportlab PDF pattern
  exists (see the sibling `Creative_Intelligence_Step9_Report.ipynb`) but not wired
  into the experiments API
- **⌘K command palette** — Phase E.5 polish
- **Sparkline charts on iteration metrics** — data lives in `metrics_history` jsonb,
  UI just needs Recharts
- **Restyle brands wizard + template pages + editor** — functional under the new
  token palette but not systematically restyled
- **Full shadcn/ui install** — token primitives cover 90% of surfaces; hard shift is
  bundle-size churn for polish gain
- **Retention prediction, emotional analysis, audience fit** — noted in the sibling
  video auditor notebook; need labeled historical data

### Known bugs / traps
- **Penpot on Railway private networking** — parked. Backend healthy, frontend nginx
  → backend times out. Resolves naturally on plain Docker (Phase F migration was
  designed for this).
- **Editor:** browser-canvas font ≠ server Geist exactly (webfont fix pending);
  single-line text layers only; pre-v3.1 creatives not editable (no bg)
- **LangGraph checkpoint tables grow unboundedly** (periodic `TRUNCATE checkpoints
  CASCADE` is OK to run when the API is quiet)
- **`creatives.embedding vector(512)`** reserved-unused (Qdrant/CLIP idea superseded
  by v4.0 learnings)
- **Governance judge is cautious** → frequent 'flagged'. By design; expandable
  reasons in review

### Lessons learned — traps I hit and won't hit again
- **Never paste secrets in chat.** All compromised keys listed in §2 must be rotated.
- **Never manually run migrations.** Alembic auto-applies on API boot via
  `entrypoint-api.sh`. Manual SQL only for one-time investigations, not schema changes.
- **Supabase DB URL:** must be the session-pooler URL, NOT the direct `db.*` host
  (which is IPv6-only). Symptom: connection timeouts from Railway.
- **Don't name a local folder `alembic/`** and put helpers inside — Python's
  installed `alembic` package name shadows it. Helpers live at `db/sql_runner.py`.
- **SQL statement splitter** must accept blocks whose first line is a comment. Fixed
  in migration 016-era commit.
- **App Router pages** only allow default + specific metadata exports. Named exports
  → build failure. Shared components go in `components/`.
- **`useSearchParams()`** in App Router pages needs Suspense wrapper OR
  `dynamic = "force-dynamic"`. Callback pages must set both.
- **audit_log.entity_id** was uuid; Meta OAuth state tokens aren't UUIDs. Widened to
  text in migration 014. Any future column that stores mixed identifiers should be
  text-typed.
- **Meta ad-image endpoint** only accepts JPEG/PNG. Our WebP outputs must be
  transcoded before upload. See `_to_jpeg()` in `integrations/meta_ads.py`.
- **`special_ad_categories`** must be a JSON array literal, not a string like `"[]"`.
- **Meta Business apps** cannot use classic Facebook Login. Must use Facebook Login
  for Business → Configurations → `config_id` in the OAuth URL. Redirect URI still
  goes in the params (cross-checked against Configuration).
- **Meta OAuth redirect URI** must point at the **frontend** (Vercel), not the
  backend API. Frontend callback page reads the code and forwards to backend with
  an auth header attached.
- **`TOKEN_ENCRYPTION_KEY`** must be identical across API + worker + beat services.
  Different values → worker can't decrypt what API encrypted → silent publish
  failures.
- **Railway Raw Editor** shell-parses `KEY="value"` — if the value contains `=`
  (like Fernet keys), quoting can mangle it. Use the plain UI editor for such values.
- **Wrong Supabase project** — always verify the project ref in the SQL Editor URL
  matches the API's SUPABASE_URL before running migrations.
- **Migration idempotency:** every SQL file uses `CREATE … IF NOT EXISTS`, `ADD
  COLUMN IF NOT EXISTS`, `DROP … IF EXISTS`. This makes them safe to re-run against
  DBs where earlier schema was applied by hand pre-Alembic.
- **Railway UI Start Command overrides Dockerfile CMD.** If you set the API service
  Start Command to `uvicorn main:app ...`, the entrypoint script is bypassed and
  migrations don't run. Clear the field to inherit the Dockerfile CMD.

---

## 10. v4.0 shipped scorecard

- [x] **Phase 0** — PROJECT-STATE.md doc (this file, now updated to final state)
- [x] **Phase A** — Learning store (migration 011; `learning_store.py`;
  briefing agent `retrieve_learnings` node)
- [x] **Phase B** — Orchestrator engine (`orchestrator.py`; mock ads adapter;
  budget ledger; kill switch; `/experiments` API; Celery beat tick)
- [x] **Phase C** — Meta ads + Instagram organic + social watcher
  (`meta_client.py`; `meta_ads.py`; `instagram_organic.py`; `social_watcher.py`;
  `/connections` API + OAuth; token encryption; Facebook Developer app registered
  on developers.facebook.com)
- [x] **Phase D** — Video generation (Veo); ffmpeg mux with end-card; sampled-frame
  governance; `creatives.media_type=video`; review inline playback
- [x] **Phase E** — Enterprise UI (design tokens; sidebar shell; /dashboard;
  /experiments mission control; /learnings library; /settings/connections;
  Meta OAuth callback page)
- [ ] **Phase F** — Server migration + Penpot revival. **Deferred indefinitely.**
  Instead: teardown to zero-cost state 2026-08-13. To bring back: see
  REVIVAL-RUNBOOK.md.

### Post-v4.0 improvements shipped
- Auto-tick chain (governance/creative → orchestrator immediately)
- Skip governance for mock/sandbox experiment iterations
- Metric windows in minutes (numeric type; UI in minutes)
- IMAGE_MODEL_ID env for fast-image demos
- Email allowlist (ALLOWED_EMAILS)
- Meta connections per-brand binding
- Review page perf (batch signed URLs, pagination, poster-first video, lazy images)
- Alembic auto-apply system (migrations run on API boot)
- Meta ad-image WebP → JPEG transcode
- Informative Meta errors (labelled steps + subcodes)
- Facebook Login for Business `config_id` support
- Meta OAuth redirect fix (backend → frontend URL)
- Cell-level fixes to compositor variance-guard, in-app editor drag model, etc.

---

## 11. Sibling projects

**`Creative_Intelligence_Step9_Report.ipynb`** (Colab notebook, in user's Google Drive
not in this repo) — the video auditor pipeline. Currently at v1 with basic OCR +
speech + rubric + judge + reportlab PDF export. v2 upgrade started (multi-frame
consensus OCR via PaddleOCR + WhisperX-style speech via faster-whisper + Gemini video
ingestion + reconciliation). Copy lives in a separate v2 notebook in Drive. Recommended
future integration: video auditor's `pipeline_result` structure feeds a new
`workers/video_audit.py` in this repo to score creatives before publishing.

---

**See [REVIVAL-RUNBOOK.md](REVIVAL-RUNBOOK.md)** for the practical step-by-step to
redeploy this platform from scratch when you're ready.
