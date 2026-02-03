# Architecture & Data Flow

## System Overview
OpsRelay ingests monitoring alerts, groups them into incidents, enriches them
with ML classification and entity extraction, and provides a retrieval-based
assistant to summarize context and recommend next steps.

## Data Flow
```mermaid
flowchart TD
  MP["Monitoring Platforms"] --> WH["Webhook API"]
  WH --> AT["Alerts Table"]
  AT --> CW["Celery Worker"]
  CW --> ML["ML Service (Classify + NER)"]
  CW --> IT["Incidents Table"]
  RD["Runbooks/Docs"] --> CI["Connector Ingestion"]
  CI --> RC["Runbook Chunks"]
  IT --> SS["Similarity Search (pgvector)"]
  RC --> SS
  SS --> SC["Summarizer/Chat"]
  SC --> UI["Dashboard + Chat UI"]
```

## System Diagram
```mermaid
flowchart LR
  subgraph Sources
    DD["Datadog"]
    SE["Sentry"]
    PD["PagerDuty (Future)"]
  end

  subgraph Backend
    FA["FastAPI Webhooks"]
    PG["PostgreSQL + pgvector"]
    CW2["Celery Workers"]
  end

  subgraph ML
    CL["Classification"]
    EE["Entity Extraction (Regex + NER)"]
  end

  subgraph Retrieval
    RB["Runbook Chunks"]
    IE["Incident Embeddings"]
    SS2["Similarity Search"]
  end

  subgraph UI
    ID["Incidents Dashboard"]
    CI2["Chat Interface"]
  end

  Sources --> FA
  FA --> PG
  FA --> CW2
  CW2 --> CL
  CW2 --> EE
  CL --> PG
  EE --> PG

  PG --> IE
  RB --> SS2
  IE --> SS2
  SS2 --> CI2
  SS2 --> ID
```

## Core Components
- Webhook API: Receives alerts, verifies signatures, stores raw payloads.
- Database: PostgreSQL + pgvector; primary store for alerts/incidents/chunks.
- Celery Workers: Async classification, entity extraction, grouping.
- ML Service: Rule-based classification, regex extraction, NER fallback.
- Retrieval Layer: Vector similarity for past incidents/runbooks.
- Summarizer: Builds context and suggests next steps.
- Dashboard + Chat: Operator UI for review and triage.

## Key Data Models
- Alert: Raw payload, ML outputs, extracted entities.
- Incident: Grouped alerts, status, summary, suggested actions.
- RunbookChunk: Document segments for retrieval.

## Scaling & Reliability Notes
- Webhook endpoints must respond quickly (<2s), async for heavy work.
- ML calls should degrade gracefully with safe defaults.
- Provenance should be stored for classification/entity extraction.
