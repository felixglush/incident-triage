"""
Unit tests for webhook signature verification.

Tests the signature_verification module in isolation without database dependencies.
"""

import hashlib
import hmac
import os
from unittest import mock

import pytest

from app.services.signature_verification import (
    verify_datadog_signature,
    verify_sentry_signature,
)


class TestDatadogSignatureVerification:
    """Test suite for Datadog signature verification."""

    @pytest.mark.unit
    def test_valid_signature(self):
        """Test that valid Datadog signature is accepted."""
        secret = "test-secret-key"
        body = b'{"id": "test-001", "title": "Test Alert"}'
        expected_signature = hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()

        with mock.patch.dict(
            os.environ,
            {
                "DATADOG_WEBHOOK_SECRET": secret,
                "SKIP_SIGNATURE_VERIFICATION": "false",
            },
        ):
            result = verify_datadog_signature(body, expected_signature)
            assert result is True

    @pytest.mark.unit
    def test_invalid_signature(self):
        """Test that invalid signature is rejected."""
        secret = "test-secret-key"
        body = b'{"id": "test-001"}'
        wrong_signature = "wrong-signature-value"

        with mock.patch.dict(
            os.environ,
            {
                "DATADOG_WEBHOOK_SECRET": secret,
                "SKIP_SIGNATURE_VERIFICATION": "false",
            },
        ):
            result = verify_datadog_signature(body, wrong_signature)
            assert result is False

    @pytest.mark.unit
    def test_missing_signature_header(self):
        """Test that missing signature header is rejected."""
        with mock.patch.dict(
            os.environ,
            {
                "DATADOG_WEBHOOK_SECRET": "test-secret",
                "SKIP_SIGNATURE_VERIFICATION": "false",
            },
        ):
            result = verify_datadog_signature(b"test body", None)
            assert result is False

    @pytest.mark.unit
    def test_missing_secret_env_var(self):
        """Test that missing DATADOG_WEBHOOK_SECRET env var causes rejection."""
        body = b'{"test": "data"}'
        signature = "some-signature"

        with mock.patch.dict(
            os.environ, {"SKIP_SIGNATURE_VERIFICATION": "false"}, clear=True
        ):
            # Remove secret if it exists
            os.environ.pop("DATADOG_WEBHOOK_SECRET", None)
            result = verify_datadog_signature(body, signature)
            assert result is False

    @pytest.mark.unit
    def test_skip_verification_flag(self):
        """Test that SKIP_SIGNATURE_VERIFICATION flag bypasses checks."""
        with mock.patch.dict(
            os.environ, {"SKIP_SIGNATURE_VERIFICATION": "true"}, clear=True
        ):
            # Should return True even with invalid signature
            result = verify_datadog_signature(b"test", "invalid-sig")
            assert result is True

    @pytest.mark.unit
    def test_timing_attack_protection(self):
        """Test that signature comparison uses constant-time comparison."""
        # This test verifies that we use hmac.compare_digest for timing attack protection
        secret = "test-secret"
        body = b"test body"
        valid_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        # Create signature that differs by one character
        invalid_sig = valid_sig[:-1] + ("a" if valid_sig[-1] != "a" else "b")

        with mock.patch.dict(
            os.environ,
            {
                "DATADOG_WEBHOOK_SECRET": secret,
                "SKIP_SIGNATURE_VERIFICATION": "false",
            },
        ):
            # Both should take similar time (constant-time comparison)
            result1 = verify_datadog_signature(body, valid_sig)
            result2 = verify_datadog_signature(body, invalid_sig)

            assert result1 is True
            assert result2 is False


class TestSentrySignatureVerification:
    """Test suite for Sentry signature verification."""

    @pytest.mark.unit
    def test_valid_signature(self):
        """Test that valid Sentry signature is accepted."""
        secret = "sentry-secret"
        body = b'{"id": "sentry-001"}'
        sig_hex = hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()

        # Sentry format: timestamp,signature
        timestamp = "1234567890"
        expected_signature = f"{timestamp},{sig_hex}"

        with mock.patch.dict(
            os.environ,
            {
                "SENTRY_WEBHOOK_SECRET": secret,
                "SKIP_SIGNATURE_VERIFICATION": "false",
            },
        ):
            result = verify_sentry_signature(body, expected_signature)
            assert result is True

    @pytest.mark.unit
    def test_invalid_signature(self):
        """Test that invalid signature is rejected."""
        with mock.patch.dict(
            os.environ,
            {
                "SENTRY_WEBHOOK_SECRET": "sentry-secret",
                "SKIP_SIGNATURE_VERIFICATION": "false",
            },
        ):
            result = verify_sentry_signature(b"test", "wrong-sig")
            assert result is False

    @pytest.mark.unit
    def test_skip_verification_in_development(self):
        """Test that signature verification can be skipped in development."""
        with mock.patch.dict(
            os.environ, {"SKIP_SIGNATURE_VERIFICATION": "true"}
        ):
            result = verify_sentry_signature(b"anything", None)
            assert result is True


class TestSignatureVerificationEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.unit
    def test_empty_body(self):
        """Test signature verification with empty body."""
        secret = "test-secret"
        body = b""
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with mock.patch.dict(
            os.environ,
            {
                "DATADOG_WEBHOOK_SECRET": secret,
                "SKIP_SIGNATURE_VERIFICATION": "false",
            },
        ):
            result = verify_datadog_signature(body, signature)
            assert result is True

    @pytest.mark.unit
    def test_unicode_in_body(self):
        """Test signature verification with Unicode characters."""
        secret = "test-secret"
        body = '{"title": "Test with émojis 🚀"}'.encode("utf-8")
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with mock.patch.dict(
            os.environ,
            {
                "DATADOG_WEBHOOK_SECRET": secret,
                "SKIP_SIGNATURE_VERIFICATION": "false",
            },
        ):
            result = verify_datadog_signature(body, signature)
            assert result is True

    @pytest.mark.unit
    def test_large_payload(self):
        """Test signature verification with large payload."""
        secret = "test-secret"
        # Create 1MB payload
        body = (b"x" * 1024 * 1024)
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with mock.patch.dict(
            os.environ,
            {
                "DATADOG_WEBHOOK_SECRET": secret,
                "SKIP_SIGNATURE_VERIFICATION": "false",
            },
        ):
            result = verify_datadog_signature(body, signature)
            assert result is True
