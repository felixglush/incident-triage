"""
Database configuration and session management.

This module provides:
- SQLAlchemy engine with connection pooling
- Session factory for database operations
- Database initialization and migration helpers
- FastAPI dependency for request-scoped sessions
"""
import os
import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from typing import Generator

from app.models.database import Base

logger = logging.getLogger(__name__)

# Database connection settings
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/opsrelay"
)

# Engine configuration with production-ready settings
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,  # Number of persistent connections
    max_overflow=20,  # Max connections beyond pool_size
    pool_pre_ping=True,  # Test connection before using
    pool_recycle=3600,  # Recycle connections after 1 hour
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",  # Log SQL queries in dev
    future=True,  # Use SQLAlchemy 2.0 style
)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False  # Prevent lazy loading errors after commit
)


# Connection event listeners for monitoring
@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    """Log successful connections"""
    logger.debug("Database connection established")


@event.listens_for(engine, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """Log when connection is checked out from pool"""
    logger.debug("Connection checked out from pool")


def init_db():
    """
    Create all database tables.

    Note: In production, use Alembic migrations instead of this.
    This is useful for development and testing.
    """
    logger.info("Initializing database schema...")
    try:
        # Enable pgvector extension if available
        with engine.connect() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))  # For text search
                conn.commit()
                logger.info("PostgreSQL extensions enabled")
            except Exception as e:
                logger.warning(f"Could not enable extensions: {e}")
                conn.rollback()

        # Create all tables
        Base.metadata.create_all(bind=engine)
        logger.info("Database schema created successfully")

    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise


def drop_db():
    """
    Drop all database tables.
    WARNING: This will delete all data!
    Only use in development/testing.
    """
    logger.warning("Dropping all database tables...")
    Base.metadata.drop_all(bind=engine)
    logger.info("All tables dropped")


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session.

    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()

    The session is automatically closed after the request,
    even if an exception occurs.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context manager for database sessions outside of FastAPI requests.

    Usage:
        with get_db_context() as db:
            user = db.query(User).first()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        logger.error(f"Database context error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def check_connection() -> bool:
    """
    Test database connectivity.

    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection check: OK")
        return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False


# Initialize database on module import (optional - can be done explicitly)
# Uncomment the following line to auto-initialize in development
# init_db()
