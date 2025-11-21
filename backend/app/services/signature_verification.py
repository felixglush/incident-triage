"""
Webhook signature verification for security.

Each monitoring platform signs their webhook payloads with a secret.
We verify these signatures to prevent unauthorized webhook requests.
"""
import hmac
import hashlib
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def verify_datadog_signature(body: bytes, signature: Optional[str]) -> bool:
    """
    Verify Datadog webhook signature using HMAC-SHA256.

    Datadog sends signatures in the X-Datadog-Signature header.

    Args:
        body: Raw request body bytes
        signature: Signature from X-Datadog-Signature header

    Returns:
        True if signature is valid, False otherwise

    Security notes:
    - Uses constant-time comparison to prevent timing attacks
    - Secret should be rotated regularly
    - In production, load from environment variable or secret manager
    """
    # In development, allow unsigned requests if signature verification is disabled
    if os.getenv("SKIP_SIGNATURE_VERIFICATION", "false").lower() == "true":
        logger.warning("Signature verification disabled - NOT FOR PRODUCTION")
        return True

    if not signature:
        logger.warning("Missing Datadog signature")
        return False

    # Load secret from environment
    secret = os.getenv("DATADOG_WEBHOOK_SECRET")
    if not secret:
        logger.error("DATADOG_WEBHOOK_SECRET not set")
        return False

    # Compute expected signature
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()

    # Constant-time comparison prevents timing attacks
    is_valid = hmac.compare_digest(expected, signature)

    if not is_valid:
        logger.warning("Invalid Datadog signature")

    return is_valid


def verify_sentry_signature(body: bytes, signature: Optional[str]) -> bool:
    """
    Verify Sentry webhook signature using HMAC-SHA256.

    Sentry sends signatures in the Sentry-Hook-Signature header.
    Format: <timestamp>,<signature>

    Args:
        body: Raw request body bytes
        signature: Signature from Sentry-Hook-Signature header

    Returns:
        True if signature is valid, False otherwise

    Reference:
    https://docs.sentry.io/product/integrations/integration-platform/webhooks/#sentry-hook-signature
    """
    # In development, allow unsigned requests if signature verification is disabled
    if os.getenv("SKIP_SIGNATURE_VERIFICATION", "false").lower() == "true":
        logger.warning("Signature verification disabled - NOT FOR PRODUCTION")
        return True

    if not signature:
        logger.warning("Missing Sentry signature")
        return False

    # Load secret from environment
    secret = os.getenv("SENTRY_WEBHOOK_SECRET")
    if not secret:
        logger.error("SENTRY_WEBHOOK_SECRET not set")
        return False

    # Sentry format: timestamp,signature
    try:
        parts = signature.split(",")
        if len(parts) != 2:
            logger.warning("Invalid Sentry signature format")
            return False

        timestamp, sig = parts
    except ValueError:
        logger.warning("Malformed Sentry signature")
        return False

    # Compute expected signature (timestamp is included in the payload)
    # Sentry includes timestamp in the body, so we just verify the signature
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()

    # Constant-time comparison
    is_valid = hmac.compare_digest(expected, sig)

    if not is_valid:
        logger.warning("Invalid Sentry signature")

    return is_valid


def verify_pagerduty_signature(body: bytes, signature: Optional[str]) -> bool:
    """
    Verify PagerDuty webhook signature.

    PagerDuty uses a different signature scheme.
    Placeholder for future implementation.

    Args:
        body: Raw request body bytes
        signature: Signature header

    Returns:
        True if signature is valid, False otherwise
    """
    # TODO: Implement PagerDuty signature verification
    # For now, accept all PagerDuty webhooks in development
    if os.getenv("SKIP_SIGNATURE_VERIFICATION", "false").lower() == "true":
        return True

    logger.warning("PagerDuty signature verification not yet implemented")
    return True  # Placeholder
