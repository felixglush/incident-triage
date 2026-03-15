"""
OpsRelay Backend API - Main application

FastAPI application with proper lifespan management for:
- Database connection pool warmup
- Health checks on startup
- Graceful shutdown handling

Architecture:
- main.py: Route registration and app configuration
- app/api/: API routers (webhooks, incidents, chat)
- app/services/: Business logic
- app/models/: Database models
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import check_connection
from app.api import webhooks
from app.api import incidents, alerts, dashboard, runbooks, connectors
from app.api import chat

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler

    Startup:
    - Check database connectivity
    - Warm up connection pool
    - Log startup completion

    Shutdown:
    - Cleanup resources
    - Log shutdown
    """
    # Startup
    logger.info("Starting OpsRelay API...")

    # Check database connectivity (don't create schema - use init_db.py separately)
    if not check_connection():
        logger.error("Database connection failed! Please run init_db.py first.")
        # In production, you might want to raise an exception here
        # For development, we'll continue to allow health check to work
    else:
        logger.info("Database connection verified")

    logger.info("OpsRelay API started successfully")

    yield  # Application runs

    # Shutdown
    logger.info("Shutting down OpsRelay API...")
    # Add cleanup here if needed (close connections, etc)
    logger.info("OpsRelay API shutdown complete")


app = FastAPI(
    title="OpsRelay API",
    description="AI-powered incident management system",
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # frontend dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(webhooks.router, prefix="/webhook", tags=["webhooks"])
app.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(runbooks.router, prefix="/runbooks", tags=["runbooks"])
app.include_router(connectors.router, prefix="/connectors", tags=["connectors"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])


@app.get("/health")
async def health():
    """
    Health check endpoint for load balancers and monitoring.

    Returns:
    - status: "healthy" if app is running
    - db_connected: True if database is reachable
    """
    db_connected = check_connection()

    return {
        "status": "healthy" if db_connected else "degraded",
        "db_connected": db_connected
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "OpsRelay API",
        "status": "running",
        "version": "0.1.0",
        "docs": "/docs"
    }


# Stub endpoints removed; use routers instead.
