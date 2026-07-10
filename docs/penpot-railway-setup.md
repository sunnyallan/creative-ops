# Penpot on Railway — setup runbook (v3.0 Commit B)

Self-hosted Penpot is the design studio for custom creative templates.
Designers build frames with named placeholder layers (`#headline`, `#image`,
`#cta`…); our backend exports those frames as SVG and renders them with
generated copy + imagery (Commits C/D).

**Realistic added cost: ~$20–30/mo** (the Penpot backend is a JVM that wants
1.5–2 GB RAM). Cheaper alternative if this matters: run Penpot's official
docker-compose on a $12 VPS and point `PENPOT_BASE_URL` at it — everything
else in our integration is identical.

You will add **4 things** to the existing Railway project: a Postgres, and
three Penpot services. All images are official `penpotapp/*`. **Pin the same
version tag on all three** (check https://hub.docker.com/u/penpotapp for the
latest 2.x — e.g. `2.4.3`) so frontend/backend/exporter never drift apart.

---

## Step 1 — Postgres for Penpot (do NOT reuse Supabase)

1. Project canvas → **+ New → Database → Add PostgreSQL**
2. Rename the service to `penpot-db`
3. Open its **Variables** tab and note `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`
   (Railway also exposes `DATABASE_URL` — we'll reference pieces of it below)

## Step 2 — Generate one shared secret

Locally:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Save the output — it becomes `PENPOT_SECRET_KEY` on **backend and exporter both**.

## Step 3 — `penpot-backend` service

1. **+ New → Docker Image** → `penpotapp/backend:<PINNED_TAG>`
2. Rename service to `penpot-backend`
3. **Settings → Networking**: leave **private only** (no public domain)
4. **Variables** (Raw Editor):

```
PENPOT_PUBLIC_URI=https://<will-fill-after-step-5>
PENPOT_DATABASE_URI=postgresql://${{penpot-db.PGHOST}}:${{penpot-db.PGPORT}}/${{penpot-db.PGDATABASE}}
PENPOT_DATABASE_USERNAME=${{penpot-db.PGUSER}}
PENPOT_DATABASE_PASSWORD=${{penpot-db.PGPASSWORD}}
PENPOT_REDIS_URI=redis://default:<REDIS_PASSWORD>@<REDIS_INTERNAL_HOST>:6379/1
PENPOT_SECRET_KEY=<from step 2>
PENPOT_FLAGS=enable-registration disable-email-verification enable-access-tokens enable-smtp-off disable-onboarding-questions
PENPOT_TELEMETRY_ENABLED=false
PENPOT_ASSETS_STORAGE_BACKEND=assets-fs
PENPOT_STORAGE_ASSETS_FS_DIRECTORY=/opt/data/assets
```

   For `PENPOT_REDIS_URI`: copy the existing Redis service's internal URL
   (Redis service → Variables → `REDIS_URL`) and change the trailing `/0`
   (or no suffix) to **`/1`** — Penpot gets its own Redis DB index so it
   never collides with Celery.

5. **Settings → Volumes**: **Add volume** mounted at `/opt/data/assets`
   (this is where uploaded design assets live — without it they vanish on redeploy)

## Step 4 — `penpot-exporter` service

1. **+ New → Docker Image** → `penpotapp/exporter:<SAME_TAG>`
2. Rename to `penpot-exporter`, keep **private only**
3. **Variables**:

```
PENPOT_PUBLIC_URI=http://penpot-frontend.railway.internal:8080
PENPOT_REDIS_URI=<same value as backend's PENPOT_REDIS_URI>
```

   (The exporter's "public uri" is what its headless browser loads — the
   **internal** frontend address is correct here, not the public one.)

## Step 5 — `penpot-frontend` service

1. **+ New → Docker Image** → `penpotapp/frontend:<SAME_TAG>`
2. Rename to `penpot-frontend`
3. **Variables**:

```
PENPOT_BACKEND_URI=http://penpot-backend.railway.internal:6060
PENPOT_EXPORTER_URI=http://penpot-exporter.railway.internal:6061
PENPOT_FLAGS=enable-registration disable-email-verification enable-access-tokens
```

4. **Settings → Networking → Generate Domain** — target port **8080**.
   You get e.g. `https://penpot-frontend-production-xxxx.up.railway.app`
5. Go **back to `penpot-backend` Variables** and set
   `PENPOT_PUBLIC_URI=https://<that domain>` → backend redeploys

## Step 6 — First login + access token

1. Open the frontend domain in the browser → **Create account**
   (registration is open, email verification disabled — fine for beta;
   revisit before exposing broadly)
2. Create a team, e.g. **Creative Ops Templates**
3. Profile icon → **Settings → Access tokens → Generate token**, name it
   `creative-ops-api`, no expiry → **copy the token**

## Step 7 — Wire our platform to Penpot

On **both** the `creative-ops` API service and the `worker` service in Railway,
add:

```
PENPOT_BASE_URL=https://<penpot-frontend domain>
PENPOT_ACCESS_TOKEN=<token from step 6>
```

Both services redeploy. Done.

---

## Verification

1. `https://<penpot domain>` loads the Penpot login/dashboard.
2. Create a quick 1080×1080 board, add a text layer named `#headline`,
   save — no errors in the backend service logs.
3. Token check from your machine:

```bash
curl -s -X POST https://<penpot domain>/api/rpc/command/get-profile \
  -H "Authorization: Token <PENPOT_ACCESS_TOKEN>" \
  -H "Content-Type: application/json" -d '{}' | head -c 300
```

   A JSON blob with your profile (not a 401) = the token works. This exact
   auth path is what the template-sync worker (Commit C) uses.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Frontend loads but login spins forever | `PENPOT_BACKEND_URI` wrong — must be the **internal** backend address with port 6060 |
| Backend crash-loops with DB errors | `PENPOT_DATABASE_URI` malformed — Penpot wants the URI **without** credentials; username/password go in their own vars |
| Exports hang (Commit C) | Exporter can't reach frontend — check `PENPOT_PUBLIC_URI` on the **exporter** points to the internal frontend address |
| "insecure cookie" login failures | Add `disable-secure-session-cookies` to both FLAGS vars only if you're testing over plain http (not needed on Railway https) |
| Backend OOM-killed | Bump service memory to 2 GB (Settings → Resources) |
