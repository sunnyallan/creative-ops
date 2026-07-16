# Database migrations (Alembic — auto-applied on API deploy)

Migrations run **automatically** when the `creative-ops` API service starts.
No more "paste SQL into Supabase manually" step.

## Adding a new migration

1. **Write the SQL** in `backend/db/migrations/NNN_short_name.sql`, following the
   existing style: **every statement must be idempotent**
   (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`,
   `CREATE INDEX IF NOT EXISTS`, `DROP … IF EXISTS`, `DROP POLICY IF EXISTS`
   before `CREATE POLICY`, etc.). Idempotency lets us re-apply safely and lets
   fresh DBs share the same file with in-place DBs.

2. **Add the matching Alembic revision** in `backend/alembic/versions/mNNN_NNN_short_name.py`:

   ```python
   """NNN_short_name — wraps db/migrations/NNN_short_name.sql"""
   from alembic._sql_runner import run_sql_file

   revision = "mNNN"
   down_revision = "mNNN-1"   # the previous head
   branch_labels = None
   depends_on = None

   def upgrade() -> None:
       run_sql_file("NNN_short_name.sql")

   def downgrade() -> None:
       raise NotImplementedError("no downgrade for NNN_short_name")
   ```

3. **Push.** Railway rebuilds the API image → the entrypoint runs
   `alembic upgrade head` → your migration applies → API starts.

## Verifying it applied

Check the API service Deploy Logs for these lines at boot:

```
[entrypoint] applying database migrations…
INFO  [alembic.runtime.migration] Running upgrade mNNN-1 -> mNNN, NNN_short_name
[entrypoint] migrations complete, starting API
```

If the migration errored, the API refuses to start (better than serving with a
broken schema). Deploy will show the failure clearly.

## Which services run migrations

**Only the API service.** Worker and beat use plain Celery start commands
(no entrypoint script) — they'd race the API on `alembic_version` if they
also tried. Their sequence:

- API boots → migrates → serves
- Worker + beat boot in parallel → assume migrations already applied

Since Railway usually starts all three near-simultaneously, in the rare case
worker boots first and tries to use a table that hasn't been added yet, it
crashes and Railway auto-restarts it a few seconds later, by which time the
API has finished migrating. Not ideal but acceptable for our scale.

## Manual controls (rare)

Local dev / troubleshooting:

```bash
cd backend
export SUPABASE_DB_URL=postgresql://...
alembic current       # what version is applied
alembic history       # full list
alembic upgrade head  # apply everything
alembic upgrade +1    # just the next one
alembic stamp head    # mark head as current WITHOUT running (baseline)
```

## Baseline note (2026-07-16)

Alembic was added at revision `m013`. Databases that already had migrations
001–011 applied by hand ran 001–013 on their first Alembic deploy — every
statement is idempotent (`IF NOT EXISTS`) so all pre-existing tables were
no-ops, and only 012 + 013 did real work.
