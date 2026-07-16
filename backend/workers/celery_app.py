from celery import Celery
from celery.schedules import crontab

from config import settings

celery_app = Celery(
    "creative_ops",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "workers.creative",
        "workers.governance",
        "workers.style_extractor",
        "workers.research",
        "workers.template_sync",
        "workers.orchestrator_tick",
        "workers.social_watcher",
    ],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    beat_schedule={
        # v4.0 Phase B — advance every running experiment every ~15 min.
        # Requires a Celery beat process (add a `beat` service on Railway).
        "orchestrator-tick": {
            "task": "orchestrator.tick",
            "schedule": crontab(minute="*/15"),
        },
        # v4.0 Phase C — hourly sweep of connected Meta/IG accounts to refresh
        # social_posts + metrics_history so the distiller learns from every
        # post on the connected channels, not only what we authored.
        "social-watcher-hourly": {
            "task": "social.watch",
            "schedule": crontab(minute=7),   # off-cycle from orchestrator ticks
        },
    },
)
