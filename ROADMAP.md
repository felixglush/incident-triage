# OpsRelay Roadmap

This roadmap mirrors Linear milestones in the "OpsRelay Roadmap" project.

## Phase 0 — Baseline & Docs
Exit criteria:
- implementation.md and ROADMAP.md exist and match scope
- tests/README.md reflects actual tests
- docs/architecture.md documents data flow and components

## Phase 1 — Incident Review + Webhooks
Exit criteria:
- Incidents API supports list/detail/status
- Filters + pagination available for review
- Webhook ingestion verified end-to-end with tests
- Seed data scripts for demo browsing

## Phase 2 — Classification + Entity Extraction
Exit criteria:
- Classification has provenance + confidence
- Entity extraction uses heuristics + NER fallback
- Fixtures and tests for extraction accuracy

## Phase 3 — Pairing + Summaries
Exit criteria:
- Embeddings stored and queried via pgvector
- Similarity search returns relevant prior incidents
- Summaries include retrieved context + citations
- Next-step suggestions stored on incidents

## Phase 4 — Dashboard + Chat UI
Exit criteria:
- Dashboard shell and routing
- Incident list/detail views in UI
- Chat interface wired to backend
- Similar incidents and suggestions shown

## Phase 5 — Connectors
Exit criteria:
- Connector interface + auth flow
- Notion, Linear, Slack ingestion paths implemented

## Phase 6 — Simulation + Demo Mode
Exit criteria:
- Fake data generator for all sources
- Demo mode toggle + seed scripts
- Alert replay + demo walkthrough
