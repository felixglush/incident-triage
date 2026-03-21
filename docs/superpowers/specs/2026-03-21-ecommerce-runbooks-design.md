# Ecommerce Platform Runbooks — Design Spec

**Date:** 2026-03-21
**Status:** Approved

## Overview

Six comprehensive, provider-agnostic operational runbooks for an ecommerce platform at Shopify-scale. Each runbook covers a single service domain end-to-end and is written to guide on-call engineers through real incidents. Files are authored as markdown and stored in `datasets/notion_mock/`, pushed to Notion via `push_notion_mock.py`, and synced into the RAG system via the Notion connector.

## Delivery

- **Format:** 6 static `.md` files in `datasets/notion_mock/`
- **Tooling:** No generator script — files are handwritten for maximum realism
- **Integration:** Pushed to Notion via `push_notion_mock.py`, then synced via `POST /connectors/notion/sync`
- **Notion block limit:** The Notion API enforces a hard limit of 100 blocks per `children` array. `push_notion_mock.py` must be updated to split pages larger than 100 blocks into sequential `PATCH /blocks/{id}/children` append calls after initial page creation. This is required for all six runbooks, which will each exceed 100 blocks.

## Service Domains

| File | H1 Heading | Service |
|---|---|---|
| `checkout-payments-runbook.md` | `# Checkout & Payments Runbook` | Payment processor, fraud detection, order creation |
| `product-catalog-runbook.md` | `# Product Catalog Runbook` | Search, inventory, pricing |
| `cdn-storefront-runbook.md` | `# CDN & Storefront Runbook` | Edge cache, image delivery, frontend serving |
| `auth-sessions-runbook.md` | `# Auth & Sessions Runbook` | Login, tokens, session store |
| `queue-workers-runbook.md` | `# Queue & Workers Runbook` | Order processing, email/notifications, webhooks |
| `database-cache-runbook.md` | `# Database & Cache Runbook` | Primary DB, read replicas, Redis |

The H1 heading is the canonical title used by `ingestion.py`'s `extract_title()` for RAG chunk metadata. Each file must begin with exactly the H1 shown above.

## Runbook Structure (per file)

Each runbook follows this consistent schema:

### 1. Service Overview
- Architecture summary and key dependencies
- SLOs (availability, latency p99, error rate)
- Owning team and escalation contacts

### 2. Recorded Incidents
2–3 named incidents per runbook, identified with format `INC-YYYY-NNNN — <Short Title>` (e.g. `INC-2024-0112 — Black Friday Checkout Meltdown`). Each includes:
- **Date and severity** (P0/P1/P2)
- **Description** — what happened, what was observed (metrics, logs, alerts that fired)
- **Impact / Outcome** — user-facing effect, duration, estimated revenue impact
- **Root Cause** — confirmed post-incident
- **Resolution Steps** — exact commands, queries, config changes used
- **Follow-up Actions** — tickets, fixes, process changes made afterward

### 3. Failure Mode Catalog
Systematic coverage of known failure patterns not represented in named incidents:
- Symptoms, diagnosis steps, resolution procedure, escalation path

### 4. Runbook Procedures
Step-by-step operational procedures:
- Restart / rollback
- Failover (DB, cache, queue)
- Scale up/out
- Emergency circuit breaker / feature flag disable

### 5. Monitoring & Alerts
- Key metrics and alert thresholds
- What each alert means and first response
- Generic dashboard references

### 6. Escalation Policy
Each runbook must define its own escalation tiers explicitly — no cross-references to a shared policy document. Include:
- On-call tiers and escalation timeline specific to this service's owning team
- Stakeholder communication template (status page, Slack, email)
- Severity classification guide (P0–P3 definitions)

## Content Realism Standards

- Incidents use realistic dates, realistic metric values (e.g. "P99 latency rose to 14s", "error rate hit 34%")
- Resolution steps use real CLI commands (`kubectl`, `psql`, `redis-cli`, `curl`)
- Failure modes are grounded in real ecommerce failure patterns (Black Friday traffic spikes, payment provider outages, cache stampedes, slow deploys)
- Provider-agnostic: "PostgreSQL" not "RDS", "Redis" not "ElastiCache", "Kubernetes" not "EKS"
- Resolution step commands must be grouped under a single `###` heading per procedure and kept within a ~2,000-character block where possible, to avoid chunk-boundary splits during RAG ingestion

## Success Criteria

- An on-call engineer unfamiliar with the service can follow the runbook to diagnose and resolve the most common failures
- Named incidents are specific enough to serve as training examples for RAG retrieval
- Each runbook stands alone — no cross-runbook dependencies, no references to shared policy docs
