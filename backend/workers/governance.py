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
    return evaluate(UUID(tenant_id), UUID(creative_id))
