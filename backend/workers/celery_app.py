from celery import Celery

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
    ],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)
