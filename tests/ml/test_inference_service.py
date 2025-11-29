"""
Unit tests for ML Inference Service.

Tests the classification and entity extraction endpoints without requiring
the actual NER model to be loaded.
"""
import pytest
from fastapi.testclient import TestClient
from unittest import mock

# Mock the transformers pipeline before importing the app
with mock.patch('ml.inference_server.pipeline'):
    from ml.inference_server import app

client = TestClient(app)


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check_returns_healthy(self):
        """Test health endpoint returns healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "ner_model_loaded" in data


class TestClassificationEndpoint:
    """Test /classify endpoint with rule-based classification."""

    def test_classify_critical_severity(self):
        """Test classification of critical severity alerts."""
        test_cases = [
            "Database is down, all connections failed",
            "Service crashed in production",
            "Critical outage affecting all users",
            "System offline - urgent attention needed"
        ]

        for text in test_cases:
            response = client.post("/classify", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["severity"] == "critical"
            assert data["confidence"] >= 0.8
            assert "team" in data

    def test_classify_error_severity(self):
        """Test classification of error severity alerts."""
        test_cases = [
            "API request failed with exception",
            "Timeout error connecting to database",
            "Fatal error in payment processor",
            "Connection failure detected"
        ]

        for text in test_cases:
            response = client.post("/classify", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["severity"] == "error"
            assert data["confidence"] >= 0.7

    def test_classify_warning_severity(self):
        """Test classification of warning severity alerts."""
        test_cases = [
            "High CPU usage detected on server",
            "Slow response time warning",
            "Degraded performance on API",
            "High latency warning"
        ]

        for text in test_cases:
            response = client.post("/classify", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["severity"] == "warning"
            assert data["confidence"] >= 0.6

    def test_classify_info_severity_default(self):
        """Test that unknown patterns default to info."""
        response = client.post(
            "/classify",
            json={"text": "Normal operational message"}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["severity"] == "info"
        assert data["team"] is not None

    def test_classify_infrastructure_team(self):
        """Test team assignment for infrastructure alerts."""
        test_cases = [
            "PostgreSQL connection pool saturated",
            "Redis cache memory limit reached",
            "High disk usage on database server",
            "CPU spike on memcached cluster"
        ]

        for text in test_cases:
            response = client.post("/classify", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["team"] == "infrastructure"
            assert data["confidence"] >= 0.7

    def test_classify_payments_team(self):
        """Test team assignment for payment alerts."""
        test_cases = [
            "Payment processing failed",
            "Stripe transaction timeout",
            "Checkout service unavailable",
            "Billing system error"
        ]

        for text in test_cases:
            response = client.post("/classify", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["team"] == "payments"
            assert data["confidence"] >= 0.8

    def test_classify_frontend_team(self):
        """Test team assignment for frontend alerts."""
        test_cases = [
            "React component rendering error",
            "Frontend UI performance degraded",
            "Browser client-side exception"
        ]

        for text in test_cases:
            response = client.post("/classify", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["team"] == "frontend"

    def test_classify_backend_team_default(self):
        """Test that unknown patterns default to backend team."""
        response = client.post(
            "/classify",
            json={"text": "General application error"}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["team"] == "backend"

    def test_classify_empty_text(self):
        """Test handling of empty input."""
        response = client.post("/classify", json={"text": ""})

        assert response.status_code == 200
        data = response.json()

        # Should return default values
        assert data["severity"] == "info"
        assert data["team"] == "backend"
        assert data["confidence"] >= 0.0

    def test_classify_response_structure(self):
        """Test that response has correct structure."""
        response = client.post(
            "/classify",
            json={"text": "Test alert message"}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify all required fields present
        assert "severity" in data
        assert "team" in data
        assert "confidence" in data

        # Verify types
        assert isinstance(data["severity"], str)
        assert isinstance(data["team"], str)
        assert isinstance(data["confidence"], float)

        # Verify ranges
        assert 0.0 <= data["confidence"] <= 1.0


class TestEntityExtractionEndpoint:
    """Test /extract-entities endpoint."""

    def test_extract_production_environment(self):
        """Test environment extraction for production."""
        test_cases = [
            ("API service failing in production environment", "production"),
            ("Error in prod database", "production"),
            ("Issue detected in production", "production")
        ]

        for text, expected_env in test_cases:
            response = client.post("/extract-entities", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["environment"] == expected_env

    def test_extract_staging_environment(self):
        """Test environment extraction for staging."""
        test_cases = [
            ("Deploy failed in staging", "staging"),
            ("Stage server not responding", "staging")
        ]

        for text, expected_env in test_cases:
            response = client.post("/extract-entities", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["environment"] == expected_env

    def test_extract_development_environment(self):
        """Test environment extraction for development."""
        response = client.post(
            "/extract-entities",
            json={"text": "Bug in development environment"}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["environment"] == "development"

    def test_extract_aws_region(self):
        """Test AWS region extraction."""
        test_cases = [
            ("High latency in us-east-1 region", "us-east-1"),
            ("Service down in us-west-2", "us-west-2"),
            ("EU-WEST-1 availability zone failure", "eu-west-1")
        ]

        for text, expected_region in test_cases:
            response = client.post("/extract-entities", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["region"] == expected_region

    def test_extract_service_name_with_dash(self):
        """Test service name extraction for hyphenated services."""
        test_cases = [
            "api-service timeout",
            "web-service not responding",
            "payment-service error"
        ]

        for text in test_cases:
            response = client.post("/extract-entities", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["service_name"] is not None
            assert "-service" in data["service_name"]

    def test_extract_service_name_kubernetes(self):
        """Test service name extraction from Kubernetes pod names."""
        response = client.post(
            "/extract-entities",
            json={"text": "pod/api-gateway-7f9c8d5b4-xyz failed healthcheck"}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["service_name"] == "api-gateway"

    def test_extract_http_error_code(self):
        """Test HTTP error code extraction."""
        test_cases = [
            ("API returning 500 errors", "500"),
            ("Received 404 status code", "404"),
            ("503 service unavailable", "503")
        ]

        for text, expected_code in test_cases:
            response = client.post("/extract-entities", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["error_code"] == expected_code

    def test_extract_multiple_entities(self):
        """Test extraction of multiple entities from single text."""
        response = client.post(
            "/extract-entities",
            json={
                "text": "api-gateway service down in production us-west-2 returning 503 errors"
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Should extract all entities
        assert data["service_name"] == "api-gateway"
        assert data["environment"] == "production"
        assert data["region"] == "us-west-2"
        assert data["error_code"] == "503"

    def test_extract_entities_no_matches(self):
        """Test that missing entities return None."""
        response = client.post(
            "/extract-entities",
            json={"text": "Something went wrong"}
        )

        assert response.status_code == 200
        data = response.json()

        # All fields should be None or not present
        assert data.get("service_name") is None
        assert data.get("environment") is None
        assert data.get("region") is None
        assert data.get("error_code") is None

    def test_extract_entities_response_structure(self):
        """Test that response has correct structure."""
        response = client.post(
            "/extract-entities",
            json={"text": "Test message"}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify all expected fields present (even if None)
        assert "service_name" in data
        assert "environment" in data
        assert "region" in data
        assert "error_code" in data


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_classify_with_very_long_text(self):
        """Test classification with very long text."""
        long_text = "Error " * 1000

        response = client.post("/classify", json={"text": long_text})

        assert response.status_code == 200
        data = response.json()

        assert data["severity"] == "error"
        assert data["confidence"] > 0.0

    def test_classify_with_special_characters(self):
        """Test classification with special characters."""
        response = client.post(
            "/classify",
            json={"text": "Error: [@#$%^&*] <critical> {failure}"}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["severity"] in ["critical", "error"]

    def test_extract_entities_case_insensitive(self):
        """Test that entity extraction is case insensitive."""
        test_cases = [
            "PRODUCTION environment",
            "Production Environment",
            "production environment"
        ]

        for text in test_cases:
            response = client.post("/extract-entities", json={"text": text})

            assert response.status_code == 200
            data = response.json()

            assert data["environment"] == "production"

    def test_missing_text_field(self):
        """Test that missing text field returns validation error."""
        response = client.post("/classify", json={})

        # FastAPI validation error
        assert response.status_code == 422

    def test_invalid_json(self):
        """Test that invalid JSON returns error."""
        response = client.post(
            "/classify",
            data="not json",
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 422
