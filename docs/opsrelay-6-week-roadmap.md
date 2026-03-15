# OpsRelay 6-Week Roadmap

## Repo-Based Baseline (Current State)
- Backend: FastAPI routers for webhooks, incidents, alerts, dashboard, runbooks, connectors, and chat streaming are implemented.
- Data layer: PostgreSQL models include alerts/incidents/actions/runbook chunks, with pgvector support when available.
- Async pipeline: webhook ingestion triggers Celery tasks for classification, entity extraction, grouping, and embedding updates.
- Retrieval/summaries: incident similarity, runbook search, summary generation, citations, and next steps are implemented.
- Frontend: Next.js dashboard, incidents list/detail, alerts, runbooks, and connectors pages are wired.
- Testing: unit + integration tests exist; no CI is configured.
- Known explicit TODO: PagerDuty signature verification is still a placeholder (`backend/app/services/signature_verification.py`).

## 6-Week Plan (Milestones, Goals, Deliverables)

| Week | Milestone | Weekly Goal | Deliverables |
|---|---|---|---|
| 1 | Ingestion and Security Hardening | Make webhook ingestion production-safe and deterministic across sources. | Implement PagerDuty signature verification; normalize webhook error handling/observability; add webhook security + contract tests; document required secrets and `SKIP_SIGNATURE_VERIFICATION` policy. |
| 2 | Data Quality and Incident Lifecycle Reliability | Improve grouping, status transitions, and audit correctness. | Tighten grouping rules and edge-case tests; status transition guardrails + timestamps validation; improve incident/action audit consistency checks; seed scripts for deterministic review flows. |
| 3 | Retrieval Quality Upgrade | Improve similarity and runbook retrieval relevance. | Tune hybrid scoring thresholds (`RAG_*` vars); add retrieval regression fixtures; implement retrieval diagnostics output (top matches, score components); expand `docs/rag-evals.md` with pass/fail criteria. |
| 4 | Summary and Copilot Quality | Make summaries/next steps more actionable and stable. | Refine summary structure and citation completeness; improve next-step heuristics by severity/service context; add chat orchestration tests for fallback and streaming failure paths; cache invalidation checks when context changes. |
| 5 | Connector Depth and Sync Workflows | Move connectors from basic status toggles to usable ingestion paths. | Define connector auth/sync contract; implement first real ingestion path (start with Notion runbooks); add connector sync state/error telemetry; integration tests for sync lifecycle. |
| 6 | Release Readiness and Demo Mode | Prepare for repeatable demos and safer releases. | End-to-end demo script with seeded data + alert replay; production readiness checklist (timeouts, retries, observability, rollback); baseline CI job for unit/integration gates; final roadmap/architecture doc refresh with known limits. |

## Milestone Summary
- Milestone 1 (Weeks 1-2): Production-safe ingestion and lifecycle correctness.
- Milestone 2 (Weeks 3-4): Retrieval + copilot quality and trust improvements.
- Milestone 3 (Weeks 5-6): Connector usefulness and release/demo readiness.

## Dependencies
- Runtime services: Postgres (with pgvector where enabled), Redis, Celery worker, ML inference service, frontend/backend containers.
- Secrets and external APIs: Datadog/Sentry/PagerDuty webhook secrets, optional OpenAI key for LLM-backed chat output.
- Data prerequisites: runbook markdown corpus and seed datasets for deterministic eval/demo.
- Tooling prerequisites: stable Docker Compose dev/test flows and repeatable test fixtures.

## Architecture Constraints to Respect
- Webhook endpoints must stay fast; heavy work remains async via Celery.
- ML and LLM paths must degrade gracefully with safe defaults when dependencies fail.
- Provenance for classification/entity extraction should remain persisted and surfaced in API responses.
- Similarity/retrieval should remain deterministic and hybrid-ready (vector + keyword).
- API/response shapes should stay stable while retrieval internals evolve.

## Risks and Mitigations
- Risk: External dependency flakiness (ML service, OpenAI, connectors).  
  Mitigation: timeouts, retries, fallback behavior, and explicit degraded-status telemetry.
- Risk: Retrieval relevance regressions from scoring changes.  
  Mitigation: offline eval fixtures, score-threshold guardrails, and regression gates before release.
- Risk: Data drift from non-deterministic sample/demo generation.  
  Mitigation: deterministic seed scripts and pinned fixtures for demos/tests.
- Risk: Security gaps in webhook signature coverage.  
  Mitigation: complete PagerDuty verification, enforce secret checks, test malformed signature paths.
- Risk: Shipping without CI enforcement.  
  Mitigation: introduce minimal CI in Week 6 for required test suites and merge gates.
