"""
Celery application configuration for OpsRelay.

Celery handles background task processing with Redis as both the message broker
and result backend. This configuration is designed for:
- Reliable task execution with proper error handling
- Monitoring and debugging with task state tracking
- Timeout protection to prevent hung workers
"""
import os
import logging
from celery import Celery

logger = logging.getLogger(__name__)

# Get Redis URL from environment or use default for development
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Initialize Celery app
celery_app = Celery(
    "opsrelay",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.workers.tasks"]  # Automatically load tasks module
)

# Configure Celery with production-ready settings
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone handling
    timezone="UTC",
    enable_utc=True,

    # Task execution
    task_track_started=True,  # Track task execution progress
    task_time_limit=300,  # 5 minute max per task (prevent hung workers)

    # Worker settings
    worker_prefetch_multiplier=4,  # Number of tasks to prefetch
    worker_max_tasks_per_child=1000,  # Recycle worker after N tasks
)

logger.info(f"Celery configured with broker: {REDIS_URL}")
