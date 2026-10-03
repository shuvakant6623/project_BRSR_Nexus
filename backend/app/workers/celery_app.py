"""Celery application (spec §13/§24). Tasks are thin wrappers — business
logic stays in domain services so it is testable without Celery."""
import logging

from celery import Celery
from celery.signals import after_setup_logger

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "brsr",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "scan-reminders": {
            "task": "app.workers.tasks.scan_reminders",
            "schedule": 3600.0,  # hourly reminder scan (spec §22)
        },
    },
    timezone="UTC",
)


@after_setup_logger.connect
def configure_loggers(**_kwargs):
    logging.getLogger("celery").setLevel(logging.INFO)
