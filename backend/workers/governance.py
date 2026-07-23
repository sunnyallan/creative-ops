import sys
from pathlib import Path
from uuid import UUID

# Ensure /app is importable even if PYTHONPATH didn't get set
_APP = str(Path(__file__).resolve().parent.parent)
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from workers.celery_app import celery_app


@celery_app.task(name="governance.run")
def run_governance(tenant_id: str, creative_id: str) -> dict:
    from governance.pipeline import evaluate
    result = evaluate(UUID(tenant_id), UUID(creative_id))
    # If this creative belongs to an experiment iteration, kick a tick
    # immediately — no waiting for the 15-min beat cadence.
    _maybe_kick_orchestrator(tenant_id, creative_id)
    return result


def _maybe_kick_orchestrator(tenant_id: str, creative_id: str) -> None:
    """When an experiment iteration's creatives finish, wake the orchestrator
    right away so publish → measure runs on the same second, not 0–15 min later."""
    from db.session import get_pool
    try:
        pool = get_pool()
        with pool.connection() as conn:
            r = conn.execute(
                "SELECT 1 FROM experiment_iterations ei "
                "JOIN creatives c ON c.campaign_id = ei.campaign_id "
                "WHERE c.id = %s AND c.tenant_id = %s AND ei.status = 'generating' LIMIT 1",
                (str(creative_id), tenant_id),
            ).fetchone()
        if r:
            from workers.orchestrator_tick import orchestrator_tick
            orchestrator_tick.delay()
    except Exception:
        pass  # never let this break governance completion
