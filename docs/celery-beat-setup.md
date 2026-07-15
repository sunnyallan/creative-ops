# Celery beat setup (v4.0 Phase B)

The orchestrator advances experiments in-flight via the `orchestrator.tick`
Celery task on a **15-minute schedule**. That schedule is only fired if a
**Celery beat** process is running alongside the worker.

Without beat, experiments still progress on:
- creation (POST /experiments kicks a tick),
- resume / approve-iteration (both kick a tick),
- manual POST /experiments/{id}/tick.

But new iterations queued behind a `measuring` window won't auto-advance.
**Beat is required for the loop to run truly hands-off.**

## Railway (interim, until Phase F server migration)

Add a **new Railway service** (same repo, same image as `worker`):

- **Service name:** `beat`
- **Source:** the existing repo/Dockerfile (auto-deploys with the API + worker)
- **Start command:**
  ```
  cd /app && celery -A workers.celery_app beat --loglevel=info
  ```
- **Env vars:** copy every var from the `worker` service (identical set)
- **Resources:** single instance, minimum RAM (~256 MB). Beat holds no
  real workload; it just publishes scheduled tasks to Redis every N min.

> **Never run more than one beat instance** — it would duplicate every
> scheduled tick. Set replicas = 1.

Sanity check: after deploy, tail the beat service logs — you should see
`Scheduler: Sending due task orchestrator-tick (orchestrator.tick)` every
15 minutes on the wall clock.

## Locally / self-host (Phase F)

Add to `docker-compose.yml` prod profile:

```yaml
  beat:
    image: creative-ops-backend
    command: celery -A workers.celery_app beat --loglevel=info
    env_file: .env
    depends_on: [redis]
    restart: unless-stopped
    deploy:
      replicas: 1
```

Same rule: exactly one replica.

## Verifying the tick

- API: `POST /experiments/{id}/tick` advances the loop synchronously —
  use this during demos to skip the 15-min wait.
- Redis: `redis-cli LLEN celery` (or the Celery-configured queue name)
  should not grow unboundedly; each tick pops one task per running
  experiment.
- Audit trail: every step lands in `audit_log` with `action='iteration.*'`
  or `experiment.*` — read that table to see the loop's movements.
