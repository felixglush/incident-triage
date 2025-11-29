"""
Integration tests for ML Service.

These tests require the ML service to be running (docker-compose up ml-service).
They test real HTTP calls to the inference endpoints.
"""
import os

import pytest
import requests

ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://localhost:8001")


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("SKIP_ML_INTEGRATION_TESTS") == "true",
    reason="ML service not available"
)
class TestMLServiceIntegration:
    """Integration tests with real ML service."""

    def test_ml_service_health(self):
        """Test ML service is running and healthy."""
        try:
            response = requests.get(f"{ML_SERVICE_URL}/health", timeout=5)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "ner_model_loaded" in data
        except requests.ConnectionError:
            pytest.skip("ML service not running - start with docker-compose up ml-service")

    def test_classify_real_critical_alert(self):
        """Test classification with real ML service for critical alerts."""
        try:
            response = requests.post(
                f"{ML_SERVICE_URL}/classify",
                json={
                    "text": "Critical: Payment processor down in production, 500 errors"
                },
                timeout=10
            )

            assert response.status_code == 200
            data = response.json()

            # Should classify as critical or error
            assert data["severity"] in ["critical", "error"]
            # Should identify payments team
            assert data["team"] in ["payments", "backend"]
            # Confidence should be reasonable
            assert 0.0 <= data["confidence"] <= 1.0

        except requests.ConnectionError:
            pytest.skip("ML service not running")

    def test_classify_real_database_alert(self):
        """Test classification identifying infrastructure team."""
        try:
            response = requests.post(
                f"{ML_SERVICE_URL}/classify",
                json={
                    "text": "PostgreSQL connection pool saturated, high latency on database queries"
                },
                timeout=10
            )

            assert response.status_code == 200
            data = response.json()

            # Should identify infrastructure team
            assert data["team"] == "infrastructure"
            # Should be warning or error
            assert data["severity"] in ["warning", "error"]

        except requests.ConnectionError:
            pytest.skip("ML service not running")

    def test_entity_extraction_real_alert(self):
        """Test entity extraction with real ML service."""
        try:
            response = requests.post(
                f"{ML_SERVICE_URL}/extract-entities",
                json={
                    "text": "api-gateway timeout in production us-east-1 returning 504 errors"
                },
                timeout=10
            )

            assert response.status_code == 200
            data = response.json()

            # Should extract environment
            assert data["environment"] == "production"

            # Should extract region
            assert data["region"] == "us-east-1"

            # Should extract error code
            assert data["error_code"] == "504"

            # Service name might be extracted
            if data["service_name"]:
                assert "api-gateway" in data["service_name"] or "gateway" in data["service_name"]

        except requests.ConnectionError:
            pytest.skip("ML service not running")

    def test_entity_extraction_multiple_patterns(self):
        """Test entity extraction with complex text."""
        try:
            response = requests.post(
                f"{ML_SERVICE_URL}/extract-entities",
                json={
                    "text": "pod/payment-service-7f9c8d5b4-xyz failing healthcheck in staging eu-west-1"
                },
                timeout=10
            )

            assert response.status_code == 200
            data = response.json()

            # Should extract service from k8s pod name
            assert data["service_name"] == "payment-service"

            # Should extract environment
            assert data["environment"] == "staging"

            # Should extract region
            assert data["region"] == "eu-west-1"

        except requests.ConnectionError:
            pytest.skip("ML service not running")

    def test_ml_service_performance(self):
        """Test ML service response time is acceptable."""
        try:
            import time

            start = time.time()
            response = requests.post(
                f"{ML_SERVICE_URL}/classify",
                json={
                    "text": "Test alert for performance measurement"
                },
                timeout=10
            )
            duration = time.time() - start

            assert response.status_code == 200

            # Should respond in under 1 second for rule-based classification
            assert duration < 1.0, f"ML service too slow: {duration:.2f}s"

        except requests.ConnectionError:
            pytest.skip("ML service not running")

    def test_end_to_end_alert_flow(self):
        """Test complete flow: classify + extract entities."""
        try:
            alert_text = "Database connection failed in production us-west-2 with error 500"

            # First classify
            classify_response = requests.post(
                f"{ML_SERVICE_URL}/classify",
                json={"text": alert_text},
                timeout=10
            )
            assert classify_response.status_code == 200
            classification = classify_response.json()

            # Should classify as error/critical for infrastructure
            assert classification["severity"] in ["error", "critical"]
            assert classification["team"] == "infrastructure"

            # Then extract entities
            entities_response = requests.post(
                f"{ML_SERVICE_URL}/extract-entities",
                json={"text": alert_text},
                timeout=10
            )
            assert entities_response.status_code == 200
            entities = entities_response.json()

            # Should extract environment and region
            assert entities["environment"] == "production"
            assert entities["region"] == "us-west-2"
            assert entities["error_code"] == "500"

        except requests.ConnectionError:
            pytest.skip("ML service not running")


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("SKIP_ML_INTEGRATION_TESTS") == "true",
    reason="ML service not available"
)
class TestMLServiceErrorHandling:
    """Test ML service error handling."""

    def test_classify_empty_text(self):
        """Test classification with empty text."""
        try:
            response = requests.post(
                f"{ML_SERVICE_URL}/classify",
                json={"text": ""},
                timeout=10
            )

            assert response.status_code == 200
            data = response.json()

            # Should return default values
            assert "severity" in data
            assert "team" in data
            assert "confidence" in data

        except requests.ConnectionError:
            pytest.skip("ML service not running")

    def test_classify_invalid_json(self):
        """Test classification with invalid JSON."""
        try:
            response = requests.post(
                f"{ML_SERVICE_URL}/classify",
                data="not json",
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            # Should return validation error
            assert response.status_code == 422

        except requests.ConnectionError:
            pytest.skip("ML service not running")

    def test_extract_entities_no_matches(self):
        """Test entity extraction with text containing no entities."""
        try:
            response = requests.post(
                f"{ML_SERVICE_URL}/extract-entities",
                json={"text": "Something went wrong somewhere"},
                timeout=10
            )

            assert response.status_code == 200
            data = response.json()

            # All fields should be None
            assert data.get("service_name") is None
            assert data.get("environment") is None
            assert data.get("region") is None
            assert data.get("error_code") is None

        except requests.ConnectionError:
            pytest.skip("ML service not running")
