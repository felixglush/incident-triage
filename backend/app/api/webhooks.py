"""
Webhook API endpoints for receiving alerts from monitoring platforms.

This module contains the FastAPI router for webhook endpoints.
Business logic is delegated to services layer for separation of concerns.
"""
import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.signature_verification import (
    verify_datadog_signature,
    verify_sentry_signature
)
from app.services.webhook_processor import WebhookProcessor
from app.workers.tasks import process_alert

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/datadog")
async def datadog_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Receive alerts from Datadog.

    This endpoint:
    1. Verifies webhook signature for security
    2. Parses the Datadog payload
    3. Creates an Alert record (or returns existing if duplicate)
    4. Queues the alert for async ML processing (Phase 1 Week 3)
    5. Returns quickly to avoid Datadog timeout

    Security:
    - Signature verification prevents unauthorized requests
    - Set DATADOG_WEBHOOK_SECRET environment variable
    - Use SKIP_SIGNATURE_VERIFICATION=true only in development

    Returns:
        200: Alert received successfully
        401: Invalid signature
        400: Malformed payload
        500: Internal error
    """
    # Read raw body for signature verification
    body = await request.body()

    # Verify signature
    signature = request.headers.get("X-Datadog-Signature")
    if not verify_datadog_signature(body, signature):
        logger.warning(f"Rejected Datadog webhook with invalid signature from {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse Datadog webhook JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Process webhook through business logic
    processor = WebhookProcessor(db)

    try:
        alert = processor.process_datadog_webhook(payload)

        # Queue alert for async ML processing
        process_alert.delay(alert.id)
        logger.debug(f"Alert {alert.id} queued for processing")

        logger.info(f"Datadog webhook processed: alert_id={alert.id}")

        return {
            "status": "received",
            "alert_id": alert.id,
            "external_id": alert.external_id
        }

    except ValueError as e:
        logger.error(f"Invalid Datadog payload: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"Error processing Datadog webhook: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sentry")
async def sentry_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Receive alerts from Sentry.

    This endpoint:
    1. Verifies webhook signature for security
    2. Parses the Sentry payload
    3. Creates an Alert record (or returns existing if duplicate)
    4. Queues the alert for async ML processing (Phase 1 Week 3)
    5. Returns quickly to avoid Sentry timeout

    Security:
    - Signature verification prevents unauthorized requests
    - Set SENTRY_WEBHOOK_SECRET environment variable
    - Use SKIP_SIGNATURE_VERIFICATION=true only in development

    Returns:
        200: Alert received successfully
        401: Invalid signature
        400: Malformed payload
        500: Internal error
    """
    # Read raw body for signature verification
    body = await request.body()

    # Verify signature
    signature = request.headers.get("Sentry-Hook-Signature")
    if not verify_sentry_signature(body, signature):
        logger.warning(f"Rejected Sentry webhook with invalid signature from {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse Sentry webhook JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Process webhook through business logic
    processor = WebhookProcessor(db)

    try:
        alert = processor.process_sentry_webhook(payload)

        # Queue alert for async ML processing
        process_alert.delay(alert.id)
        logger.debug(f"Alert {alert.id} queued for processing")

        logger.info(f"Sentry webhook processed: alert_id={alert.id}")

        return {
            "status": "received",
            "alert_id": alert.id,
            "external_id": alert.external_id
        }

    except ValueError as e:
        logger.error(f"Invalid Sentry payload: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"Error processing Sentry webhook: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/pagerduty")
async def pagerduty_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Receive webhooks from PagerDuty.

    Placeholder for future implementation.
    PagerDuty webhook format differs from Datadog/Sentry.

    Returns:
        200: Webhook acknowledged (stub)
    """
    logger.info("PagerDuty webhook received (not yet implemented)")

    payload = await request.json()

    return {
        "status": "received",
        "note": "PagerDuty integration coming soon"
    }
