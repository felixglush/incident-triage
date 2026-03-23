# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

When exiting plan mode to begin implementation, ALWAYS save the implementation plan first as a markdown file in @docs/


## Project Overview

**OpsRelay** is an AI-powered incident management system that automatically triages alerts from monitoring platforms (Datadog, Sentry, etc.), groups them into incidents, and provides intelligent assistance to on-call engineers through RAG-based copilot features.

## Project Status

This is a portfolio project currently in development. Development follows phased delivery detailed in [implementation.md](implementation.md) and [ROADMAP.md](ROADMAP.md). Architecture is summarized in [docs/architecture.md](docs/architecture.md).

## Technology Stack

**Backend:**
- FastAPI (async API server)
- PostgreSQL (primary database)
- Celery + Redis (async task queue)
- SQLAlchemy (ORM)

**Machine Learning:**
- Transformers library (DistilBERT for classification, BERT for NER)
- Sentence Transformers (all-MiniLM-L6-v2 for embeddings)
- Anthropic Claude API (RAG and summarization)
- pgvector extension (vector similarity search)

**Frontend:**
- Next.js with React
- TypeScript
- Tailwind CSS

**Infrastructure:**
- Docker & Docker Compose
- Python 3.11+
- Node.js 18+

## Architecture Overview

### Data Flow

1. **Alert Ingestion**: Monitoring platforms send webhooks to `/webhook/{platform}` endpoints
2. **Webhook Handler**: FastAPI validates signatures, deduplicates, stores alert in PostgreSQL, queues for async processing
3. **Worker Processing**: Celery worker calls ML inference service for classification and entity extraction
4. **Incident Grouping**: Alerts are grouped into incidents based on timing, similarity, and extracted entities
5. **Summarization**: When incidents reach thresholds, ML generates summaries
6. **RAG Copilot**: Users query runbook knowledge base via semantic search + LLM synthesis

### Key Components

**Webhook Endpoints** (`backend/app/api/webhooks.py`):
- Accept alerts from Datadog, Sentry, etc.
- Verify signatures for security
- Return quickly (async processing via Celery)
- Handle duplicate detection via `external_id`

**ML Inference Service** (`ml/inference_server.py`):
- Separate FastAPI service for ML operations
- Classification endpoint for severity and team assignment
- Entity extraction endpoint for services, regions, environments
- Can start with rule-based heuristics before fine-tuning models

**Celery Workers** (`backend/app/workers/tasks.py`):
- `process_alert` task: orchestrates ML classification and grouping
- Defensive error handling (graceful degradation if ML fails)
- Calls ML service via HTTP, updates database with results

**RAG System** (`backend/app/api/chat.py`):
- Embeds user questions using sentence-transformers
- Performs vector similarity search via pgvector
- Sends top-k chunks + question to Claude for answer synthesis
- Returns answer with source citations

## Database Schema

**alerts** table:
- Stores raw webhook payloads in `raw_payload` JSON column
- ML predictions: `severity`, `predicted_team`, `confidence_score`
- Extracted entities: `service_name`, `environment`, `region`, `error_code`
- Foreign key to incidents table for grouping

**incidents** table:
- Aggregates related alerts
- Contains ML-generated `summary` field
- Tracks `status` (open, investigating, resolved)
- JSON array of `affected_services`

**runbook_chunks** table:
- Stores documentation segments for RAG
- `embedding` column (Vector type with pgvector)
- Links to `source_document` for citations

**incident_actions** table:
- Timeline of actions during incident response
- Captures status changes, comments, alert additions

## Development Commands

### Running Services

```bash
# Start all services with Docker Compose
docker-compose up

# Backend API runs on port 8000
# PostgreSQL on port 5432
# Redis on port 6379
```

### Running Celery Workers

```bash
cd backend
source venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info
```

### Database Initialization

```bash
# Run from Python shell or create migration script
from app.database import init_db
init_db()
```

### ML Service

```bash
cd ml
uvicorn inference_server:app --host 0.0.0.0 --port 8001
```

### Frontend Development

```bash
cd frontend
npm install
npm run dev
# Runs on port 3000
```

### Generate Sample Data

```bash
python datasets/generate_alerts.py
python datasets/generate_runbooks.py
```

### Generate Embeddings

```bash
cd ml
python generate_embeddings.py
```

## Development Phases

**Phase 1 (Weeks 1-3)**: Foundation
- Docker infrastructure setup
- Database schema and migrations
- FastAPI webhook endpoints
- Basic Celery worker structure
- Sample data generation
- Goal: Alerts flowing from webhook → database → API

**Phase 2 (Weeks 4-7)**: ML Intelligence
- ML inference service with classification models
- Entity extraction via NER
- RAG system implementation (embeddings + vector search)
- Incident summarization
- Goal: Intelligent triage and copilot assistance

**Phase 3 (Weeks 8-12)**: UX and Integration
- Next.js dashboard
- Slack integration for notifications
- Polish and demo mode
- Goal: Production-ready demo

## Important Design Patterns

### Async Processing
- Webhooks must respond quickly (<2s) to avoid timeouts
- All ML processing happens asynchronously via Celery
- Use `process_alert.delay(alert_id)` pattern

### Error Handling
- ML service calls wrapped in try-except with fallback values
- System gracefully degrades when components fail
- Never lose alerts due to ML failures

### Security
- Verify webhook signatures from monitoring platforms
- Use environment variables for all secrets
- Never commit API keys or credentials

### Data Preservation
- Store complete `raw_payload` from webhooks for debugging
- Separate `created_at` (received time) from `alert_timestamp` (occurred time)
- Track confidence scores for ML predictions

## Configuration

Environment variables (set in `.env` file, never commit):

```
DATABASE_URL=postgresql://opsrelay:password@localhost:5432/opsrelay
REDIS_URL=redis://localhost:6379/0
ML_SERVICE_URL=http://localhost:8001
ANTHROPIC_API_KEY=sk-ant-...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

## Testing Strategy

- Use sample webhook payloads for endpoint testing
- Validate classification accuracy on labeled test set
- Test RAG quality with predefined questions
- Verify incident grouping logic with time-series scenarios
- End-to-end tests from webhook to incident creation

## Common Pitfalls

- **N+1 queries**: Eagerly load related alerts when fetching incidents
- **Memory leaks**: Always close database sessions in workers (use try-finally)
- **Webhook timeouts**: Never do synchronous ML inference in webhook handlers
- **Duplicate alerts**: Always check `external_id` before creating new alerts
- **Vector dimensions**: Ensure embedding dimension (384) matches model output

## Production Considerations

The implementation guide notes these are for demo/portfolio purposes:
- Signature verification is stubbed initially
- Start with rule-based classification before fine-tuning
- Can use local summarization models instead of API for cost savings
- pgvector is simpler than dedicated vector DB for moderate scale

## Key Files to Reference

- [implementation.md](implementation.md): Comprehensive build guide with code examples
- README.md: Basic project description
- `.gitignore`: Excludes models, data, secrets, node_modules

## Project Goals

This is a **portfolio project** designed to demonstrate:
- Modern ML operations (classification, NER, RAG, summarization)
- Distributed systems (async workers, message queues)
- REST API design with FastAPI
- Production-ready patterns (error handling, logging, monitoring)
- Full-stack development (backend + frontend)
