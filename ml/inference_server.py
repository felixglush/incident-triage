"""
ML Inference Service for OpsRelay
Provides classification and entity extraction for alerts
"""
import logging
import re
import time
from typing import Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel
from transformers import pipeline

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ML Inference Service", version="2.0.0")

# Global model variable
ner_model = None


# Pydantic models
class ClassificationRequest(BaseModel):
    text: str


class ClassificationResponse(BaseModel):
    severity: str
    team: str
    confidence: float


class NERRequest(BaseModel):
    text: str


class EntityResponse(BaseModel):
    service_name: Optional[str] = None
    environment: Optional[str] = None
    region: Optional[str] = None
    error_code: Optional[str] = None


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests with duration and status"""
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    logger.info(
        f"{request.method} {request.url.path} - "
        f"Status: {response.status_code} - "
        f"Duration: {duration:.3f}s"
    )
    return response


# Startup event - load models
@app.on_event("startup")
async def load_models():
    """Load ML models at startup"""
    global ner_model

    logger.info("Loading BERT NER model...")
    try:
        ner_model = pipeline(
            "ner",
            model="dslim/bert-base-NER",
            device=-1  # CPU
        )
        logger.info("✓ NER model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load NER model: {e}")
        logger.warning("NER model unavailable - will use regex-only extraction")


# Health check
@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "ner_model_loaded": ner_model is not None
    }


# Classification endpoint
@app.post("/classify", response_model=ClassificationResponse)
async def classify_alert(request: ClassificationRequest):
    """
    Classify alert severity and team using rule-based heuristics.

    Severity Rules:
    - CRITICAL: System down, outages, critical failures
    - ERROR: Errors, failures, exceptions, timeouts
    - WARNING: High usage, slow performance, degraded service
    - INFO: Everything else

    Team Assignment:
    - infrastructure: Database, cache, system resources
    - payments: Payment processing, transactions
    - frontend: UI, client-side issues
    - backend: Default for application services
    """
    text_lower = request.text.lower()

    logger.debug(f"Classifying text: {request.text[:100]}...")

    # Severity classification
    severity, severity_confidence = _classify_severity(text_lower)

    # Team assignment
    team, team_confidence = _classify_team(text_lower)

    # Overall confidence is average of both
    confidence = (severity_confidence + team_confidence) / 2

    logger.info(
        f"Classification result: severity={severity}, team={team}, "
        f"confidence={confidence:.2f}"
    )

    return ClassificationResponse(
        severity=severity,
        team=team,
        confidence=confidence
    )


def _classify_severity(text: str) -> tuple[str, float]:
    """
    Classify severity with confidence score.
    NOTE: naive, placeholder for now.
    """
    # Critical keywords
    critical_keywords = ["down", "outage", "critical", "crashed", "offline", "unavailable"]
    if any(keyword in text for keyword in critical_keywords):
        return "critical", 0.9

    # Error keywords
    error_keywords = ["error", "failed", "failure", "exception", "timeout", "fatal"]
    if any(keyword in text for keyword in error_keywords):
        return "error", 0.85

    # Warning keywords
    warning_keywords = ["warning", "high", "slow", "degraded", "latency", "delayed"]
    if any(keyword in text for keyword in warning_keywords):
        return "warning", 0.8

    # Default to info
    return "info", 0.5


def _classify_team(text: str) -> tuple[str, float]:
    """
    Classify team with confidence score
    NOTE: naive, placeholder for now.
    """
    # Infrastructure keywords
    infra_keywords = [
        "database", "postgres", "postgresql", "mysql", "redis", "memcached",
        "disk", "cpu", "memory", "storage", "cache", "dns"
    ]
    if any(keyword in text for keyword in infra_keywords):
        return "infrastructure", 0.9

    # Payments keywords
    payment_keywords = ["payment", "transaction", "stripe", "checkout", "billing"]
    if any(keyword in text for keyword in payment_keywords):
        return "payments", 0.9

    # Frontend keywords
    frontend_keywords = ["ui", "frontend", "react", "next.js", "browser", "client"]
    if any(keyword in text for keyword in frontend_keywords):
        return "frontend", 0.85

    # Default to backend
    return "backend", 0.6


# Entity extraction endpoint
@app.post("/extract-entities", response_model=EntityResponse)
async def extract_entities(request: NERRequest):
    """
    Extract entities using hybrid approach: regex (fast) + NER (fallback).

    Entities Extracted:
    - Environment: production, staging, dev
    - Region: AWS/GCP/Azure region codes
    - Service: Service names from text
    - Error codes: HTTP status codes, application errors
    """
    text = request.text

    logger.debug(f"Extracting entities from: {text[:100]}...")

    # Extract using regex patterns (fast, deterministic)
    entities = {
        "environment": _extract_environment(text),
        "region": _extract_region(text),
        "service_name": _extract_service_name(text),
        "error_code": _extract_error_code(text)
    }

    # If service name not found via regex, try NER model
    if not entities["service_name"] and ner_model is not None:
        entities["service_name"] = _extract_service_with_ner(text)

    logger.debug(f"Extracted entities: {entities}")

    return EntityResponse(**entities)


def _extract_environment(text: str) -> Optional[str]:
    """Extract environment using regex"""
    pattern = r'\b(production|prod|staging|stage|dev|development)\b'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        env = match.group(1).lower()
        # Normalize to standard names
        if env in ["prod"]:
            return "production"
        elif env in ["stage"]:
            return "staging"
        elif env in ["dev"]:
            return "development"
        return env

    return None


def _extract_region(text: str) -> Optional[str]:
    """Extract cloud region using regex"""
    # AWS regions
    aws_pattern = r'\b(us-east-1|us-east-2|us-west-1|us-west-2|eu-west-1|eu-west-2|eu-central-1|ap-southeast-1|ap-southeast-2|ap-northeast-1)\b'
    match = re.search(aws_pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).lower()

    # GCP regions
    gcp_pattern = r'\b(us-central1|us-east1|us-west1|europe-west1|asia-east1)\b'
    match = re.search(gcp_pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).lower()

    return None


def _extract_service_name(text: str) -> Optional[str]:
    """Extract service name using regex patterns"""
    # Pattern 1: service-name format (common in k8s, microservices)
    pattern1 = r'\b([\w-]+)-service\b'
    match = re.search(pattern1, text, re.IGNORECASE)
    if match:
        return match.group(0).lower()

    # Pattern 2: service_name format
    pattern2 = r'\b([\w]+)_service\b'
    match = re.search(pattern2, text, re.IGNORECASE)
    if match:
        return match.group(0).lower()

    # Pattern 3: Kubernetes pod names (pod/service-name-hash)
    k8s_pattern = r'pod/([\w-]+)-[a-f0-9]+'
    match = re.search(k8s_pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).lower()

    # Pattern 4: Common service prefixes
    prefix_pattern = r'\b(api|web|worker|db|cache|queue|scheduler)[-_]?([\w]+)\b'
    match = re.search(prefix_pattern, text, re.IGNORECASE)
    if match:
        return match.group(0).lower()

    return None


def _extract_service_with_ner(text: str) -> Optional[str]:
    """Extract service name using NER model as fallback"""
    try:
        entities = ner_model(text)

        # Look for organization names (often service names in ops context)
        for entity in entities:
            if entity.get("entity", "").startswith("B-ORG"):
                return entity["word"].lower()

    except Exception as e:
        logger.error(f"NER extraction failed: {e}")

    return None


def _extract_error_code(text: str) -> Optional[str]:
    """Extract error codes (HTTP status, app errors)"""
    # HTTP status codes (4xx, 5xx)
    http_pattern = r'\b([45]\d{2})\b'
    match = re.search(http_pattern, text)
    if match:
        return match.group(1)

    # Application error codes (e.g., ERR-1234, ERROR_CODE_123)
    app_error_pattern = r'\b(ERR[-_]?\d+|ERROR[-_]?CODE[-_]?\d+)\b'
    match = re.search(app_error_pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
