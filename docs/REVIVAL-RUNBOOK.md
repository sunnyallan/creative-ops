# REVIVAL RUNBOOK — bring Creative Ops back from cold storage

> **You (or a future engineer) have this repo but nothing deployed anywhere.** This
> runbook walks you from empty accounts to a fully working platform in ~45 min of
> mostly-automated setup + waiting.
>
> Read **[PROJECT-STATE.md](PROJECT-STATE.md)** first — it's the "what this is" that
> pairs with this "how to bring it back."

---

## 0. Prerequisites — what you need

| Thing | Where | How long |
|---|---|---|
| GitHub access to `sunnyallan/creative-ops` | github.com | — |
| A **fresh Supabase project** | supabase.com — free tier is fine | 2 min |
| A **hosting platform** for backend | Railway (~$25/mo), Render, Fly.io, or your own VPS | 5 min |
| A Vercel account | vercel.com — free tier is fine | 2 min |
| A Gemini API key | aistudio.google.com | 2 min |
| A Sightengine account | sightengine.com — free tier gives 500 ops/mo | 2 min |
| Optional: Langfuse workspace | cloud.langfuse.com — free tier fine | 2 min |
| Optional: Meta Developer App | Already registered on developers.facebook.com as App ID `2289944078434402` — reusable | 0 min |

**Time budget:** ~30 min actual work + ~15 min waiting for deploys.

---

## 1. Supabase (fresh project, ~5 min)

### 1a — Create the project

1. supabase.com → New Project
2. Region: pick the one closest to your backend host (e.g. `ap-northeast-1` if using
   Railway Asia-Northeast, or the same region as your own server)
3. Database password: generate a strong one, save in 1Password
4. Wait ~2 min for provisioning

### 1b — Grab the values you need

Project Settings → API → note these four:

- `SUPABASE_URL` = the "Project URL" (e.g. `https://xxxxx.supabase.co`)
- `SUPABASE_ANON_KEY` = the "anon public" key
- `SUPABASE_SERVICE_ROLE_KEY` = the "service_role secret" key
- `SUPABASE_JWT_SECRET` = under "JWT Settings" (legacy, unused by auth path but keep)

### 1c — Grab the DB URL

Project Settings → Database → **Session Pooler** → Connection string.

Looks like:
```
postgresql://postgres.<REF>:<PASSWORD>@aws-1-<region>.pooler.supabase.com:5432/postgres
```

**CRITICAL:** use the **Session Pooler** URL. The "Direct connection" URL uses
IPv6-only DNS and will silently fail to connect from Railway. Symptom would be
"failed to fetch" on every API request with no clear error.

Save as `SUPABASE_DB_URL`.

### 1d — Create the storage bucket

Storage tab (left sidebar) → **New bucket** → name: `tenant-assets` → **Public: OFF**.

### 1e — Enable pgvector

SQL Editor → run:
```sql
create extension if not exists vector;
create extension if not exists "uuid-ossp";
```

(Migration 001 does this too but running it upfront avoids a first-boot rare-path.)

**Skip creating tables manually.** Alembic auto-creates the entire schema (all 16
migrations) on the first API boot.

---

## 2. Backend hosting (~10 min on Railway; pick your poison)

### Option A — Railway (fastest to redeploy — same as before)

1. railway.app → New Project → Deploy from GitHub → `sunnyallan/creative-ops`
2. It auto-detects three deployable pieces. **Set root directory to `backend` for all
   three:**
   - API service (default name)
   - Duplicate the service twice, rename the copies to `worker` and `beat`
3. **Add a Redis plugin** — Railway → New → Database → Redis
4. **Environment variables** — on all three services, paste this block into
   Variables → Raw Editor (fill in your values):

```env
# AI
GEMINI_API_KEY=<from aistudio.google.com>
SIGHTENGINE_API_USER=<from sightengine.com>
SIGHTENGINE_API_SECRET=<from sightengine.com>

# Supabase
SUPABASE_URL=<from step 1b>
SUPABASE_ANON_KEY=<from step 1b>
SUPABASE_SERVICE_ROLE_KEY=<from step 1b>
SUPABASE_DB_URL=<from step 1c — the SESSION POOLER url>
SUPABASE_JWT_SECRET=<from step 1b>
SUPABASE_STORAGE_BUCKET=tenant-assets

# Redis (Railway auto-injects REDIS_URL if you add the plugin AND click "Add Reference")
REDIS_URL=${{Redis.REDIS_URL}}

# Runtime
PYTHONPATH=/app

# Observability (optional)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

# Auth lockdown
ALLOWED_EMAILS=your.email@example.com

# Token encryption (generate ONE new key, use IDENTICAL VALUE on all 3 services)
# Generate: python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
TOKEN_ENCRYPTION_KEY=<paste the same 44-char base64 string on all 3 services>

# Meta (add after step 5 below; leave blank until then)
META_APP_ID=
META_APP_SECRET=
META_REDIRECT_URI=
META_LOGIN_CONFIG_ID=
META_API_VERSION=v21.0
META_USE_SANDBOX=true
```

5. **Start commands:**
   - **API service** → Settings → Deploy → Start Command: **empty**
     (uses Dockerfile CMD which runs `entrypoint-api.sh` → runs Alembic migrations →
     starts Uvicorn)
   - **worker service** → Start Command:
     `celery -A workers.celery_app worker --loglevel=info --concurrency=2`
   - **beat service** → Start Command:
     `celery -A workers.celery_app beat --loglevel=info`
     (Only ever run ONE beat replica.)

6. **Generate public domain** on the API service: Settings → Networking → Generate Domain.
   Note the URL (e.g. `creative-ops-production.up.railway.app`).

7. **Wait for API to deploy.** Watch the logs:
   - Should see `[entrypoint] applying database migrations…`
   - Then a wave of Alembic `Running upgrade m001 → m002 → … → m016`
   - Then `[entrypoint] migrations complete, starting API` + Uvicorn startup

8. Verify: `curl https://<api-domain>/health` → `{"ok":true}`

### Option B — Render / Fly / your VPS

Deploy the same way: three services (api, worker, beat) all from the `backend/`
Dockerfile, plus Redis. Same env vars. Same start commands. Same 3-service split.
Only difference: how you provision. No code changes.

---

## 3. Vercel frontend (~3 min)

1. vercel.com → New Project → Import `sunnyallan/creative-ops`
2. **Root directory:** `frontend`
3. Environment variables:
```
NEXT_PUBLIC_SUPABASE_URL=<from step 1b>
NEXT_PUBLIC_SUPABASE_ANON_KEY=<from step 1b>
NEXT_PUBLIC_API_URL=<your Railway API domain, e.g. https://creative-ops-production.up.railway.app>
```
4. Deploy. Wait ~2 min.
5. Note the Vercel URL (e.g. `creative-ops-xi.vercel.app`).

---

## 4. First boot verification (~2 min)

1. Open `https://<vercel-domain>` in a browser
2. Root should redirect you to `/login`
3. Enter your allowlisted email (whatever you set as `ALLOWED_EMAILS`)
4. Check email → click the magic link → land on `/dashboard`
5. If you land on the dashboard: **the whole stack works.**

Try creating a brand at `/brands/new`. Reference banners can be a couple of your
previous brand's images, or a paragraph description if you skip the upload step.

Create a `mock_ads` experiment at `/experiments` with a short (~5 min) metric window.
Click **⟳ Advance** — the loop should march plan → generate → publish → measure →
analyze → next iteration. Learnings will start appearing in `/learnings` after 2-3
iterations. This proves everything is wired.

---

## 5. Meta integration (only if you want to publish real ads or IG posts)

The Meta developer app already exists (App ID `2289944078434402`). You'll need to
either:

- **Regain access to it** if you still own the Facebook account it was registered
  under (developers.facebook.com → My Apps)
- **OR register a fresh app** following `docs/meta-approval-filings.md`

### 5a — Get the new app secret

developers.facebook.com → App Settings → Basic → **Reset** the App Secret (the one
in old chat logs is compromised). Save the new value.

### 5b — Update env vars

On the API + worker + beat services in Railway, set:

```env
META_APP_ID=2289944078434402
META_APP_SECRET=<the newly reset secret>
META_REDIRECT_URI=https://<vercel-domain>/connections/meta/callback
META_LOGIN_CONFIG_ID=<from Facebook Login for Business → Configurations>
META_USE_SANDBOX=true
```

### 5c — Update the Configuration

developers.facebook.com → your app → Facebook Login for Business → Configurations →
your Configuration → set Redirect URI to:
```
https://<vercel-domain>/connections/meta/callback
```
(must exactly match `META_REDIRECT_URI` — Meta cross-checks).

### 5d — Wait for redeploy → test

Open `/settings/connections` → pick active brand in sidebar dropdown → confirm the
"Bind to brand" selector shows your brand → **+ Connect Meta** → Facebook OAuth →
approve → picker modal → pick ad account + page + IG → Save.

Run a `meta_ads` experiment to confirm real API roundtrips (ads will be created
PAUSED in your ad account thanks to `META_USE_SANDBOX=true`).

---

## 6. First real experiment (~10 min end-to-end)

Recommended demo settings — feels alive without long waits:

- Goal: `Learn what carousel style [your persona] clicks for our launch`
- Metric: `clicks`
- Target: `5000`
- Budget: `3000`
- Per-iteration cap: `500`
- Metric window: **5 minutes**
- Min spend for verdict: `50`
- Max iterations: `4`
- Channels: `mock_ads`
- Brand: whichever you set up

Hit start → mission control shows the loop marching. Hit **⟳ Advance** repeatedly to
skip the beat cadence and see iterations complete in ~1-2 min each. After iteration 2
or 3, `/learnings` should show real distilled statements. Report block appears when
experiment terminates.

Bump `IMAGE_MODEL_ID=gemini-2.5-flash-image` on the worker service if you want even
faster iterations (10-15s vs 30-60s per image).

---

## 7. Common redeploy problems (paste-friendly troubleshooting)

### "Failed to fetch" on every request
- Health check first: `curl https://<api-domain>/health`
- If timeout: API not up. Check Railway API service logs for tracebacks
- If 500 on specific endpoint: check API runtime logs — look for `TokenCryptoError`
  (Fernet key mismatch or invalid format), `psycopg.errors.UndefinedColumn`
  (migration didn't run), or `MetaAPIError` (Meta call failed)

### API says "column X does not exist"
- Migration didn't apply. Check API startup log for
  `[entrypoint] applying database migrations…`
- If missing, the Start Command in Railway UI is overriding the Dockerfile CMD.
  Clear the API service Start Command field so it inherits from Dockerfile.
- Or manually run Alembic once: SSH into container OR temporarily change API start
  command to `bash /app/entrypoint-api.sh`

### "Meta integration not configured"
- One of `META_APP_ID / META_APP_SECRET / META_REDIRECT_URI` is unset on the API
  service. Even one missing = 503

### Meta OAuth returns "URL Blocked"
- The Configuration in Meta has a different redirect URI than
  `META_REDIRECT_URI` env. Must be character-for-character identical.

### Meta OAuth completes then callback errors
- `META_REDIRECT_URI` points at the backend API (Railway URL). It must point at the
  **frontend** (Vercel URL). Facebook redirects browser to that URL, not an API call.

### "Field required: authorization" on callback
- Same as above — redirect went to backend, backend needs auth header, browser
  redirect from Facebook has no header. Fix redirect URI.

### Worker isn't processing tasks
- Check worker Deploy Logs for `Task received: creative.generate`
- If nothing: Redis isn't reachable. Verify `REDIS_URL` on the worker service
  matches the Redis plugin's connection string (use Railway variable references:
  `${{Redis.REDIS_URL}}`)

### Beat isn't ticking
- Beat needs its own separate service. Only one replica.
- Start command: `celery -A workers.celery_app beat --loglevel=info`
- Beat log should show: `Scheduler: Sending due task orchestrator-tick` every 15 min

### Alembic error: `column brand_id does not exist` (or similar) during migration
- Migration 015 was previously broken on a comment-parsing bug in `db/sql_runner.py`.
  Fixed. If you see this on a fresh deploy: the fix is in the repo — just
  make sure you're on `main` branch.

### Signed URLs failing on review page
- Symptom: images 403 in the browser, review page grey squares
- Fix: verify `SUPABASE_STORAGE_BUCKET=tenant-assets` and the bucket exists in your
  new Supabase project (step 1d above)

---

## 8. Cost expectations after full redeploy

Monthly baseline (assuming light usage — one active user, a few experiments per week):

| Service | Cost |
|---|---|
| Railway (API + worker + beat + Redis, 512MB each) | ~$20–30 |
| Supabase (free tier) | $0 |
| Vercel (Hobby tier) | $0 |
| Langfuse Cloud (free tier) | $0 |
| Gemini API (Flash + Nano Banana Pro, moderate use) | $5–20 |
| Sightengine (500 free ops, then $0.001/img) | ~$0–5 |
| Meta (sandbox mode, no real spend) | $0 |
| **Total** | **~$25–55/mo** |

Add real ad spend on top when App Review approves and you flip `META_USE_SANDBOX=false`.

To scale down: pause Railway services when not actively demoing. Or move to a fixed
VPS (~$8/mo Hetzner CX22 handles it easily).

---

## 9. What you can safely skip on redeploy

- **Penpot** — parked. Templates feature works without it; UI shows an amber "not
  configured" banner on `/settings/templates`. If you ever want it back, add the 3
  services to docker-compose (spec in `docs/penpot-railway-setup.md`).
- **FAL** — fallback image generator; leave `FAL_KEY` empty unless Gemini image
  gen quotas become a problem
- **Business Verification + App Review** — only needed for live Meta ads. Sandbox
  works today with just the app registration.
- **Bundling Phase F changes** — you may want to skip the server-migration piece
  entirely and stay on Railway. Save yourself the ops overhead.

---

## 10. When you're done redeploying — regenerate compromised secrets

Do these AFTER the redeploy is verified working, then update Railway env vars +
redeploy once more:

- [ ] `SUPABASE_SERVICE_ROLE_KEY` — Supabase → Project Settings → API → Reset
- [ ] `SUPABASE_DB_URL` password — Supabase → Project Settings → Database → Reset password
- [ ] `META_APP_SECRET` — Facebook Developer → App Settings → Basic → Reset next to App Secret
- [ ] `GEMINI_API_KEY` — aistudio.google.com → API keys → Regenerate
- [ ] `SIGHTENGINE_API_SECRET` — Sightengine dashboard → Settings
- [ ] `TOKEN_ENCRYPTION_KEY` — new one already (you generated it in step 2)

These were pasted in prior chat logs and should never be reused.

---

**Done.** Once the smoke tests pass in step 4 and (optionally) step 6, you're back
in business. Enjoy.
