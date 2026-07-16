# Meta approval filings (v4.0 Phase C)

**File these on day 1** — external timelines are 2–6 weeks and can't be
compressed. Every day of delay is a day your live-spend loop can't launch.
The **sandbox works from hour zero** with no filings; only *live* Meta
publishing is gated by App Review.

Everything below happens at [developers.facebook.com](https://developers.facebook.com/) and
[business.facebook.com](https://business.facebook.com/).

---

## Step 1 — Meta Business Manager (5 min)

Create (or claim) a **Business Manager**. Every downstream verification
attaches to it.

  Business Settings → Business Info → verify company registration details
  (GST/CIN/etc). Add all the humans who need admin access.

## Step 2 — Meta Developer App (10 min)

developers.facebook.com → **My Apps → Create App**
  - Type: **Business**
  - Attach to the Business Manager from Step 1
  - App name: something recognisable, e.g. `Creative Ops Growth Engine`
  - App contact email: a real, monitored inbox

App Dashboard → **Settings → Basic** → note the **App ID** and **App
Secret** — these become `META_APP_ID` / `META_APP_SECRET` in Railway
env.

  Also set:
  - App Domains (e.g. your api domain minus scheme)
  - Privacy Policy URL   (**required for App Review**)
  - Terms of Service URL (**required for App Review**)
  - Data Deletion Instructions URL

## Step 3 — Add products to the app

Dashboard → **Add Product**, add each of:
  - **Facebook Login** — under Settings, add the Valid OAuth Redirect URI:
    `https://<your api domain>/connections/meta/callback`
    (matches `META_REDIRECT_URI`)
  - **Marketing API** — enables ad-management endpoints
  - **Instagram Graph API** — enables IG business account APIs

## Step 4 — Business Verification (SLOW — file today)

Business Settings → **Security Center → Start Verification**.
  Required uploads:
    - Business licence / GST certificate
    - Utility bill or bank statement at the registered address
    - Domain ownership proof (DNS TXT record or a meta tag they generate)

  **Reviews take 2–5 business days typically, sometimes 2 weeks.** You
  cannot request Advanced Access for the permissions we need without
  this being **approved** first.

## Step 5 — App Review submissions

App Dashboard → **App Review → Permissions and Features**. For each
permission below, click **Request Advanced Access** and file the review.

  Required permissions:
    - `ads_management`               (create + manage ads via Marketing API)
    - `ads_read`                     (insights ingestion)
    - `pages_show_list`              (list the user's pages during connect)
    - `pages_read_engagement`        (page post metrics)
    - `pages_read_user_content`      (list page posts for watcher)
    - `pages_manage_posts`           (organic FB posting; optional if IG-only)
    - `instagram_basic`              (read connected IG account)
    - `instagram_content_publish`    (publish IG media)
    - `instagram_manage_insights`    (IG insights)
    - `business_management`          (multi-tenant business ownership)

  Each request needs:
    - **Screencast** (2–4 min) showing the app flow that uses the permission.
      Record while running the sandbox flow: connect, pick ad account,
      run one experiment iteration, view the ad in Meta Ads Manager.
    - **Written description**: "Autonomous ad-optimisation platform for
      brand marketers. Uses this permission to <specific use>. User consents
      via Facebook Login at connection time."
    - **Test user**: create a test user under App Roles → Roles → Test Users,
      give reviewers those credentials.

  **Turnaround: 5–15 business days per submission**, sometimes rejected
  once with a request for clearer screencasts. Budget two rounds.

## Step 6 — App Modes

Until App Review approves everything, the app runs in **Development Mode**
— usable only by roles you add manually (App Admin, Developer, Tester).
That's enough to test end-to-end with the sandbox ad account.

When all permissions are approved: **App Mode → Live**. Then real users
can log in and the loop can spend live budget.

---

## Sandbox = usable today (no filings needed)

  1. Business Settings → Ad Accounts → **Create Sandbox Ad Account**
     (or use an existing one — sandbox is a per-account setting)
  2. Sandbox ad accounts:
     - accept only fake billing
     - never actually deliver impressions
     - return synthetic-shaped insights (small numbers) so the loop's
       poll → analyze → distill wiring is exercisable end-to-end
  3. Set `META_USE_SANDBOX=true` in Railway env — ads created via the
     orchestrator stay `PAUSED` regardless, so nothing spends real money
     even if you accidentally hit a live account.

  Verify wiring in sandbox:
    - Connect via `/settings/connections` (frontend Phase E adds the UI;
      for now hit `GET /connections/meta/oauth-url` and paste the URL)
    - Select ad account + page + IG
    - Run one experiment with `channels=['meta_ads']`
    - The ad should appear in Meta Ads Manager under the sandbox account,
      status Paused, budget matching `spend_planned`

---

## Environment variables to set once ready

On the API, worker, AND beat services in Railway:

    META_APP_ID=<from App Dashboard → Basic>
    META_APP_SECRET=<same>
    META_REDIRECT_URI=https://<api domain>/connections/meta/callback
    META_API_VERSION=v21.0
    META_USE_SANDBOX=true          # flip to false only after live approval
    TOKEN_ENCRYPTION_KEY=<generate with the command in .env.example>
    API_BASE_URL=https://<api domain>

`TOKEN_ENCRYPTION_KEY` MUST be the same value on api / worker / beat —
tokens encrypted on one service must be decryptable on the others.

---

## Common gotchas

- **"Invalid OAuth redirect_uri"** on callback → the URI in `META_REDIRECT_URI`
  must EXACTLY match what's listed under Facebook Login → Settings →
  Valid OAuth Redirect URIs (protocol, host, path — every character).
- **"App not active"** for real users → you're still in Development Mode.
  Add them as Testers, or ship App Review.
- **Long-lived tokens still expire** at ~60 days. `POST /connections/{id}/refresh`
  today just verifies; a background refresh loop lands with Phase F.
- **Rate limits** hit fast on Marketing API. `meta_client.with_retry` has
  exponential backoff for 5xx + Meta transient error codes; if the ceiling
  becomes a real problem, we shard across more app IDs (a Phase later).
