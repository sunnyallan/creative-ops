# Creative Ops

Autonomous AI creative operations platform. Multi-tenant SaaS: brand teams enter a goal
and a budget, the system researches, generates on-brand creatives (image + video +
carousel), publishes to Meta / Instagram, measures real performance, distils learnings
into a persistent brand memory, and iterates — until the goal is met or budget spent.

**Status:** feature-complete through v4.0 as of August 2026. **Not currently
deployed.** All hosted services torn down for cost reasons. Code preserved here for
future revival.

## 📚 Read these first

1. **[docs/PROJECT-STATE.md](docs/PROJECT-STATE.md)** — durable knowledge base.
   What exists, how it fits together, every trap we hit. Read this to understand the
   codebase without archaeology.
2. **[docs/REVIVAL-RUNBOOK.md](docs/REVIVAL-RUNBOOK.md)** — practical step-by-step
   to bring the platform back from cold storage. ~45 min from empty accounts to
   working platform.

## Stack

- **Frontend:** Next.js 14 (App Router, TS, Tailwind, dark-first design tokens),
  Supabase Auth (magic link + email allowlist), TanStack Query
- **Backend:** FastAPI + Celery + LangGraph, Python 3.12
- **Autonomous engine:** durable orchestrator loop (`agents/orchestrator.py`) with
  budget ledger + hybrid guardrails + kill switch + auto-tick chain
- **Learning store:** pgvector cosine similarity over `gemini-embedding-001`
  embeddings, brand-scoped, injected as prompt priors on all future briefs
- **Meta integration:** OAuth via Facebook Login for Business (`config_id`),
  Fernet-encrypted tokens, per-brand connections, Marketing API + IG Content
  Publishing API
- **Video:** Veo 3.0 + ffmpeg end-card mux, sampled-frame governance
- **DB:** Supabase Postgres + pgvector, RLS keyed on `app.current_tenant_id` GUC,
  Alembic auto-apply migrations on API boot
- **Storage:** Supabase Storage (`tenant-assets` bucket), batch-signed URLs
- **AI models:** Gemini 2.5 Flash (LLM), Nano Banana Pro (image), Veo 3.0 (video),
  Sightengine (brand safety)

## Live surfaces (when deployed)

- `/dashboard` — KPI overview
- `/experiments` + `/experiments/[id]` — autonomous loop mission control
- `/learnings` — brand memory library
- `/review` — creatives queue with inline video playback + canvas editor
- `/campaigns/new` — manual campaign creation with 20-layout picker or Penpot templates
- `/brands` — 6-step wizard, reference banner style extraction
- `/settings/connections` — per-brand Meta OAuth

## What's stubbed / deferred

- Google Ads adapter (stub only)
- Meta video ads (chunked upload — use `instagram_organic` for video Reels instead)
- Meta App Review for live spend (external 2-6 week clock; sandbox works today)
- Penpot custom templates (feature works, self-hosting the Penpot backend on
  Railway hit private-networking issues; runbook at `docs/penpot-railway-setup.md`)

## Repo layout

- `backend/` — FastAPI + Celery worker + Alembic migrations
- `frontend/` — Next.js App Router
- `docs/` — PROJECT-STATE, REVIVAL-RUNBOOK, migrations, celery-beat-setup, meta-approval-filings, penpot-railway-setup
- `docker-compose.yml` — local dev harness (not currently used)

## When you're ready to redeploy

Follow **[docs/REVIVAL-RUNBOOK.md](docs/REVIVAL-RUNBOOK.md)**. About 45 min from
empty accounts to a working demo. All migrations auto-apply on first API boot —
no manual SQL required.
