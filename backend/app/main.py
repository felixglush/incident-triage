"""OpsRelay Backend API - Main application stub"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(
    title="OpsRelay API",
    description="AI-powered incident management system",
    version="0.1.0"
)


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "OpsRelay API",
        "status": "running"
    }


# Webhook endpoints will go here
@app.post("/webhook/datadog")
async def datadog_webhook():
    """Datadog webhook endpoint - stub"""
    return {"status": "received"}


@app.post("/webhook/sentry")
async def sentry_webhook():
    """Sentry webhook endpoint - stub"""
    return {"status": "received"}


# Alert endpoints
@app.get("/alerts")
async def list_alerts():
    """List all alerts - stub"""
    return {"alerts": []}


# Incident endpoints
@app.get("/incidents")
async def list_incidents():
    """List all incidents - stub"""
    return {"incidents": []}
