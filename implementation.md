# Implementation Plan — OpsRelay

This document describes the progressive delivery plan for OpsRelay. It is
intended to stay in sync with Linear milestones and the ROADMAP.

## Phase 0 — Baseline & Docs
Goal: Align documentation with reality and establish a clear plan.
- Create/restore roadmap and implementation docs
- Add architecture and data-flow docs
- Reconcile test documentation with actual tests
- Update README/CLAUDE references

## Phase 1 — Incident Review + Webhooks
Goal: Review past incidents and reliably ingest new ones.
- Incidents API (list, detail, status updates)
- Filters + pagination for alerts/incidents
- Webhook -> incident integration tests
- Seed data for review flows

## Phase 2 — Classification + Entity Extraction
Goal: Classify incidents and extract key information with clear provenance.
- Classification provenance + confidence storage
- Entity extraction pipeline with NER fallback
- Evaluation fixtures and tests

## Phase 3 — Pairing + Summaries
Goal: Pair new incidents to prior ones and generate next steps.
- Embeddings for incidents/runbooks (pgvector)
- Similarity search service
- Summarizer endpoint with retrieved context
- Next-steps generator and storage

## Phase 4 — Dashboard + Chat UI
Goal: Provide a dashboard and chat interface for triage.
- Next.js shell
- Incidents table + detail view
- Chat UI wired to /chat
- Similar incidents + suggested actions panel

## Phase 5 — Connectors
Goal: Pull context from external systems.
- Connector framework (auth, sync, schema)
- Notion runbooks
- Linear incident context
- Slack history

## Phase 6 — Simulation + Demo Mode
Goal: Provide fake data and a demo walkthrough.
- Fake data generator
- Demo mode toggle + seed scripts
- Alert replay simulator
- E2E demo walkthrough

## Guiding Principles
- Prefer defensive defaults and graceful degradation
- Persist provenance for ML outputs (heuristic vs model)
- Keep ingestion fast; do heavy work async
- Build for demoability at each phase
