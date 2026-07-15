# PROJECT-STATE — Creative Ops platform

> **Purpose of this file:** complete session-independence artifact. Any engineer or AI session
> should be able to resume work on this codebase cold from this document alone.
> Maintained as of **v3.1** (July 2026), with the approved **v4.0 plan** appended.
> Update this file whenever a phase ships.

---

## 1. What this product is

Multi-tenant AI creative-operations SaaS. A brand manager sets up a brand (colours, personas,
reference banners, rules), then generates on-brand marketing creatives — banners, social posts,
carousels — from a one-line goal. AI writes the brief and copy, generates imagery, composites
text/logos, runs brand-safety governance, and queues results for human review, editing, and
(stubbed) platform deployment. v4.0 (in progress) adds an autonomous goal+budget orchestration
loop with a persistent learning store and real Meta publishing.

### Live deployments
| Surface | Where |
|---|---|
| Frontend | Vercel — `https://creative-ops-xi.vercel.app` (repo `/frontend`, auto-deploy on push) |
| API | Railway — `https://creative-ops-production.up.railway.app` (service `creative-ops`, `/backend`, Dockerfile) |
| Worker | Railway — service `worker`, same image, `celery -A workers.celery_app worker --loglevel=info --concurrency=2` |
| Redis | Railway plugin (Celery broker/backend; DB index 1 reserved for Penpot) |
| DB / Auth / Storage | Supabase project `iqmajludgkcvzgqegxds` — bucket `tenant-assets` |
| Observability | Langfuse cloud (`LANGFUSE_HOST=https://cloud.langfuse.com`) |
| Penpot | Railway services `penpot-frontend/backend/exporter` + `penpot-db` — **PARKED, non-functional** (see §8) |
| Repo | GitHub `sunnyallan/creative-ops`, branch `main`; Railway API start command lives in UI (railway.json holds build/restart only) |

**Deploy loop:** `git push` → Railway + Vercel auto-deploy. **SQL migrations are NEVER auto-applied** —
paste each `backend/db/migrations/NNN_*.sql` into the Supabase SQL Editor manually. This has bitten us
repeatedly (every "Failed to fetch" incident was an unapplied migration).

---

## 2. Backend architecture (`/backend`)

FastAPI + Celery + LangGraph. Python 3.12, Dockerfile base `python:3.12-slim` (Debian Trixie —
note the `libgdk-pixbuf-2.0-0` hyphenated package name). Fonts (Geist bundled in `backend/fonts/` +
DejaVu via apt) and the rembg `u2net` model are baked into the image at build.

### Entry + platform
- `main.py` — FastAPI app, CORS `*`, routers: brands, brand_references, campaigns (+`layouts_router` = `GET /layouts`), channels, creatives, partners, personas, template (asset placement), templates (Penpot)
- `auth.py` — verifies Supabase bearer tokens by calling `{SUPABASE_URL}/auth/v1/user` (60s in-proc cache). **Do not decode JWTs locally** — Supabase uses asymmetric keys. `_ensure_tenant` auto-creates one tenant per auth user.
- `db/session.py` — psycopg pool; `tenant_connection(tenant_id)` sets `app.current_tenant_id` GUC per txn (RLS enforcement point)
- `config.py` — pydantic-settings; env inventory in §7
- `storage.py` — Supabase Storage (service-role): `upload_bytes`, `signed_url`, `download_bytes`
- `observability.py` — `traced_generate(...)`: Langfuse-wrapped Gemini calls (trace per call, tenant as user_id, campaign as session_id)
- `layouts.py` — **20-layout registry**; each: `asset_plan` (`none|full|subject_cutout|multi:N`), `image_prompt_fragment`, `compositor_mode`, `mode_params`. Helpers: `get_layout`, `asset_plan_of`, `registry_for_prompt`, `registry_for_api`
- `penpot_client.py` — Penpot RPC `get-file` (frame-id by board name; transit-key normalisation) + `/api/export` frame→SVG. Token auth. Parked with Penpot.

### Agents
- `agents/briefing_agent.py` — LangGraph `StateGraph`, PostgresSaver on Supabase (thread `campaign:{id}`):
  `read_brand_kit → analyse_persona → pick_layout → generate_brief → persist_brief`
  - `pick_layout`: 'auto' → Gemini Flash-Lite picks from registry; persisted on campaign; stamped on every brief
  - `generate_brief`: content-type framing (banner/post/carousel w/ slide roles hook→points→cta), research-notes block, brand rules block, persona-specific concrete image_direction examples, copy length caps (defaults 30/50/15), partner block (products lock the hero object; persona changes style only), **count-check → retry with reinforcement → pad** (Gemini undercount defence)

### Workers (Celery; all registered in `workers/celery_app.py` includes)
- `workers/creative.py` — task `creative.generate(tenant_id, campaign_id, brief_index)`:
  1. Loads campaign (brief, constraints, partner, brand_id, product_image_path, content_type, slide_count, template_id) + brand from `brands`
  2. Carousel anchored coherence: slide 0 first; slides 1+ receive slide-0 PNG as conditioning; requeue w/ countdown=10 if anchor missing
  3. **Asset planner** by layout/template: `none` (no image gen — ~$0.01 creatives), `full`, `subject_cutout` (white-bg prompt + rembg → RGBA), `multi:N` (first anchors rest); template image slots override
  4. `_gen_image` prompt stack (order matters): BRAND STYLE block (ABSOLUTE LAW; >150 chars triggers priority framing + illustrative-cue anti-photography override), product-image conditioning part, layout fragment, cutout mode, persona&scene, subject (partner products lock), composition (aspect-aware square-centred / wide-right, clean text zones, no torn-paper), hard bans (no cards/text/fake brands)
  5. Renders via `render_layout` (or `render_template` when campaign.template_id) → WebP q82
  6. **v3.1:** second render with blank copy → `*_bg.webp` → `edit_background_path` (in-app editor base)
  7. Inserts creative row → kicks `governance.run`
  - Internal brief keys are `_`-prefixed (bytes etc.) and **must be stripped before json.dumps** (`default=str` everywhere — recurring bug class)
- `workers/compositor.py` — Pillow. Legacy `composite()` = overlay mode (aspect-aware text bottom-left, 3-line wrap, fixed sizes 62/30/46, WCAG auto text colour, variance>40 safe-zone gradient guardrail, CTA pill bbox-true centring + reverse-fill when pill≈bg, dual logo plates opposite corners, SVG logos via cairosvg). v3 `render_layout()` dispatch + modes: typo, quote, stat, split_h/v, cutout(polaroid/minimal), meme, grid, collage, before_after, editorial, duotone post-filter. All WebP q82.
- `workers/governance.py` → `governance/pipeline.py` — Sightengine (nudity-2.1/gore/weapon/offensive/text; >0.5 blocks) then Gemini judge (knows body copy is NOT on image; judge severity 'block' is downgraded to 'warn' — **only Sightengine can hard-block**). Status: passed/flagged/blocked.
- `workers/research.py` — `research.gather`: Gemini + Google search grounding → 250-400 word notes on `campaigns.research_notes` (runs synchronously in POST /campaigns when topic present)
- `workers/style_extractor.py` — `brand.extract_reference_style`: vision-describe each reference banner → aggregate into `brands.style_description`
- `workers/template_sync.py` / `workers/template_renderer.py` — Penpot board→SVG sync; placeholder fill (#headline/#body/#cta/#image[N]/#logo/#partner_logo/#slide_pip; shrink-to-fit text; base64 image swap) + cairosvg rasterize. Functional code; blocked only by Penpot hosting.

### Integrations (`integrations/`)
`Deployer` Protocol; `dispatch(channel,...)` routes approve→deployer. All four (google_ads, meta_ads, whatsapp, sendgrid) are **stubs** writing `deployments` rows `status='stubbed'`. v4.0 replaces meta_ads with the real SDK adapter and adds `mock_ads`.

### API endpoints summary
`/me` · `/brands` CRUD + `/brands/{id}/references` (+`/regenerate`) · `/campaigns` (POST creates + research + briefs + fans out creatives; `{id}/regenerate-missing`) · `/layouts` · `/channels` CRUD (+ `CONTENT_TYPE_CHANNELS`: banner→meta_feed+whatsapp, social_post→IG post+portrait, carousel→IG slide×N) · `/creatives` (list w/ `pending_review` filter, approve→dispatch, reject, `{id}/edit-data`, `{id}/edit`) · `/partners` CRUD (auto-upsert on campaign use) · `/personas/library` · `/template` (tenant-wide asset placement incl. `cta_colour`) · `/templates` (Penpot; + `/penpot-info`)

---

## 3. Frontend (`/frontend`) — Next.js 14 App Router, Tailwind, TanStack Query

- `lib/api.ts` — fetch wrapper w/ Supabase bearer; `lib/supabase.ts`; `lib/brand-context.tsx` — BrandProvider: fetches `/brands`, active brand in localStorage
- `components/top-nav.tsx` — brand switcher + New campaign / Review / Brands / Templates / Settings
- Pages:
  - `/` → redirects signed-in → `/campaigns/new`; `/login` magic link; `/onboarding` → redirect `/brands/new`
  - `/brands` list · `/brands/new` 6-step wizard (basics, colours+logo+fonts, personas w/ library picker, rules do/dont/feel, references **mandatory: ≥2 images OR ≥200-char style description**, permission) · `/brands/[id]` edit (incl. logo replace) · `/brands/[id]/references` (upload, extraction status polling, re-aggregate)
  - `/campaigns/new` — content-type tabs (Banner/Post/Carousel), research topic + slide slider for social, **Design section** (Penpot template strip → else Auto + 20-layout grid w/ "fast" chips), brand-scoped persona checkboxes, product-image upload, copy sliders, partner picker (saved/new w/ products_or_services field)
  - `/campaigns/[id]` — content chip, research notes details, brief JSON details, carousel strips grouped by persona w/ n/N pips; smart polling (8s while generating → stop)
  - `/review` — carousel strips w/ approve-all; cards: channel/persona/layout badges, governance chips + expandable flag reasons, Approve / **Edit** / Reject(tag+reason); poll 8s active→30s idle
  - `/creatives/[id]/edit` — **canvas editor**: text-free bg + draggable text layers (fractional coords), drag=move / double-click=edit text / blur=commit, inspector (size/colour/weight/CTA pill), full-res canvas composite → `POST edit` replaces storage_path; "not editable" state for pre-v3.1 creatives
  - `/settings` hub · `/settings/templates` (Penpot gallery/register/sync/Edit-in-Penpot; amber banner when unconfigured) · `/settings/template` (asset placement) · `/settings/channels` · `/settings/partners`

---

## 4. Database (Supabase Postgres; migrations 001–010 in `backend/db/migrations/`)

**RLS pattern everywhere:** `tenant_id` column; `app_current_tenant()` reads GUC; policy USING+CHECK; `FORCE ROW LEVEL SECURITY`; grants to `app_user`. Storage paths namespaced `tenants/{id}/...`.

| Table | Key columns (beyond id/tenant_id/created_at) |
|---|---|
| tenants | name, owner_user_id, **template_config jsonb** (logo_position, title_bar[auto/solid_dark/solid_brand/gradient/none], title_position, cta_style, cta_colour) |
| brands | name, tone, brand_values, primary/secondary/accent_colour, heading/body_font, logo_path, persona_definitions jsonb, brand_rules_do/dont, brand_feel, **style_description** (aggregated from references), asset_permission_accepted_at |
| brand_references | brand_id, image_path, extracted_style_description, extraction_status |
| campaigns | brand_id, goal, persona_segment, brief jsonb, status, copy_constraints jsonb, partner_brand jsonb (snapshot incl products_or_services), product_image_path, content_type[banner/social_post/social_carousel], research_topic/notes, carousel_slide_count, **layout_style**, **template_id** |
| creatives | campaign_id, brand_id, channel, dimensions, copy_headline/body/cta, storage_path, embedding vector(512) (unused, reserved), governance_status/issues, human_status/rejection, persona_segment, slide_index, layout_style, template_id, **edit_background_path**, **edit_layout jsonb** |
| partners | name UNIQUE(tenant), logo_path, primary_colour, **products_or_services** (locks AI hero subject) |
| channels | key UNIQUE(tenant), display_name, w, h, kind, enabled (built-ins merged in code) |
| personas_library | GLOBAL (no RLS), ~32 rows incl. 20 Indian-market personas; UNIQUE(name) |
| templates | name, penpot_file/page/frame_id, svg_source, zones jsonb (incl _board_name), preview_path, sync_status/error |
| deployments | creative_id, channel, status('stubbed'), payload jsonb |
| audit_log | user_id, action, entity, entity_id, meta jsonb |
| checkpoints / checkpoint_blobs / checkpoint_writes | LangGraph PostgresSaver (grows; truncate with cleanups) |

**Applied through migration 010.** Next: 011 (v4.0 Phase A).

---

## 5. Models & costs (June–July 2026)

| Use | Model | Notes |
|---|---|---|
| LLM (brief, copy, judge, layout pick, analysis) | `gemini-2.5-flash` (`-lite` for layout pick) | Free-tier OK; billing enabled |
| Image gen | `gemini-3-pro-image` (Nano Banana Pro) | ~$0.12–0.15/img; aspect via `image_config`; supports image conditioning (product/anchor Parts) |
| Vision (judge, style extraction) | `gemini-2.5-flash` | |
| Research grounding | `gemini-2.5-flash` + `google_search_retrieval` tool | ~$0.005–0.01/call |
| Embeddings (v4.0) | `gemini-embedding-001` planned | 768-dim for `learnings` |
| Video (v4.0) | Veo 3.x via google-genai planned | ~$3–6 per 8s |
| Bg removal | rembg u2net local | free; model baked in image |
| **Never use** | gemini-1.5/2.0 (shut down), Imagen (deprecated), `gemini-3.1-pro`/`2.5-pro` on this key | history: 404s / zero free quota |

Typical costs: banner campaign (2 creatives) ≈ $0.30 Pro-image; typography layouts ≈ $0.01; 5-slide carousel ≈ $0.75.

## 6. Prompt architecture (hard-won rules — do not regress)

1. **Brand style is ABSOLUTE LAW** — style_description >150 chars gets top-of-prompt priority framing; illustrative cues (illustrat/vector/pastel/mockup/…) trigger explicit anti-photography override
2. **Partner products lock the hero object** (`products_or_services`); persona changes styling/mood only — never the object category
3. Personas need **concrete example image_directions** in the briefing prompt (abstract "tailor to persona" fails)
4. Composition contract: square→subject centred upper + bottom 35% clean; wide→subject right + left 50% clean; no torn-paper transitions; corners clear for logo plates
5. No text/cards/fake brands inside generated images — branding is composited after
6. Structured-output undercount: count-check → reinforced retry (temp 0.5) → pad
7. json.dumps of briefs/brand dicts: strip `_`-prefixed keys + `default=str` (bytes/UUID crash class)
8. Brand kit JSON at prompt start (Gemini implicit caching)

## 7. Env var inventory

Backend (Railway API + worker, identical): `GEMINI_API_KEY, FAL_KEY, SIGHTENGINE_API_USER/SECRET, SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_DB_URL` (**Session-pooler URL** `postgres.{ref}:pw@aws-…pooler.supabase.com:5432` — direct `db.*` host is IPv6-only and unreachable), `SUPABASE_JWT_SECRET` (legacy, unused by auth path), `SUPABASE_STORAGE_BUCKET=tenant-assets, REDIS_URL` (Railway Redis), `PYTHONPATH=/app, LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST, PENPOT_BASE_URL, PENPOT_ACCESS_TOKEN` (unset→banner), stub keys (GOOGLE_ADS_*, META_*, WHATSAPP_*, SENDGRID_*).
Vercel: `NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, NEXT_PUBLIC_API_URL`.

## 8. Known issues / deferred

- **Penpot on Railway: PARKED.** Backend healthy (binds `::`), frontend nginx→backend times out over Railway private networking (both v4/v6). Untried: public-domain-for-backend workaround. **Resolves naturally in Phase F** (plain docker-compose). Templates UI degrades to amber banner.
- **Editor:** browser-canvas font ≠ server Geist exactly (webfont fix pending); single-line text layers only; pre-v3.1 creatives not editable (no bg)
- **Supabase DB password compromised in chat logs — rotation still pending** (do during Phase F cutover); Sightengine/Gemini keys same status
- Egress: WebP q82 helped; thumbnails deferred; watch Supabase bandwidth
- LangGraph checkpoint tables grow unboundedly (periodic truncate OK)
- `creatives.embedding vector(512)` reserved-unused (Qdrant/CLIP idea superseded by v4.0 learnings)
- Governance judge cautious → frequent 'flagged' (by design; reasons expandable in review)

## 9. v4.0 plan (approved) — condensed checklist

Full plan: `~/.claude/plans/i-want-to-now-woolly-sutherland.md`. Decisions: **Meta first + organic watcher** (file approvals day 1; sandbox + mock adapter meanwhile) · **hybrid spend guardrails** (auto ≤ per-iteration cap; above → one-click approval; kill switch) · **video included** (Veo) · **migrate to user's server as final phase** (fixes Penpot).

- [x] **0** `docs/PROJECT-STATE.md` (this file)
- [ ] **A** Learning store — migration 011 (`experiments`, `experiment_iterations`, `learnings` w/ vector(768), `social_posts`), `learning_store.py` distill/retrieve (gemini-embedding-001), `retrieve_learnings` briefing node w/ PROVEN LEARNINGS block
- [ ] **B** Orchestrator — `agents/orchestrator.py` durable LangGraph (plan→research→learnings→brief_and_generate→governance→spend_gate→publish→measure-interrupt→analyze→distill→decide→report), budget ledger invariant, Celery **beat** `orchestrator.tick` 15min, `integrations/mock_ads.py` simulator, `/experiments` API (+approve/pause/resume/stop/report)
- [ ] **C** Meta — day-1 filings (Business Verification + App Review: ads_management, ads_read, pages_read_engagement, instagram_basic, instagram_manage_insights); real `meta_ads.py` (facebook-business; paused-by-default sandbox; Insights ingestion; persona→targeting map); `workers/social_watcher.py` hourly; `/settings/connections` OAuth + encrypted tokens
- [ ] **D** Video — `workers/video.py` Veo 6-8s, ffmpeg end-card (compositor frame) + thumbnail, 3-frame sampled governance, `creatives.media_type/video_path`, review playback, adapters accept video
- [ ] **E** Enterprise UI — shadcn/ui + tokens + dark-first, sidebar shell + ⌘K, `/dashboard`, `/experiments` mission control (timeline, budget gauge, metric charts, approval banner, kill switch), `/learnings` library, report view + PDF (reportlab pattern), restyle existing pages
- [ ] **F** Migration — compose prod profile (api/worker/**beat**/redis/penpot stack) + Dokploy on user's server (specs TBD — ask), DNS cutover, Railway decommission, **rotate DB password**, `docs/deploy-selfhost.md`

**Verification per phase** is specified in the plan file (mock-adapter E2E loop with 5-min windows is the Phase B acceptance test).
