"""Celery application configuration"""
import os
from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "opsrelay",
    broker=redis_url,
    backend=redis_url
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


@app.task
def process_alert(alert_id: int):
    """Process an alert - stub implementation"""
    return {"status": "processed", "alert_id": alert_id}
