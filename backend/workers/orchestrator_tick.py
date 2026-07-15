"""v4.0 Phase B — Orchestrator beat tick.

Runs every ~15 min via Celery beat. For each experiment in `running` status,
advances any in-flight iteration by one node (poll metrics, or analyze if
the measurement window has closed). Also nudges freshly-generating
iterations forward once their creatives finish rendering.

The orchestrator's core logic is idempotent — this task is safe to run
concurrently with orchestrator.start_experiment, and safe to retry.
"""
from __future__ import annotations

import logging
from uuid import UUID

from db.session import tenant_connection
from workers.celery_app import celery_app

log = logging.getLogger("orchestrator_tick")


@celery_app.task(name="orchestrator.tick")
def orchestrator_tick() -> dict:
    """Sweep every running / awaiting-generation experiment and step it forward."""
    from agents.orchestrator import run_next_step

    # Query BYPASSES tenant RLS (service-role connection via a fresh SUPERUSER
    # would be needed for that); instead we walk experiments in status IN
    # ('running','awaiting_approval'-no,'paused'-no) via a raw pool call that
    # sets no tenant GUC and reads only ids/tenant_ids. `experiments` RLS
    # requires a matching tenant, so we do the enumeration through a system
    # role bypass by connecting as the pool user (Supabase service role
    # bypasses RLS by default).
    from db.session import get_pool

    pool = get_pool()
    with pool.connection() as conn:
        # Service-role connections bypass RLS; we scope by status only.
        rows = conn.execute(
            "SELECT id, tenant_id FROM experiments WHERE status = 'running'"
        ).fetchall()

    results = []
    for exp_id, tenant_id in rows:
        try:
            step = run_next_step(str(tenant_id), str(exp_id))
            results.append({"experiment_id": str(exp_id), **step})
        except Exception as e:
            log.exception("tick failed for experiment %s: %s", exp_id, e)
            results.append({"experiment_id": str(exp_id), "error": str(e)})
    return {"processed": len(results), "results": results}
