# Creative Ops — MVP

AI-native creative operations. Brief → on-brand creatives → human review → (stubbed) platform deploy.

Built against `d89d3f2d-07e6-4ed9-9272-f8f63808309c.md` (architecture doc), sliced to a 3-day closed-beta scope. See `~/.claude/plans/lets-plan-this-out-mellow-stroustrup.md` for the slice.

## Stack
- Next.js 15 (App Router, TS, Tailwind) + Supabase Auth + TanStack Query
- FastAPI + LangGraph + Celery + Redis
- Supabase (Postgres + pgvector + Storage) with RLS keyed on `app.current_tenant_id`
- Gemini 3.1 Pro (briefing, copy, vision judge), Nano Banana `gemini-2.5-flash-image` (image gen)
- Sightengine (brand-safety stage 2), Gemini vision judge (stage 3). Falconsai stage 1 deferred.
- Pillow channel compositor — Meta 1080×1080 + WhatsApp 1200×628 for MVP.

## What's stubbed
- `integrations/google_ads.py`, `meta_ads.py`, `whatsapp.py`, `sendgrid.py` all conform to a `Deployer` Protocol and currently insert into `deployments` with `status='stubbed'`. Drop in real impls behind the same signature when API approvals land.

## Local dev
1. `cp .env.example .env` — fill `GEMINI_API_KEY`, `SIGHTENGINE_*`, Supabase keys.
2. Create a Supabase project, run `backend/db/migrations/001_init.sql` in the SQL editor, create a public bucket `tenant-assets`.
3. `docker compose up --build`
4. Visit http://localhost:3000 → sign in → onboarding → new campaign → review queue.

## Deploy
- **Frontend** → Vercel: link repo `/frontend`, set `NEXT_PUBLIC_*` env vars.
- **Backend + worker** → Railway: one service from `/backend` running `uvicorn`, second service same image running `celery -A workers.celery_app worker`. Add Redis plugin and set `REDIS_URL`.
- **DB + storage + auth** → Supabase Cloud.

## Verification
See plan file §Verification. Key checks: RLS isolation, governance flagging path, stubbed deployment row + `audit_log` after approve/reject.

## Penpot (v3.0 custom templates)

Custom creative templates are designed in a self-hosted Penpot instance and
rendered by our pipeline. Setup runbook: [docs/penpot-railway-setup.md](docs/penpot-railway-setup.md).
Backend needs `PENPOT_BASE_URL` + `PENPOT_ACCESS_TOKEN` env vars.

## Post-Monday (deferred)
Qdrant + CLIP recycling, learning loop / PostgresStore, multi-persona briefs, governance retry-loop cap, Langfuse, Stripe billing, Google display + emailer channels, Falconsai stage 1.
