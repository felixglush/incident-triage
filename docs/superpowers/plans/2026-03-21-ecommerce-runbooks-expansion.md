# Ecommerce Runbooks Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand 6 service runbooks with additional incidents, inter-service impact maps, and rollback decision trees; write postmortems for all 18 named incidents; create pre-action checklists for each service.

**Architecture:** Three document sets stored in `datasets/notion_mock/`:
1. **Expanded runbooks** — existing 6 files enhanced with 3-5 additional incidents each, impact maps, and rollback trees
2. **Postmortems** — 18 separate markdown files (3 per service), one per named incident, with timeline, root cause deep-dive, action items
3. **Pre-action checklists** — 6 files, one per service, with pre-deploy, pre-sale, and pre-maintenance checklists

All files pushed to Notion via updated `push_notion_mock.py` and synced into RAG.

**Tech Stack:** Markdown, Notion REST API (via existing push script)

---

## Files

| Action | Path | Purpose |
|---|---|---|
| Modify | `datasets/notion_mock/checkout-payments-runbook.md` | Add 4 more incidents, impact map, rollback tree |
| Modify | `datasets/notion_mock/product-catalog-runbook.md` | Add 4 more incidents, impact map, rollback tree |
| Modify | `datasets/notion_mock/cdn-storefront-runbook.md` | Add 4 more incidents, impact map, rollback tree |
| Modify | `datasets/notion_mock/auth-sessions-runbook.md` | Add 4 more incidents, impact map, rollback tree |
| Modify | `datasets/notion_mock/queue-workers-runbook.md` | Add 4 more incidents, impact map, rollback tree |
| Modify | `datasets/notion_mock/database-cache-runbook.md` | Add 4 more incidents, impact map, rollback tree |
| Create | `datasets/notion_mock/postmortems/checkout-payments-*.md` | 3 postmortems (one per original incident) |
| Create | `datasets/notion_mock/postmortems/product-catalog-*.md` | 3 postmortems |
| Create | `datasets/notion_mock/postmortems/cdn-storefront-*.md` | 3 postmortems |
| Create | `datasets/notion_mock/postmortems/auth-sessions-*.md` | 3 postmortems |
| Create | `datasets/notion_mock/postmortems/queue-workers-*.md` | 3 postmortems |
| Create | `datasets/notion_mock/postmortems/database-cache-*.md` | 3 postmortems |
| Create | `datasets/notion_mock/checklists/checkout-payments-checklist.md` | Pre-action checklist |
| Create | `datasets/notion_mock/checklists/product-catalog-checklist.md` | Pre-action checklist |
| Create | `datasets/notion_mock/checklists/cdn-storefront-checklist.md` | Pre-action checklist |
| Create | `datasets/notion_mock/checklists/auth-sessions-checklist.md` | Pre-action checklist |
| Create | `datasets/notion_mock/checklists/queue-workers-checklist.md` | Pre-action checklist |
| Create | `datasets/notion_mock/checklists/database-cache-checklist.md` | Pre-action checklist |

---

## Incident Expansion Guidelines

Each runbook currently has 3 incidents. Add 4 more (total 7) covering:

1. **Partial failure / degraded mode** — service up but slow or error rate elevated, not a complete outage
2. **Human error incident** — engineer mistake (bad config change, wrong SQL query, typo in deploy)
3. **External dependency failure** — third-party API down, DNS issue, TLS cert expiry
4. **Infrastructure/cascade incident** — resource limit hit that cascades downstream (e.g., DB connection pool exhaustion cascading from cache miss storm)

Incidents should span 2024–2025, realistic metrics, real CLI commands, and actionable resolution steps.

---

## Inter-Service Impact Map Template

Add a new section to each runbook after "Escalation Policy":

```markdown
## Inter-Service Impact Map

When this service degrades, the cascade looks like:

| Stage | Service | Impact | Time to Detect |
|---|---|---|---|
| Immediate | checkout-service | checkout errors spike | <1 min |
| +2 min | order-service | order creation queued behind pending checkouts | +2 min |
| +5 min | notification-service | email backlog grows | +5 min |
| +15 min | webhook-service | merchant notifications delayed | +15 min |

**How to read this:** If [Service X] is down for N minutes, expect downstream services to start failing or degrading at these intervals. Use this to set alert thresholds and determine escalation urgency.

**Isolation actions:** [Steps to prevent downstream cascade — e.g., circuit breaker, rate limiter, fallback mode]
```

---

## Rollback Decision Tree Template

Add a new section to each runbook after "Inter-Service Impact Map":

```markdown
## Rollback Decision Tree

**When to rollback vs. hotfix:**

1. Error rate >5% for >3 minutes?
   - YES → Rollback if error rate is from a recent deploy (within 1 hour)
   - NO → Proceed to diagnosis

2. Customer impact confirmed (> N orders/emails/API calls failing)?
   - YES → If error is in application code, rollback. If error is config/data, hotfix.
   - NO → Wait for more data; don't panic-rollback

3. Confidence in the root cause?
   - HIGH (e.g., obvious null pointer, deploy changelog) → Rollback if deploy is recent
   - LOW (e.g., intermittent or unclear) → Wait 5 minutes for patterns to emerge before rolling back

**Quick rollback command:**
```bash
kubectl rollout undo deployment/<service> -n ecommerce
kubectl rollout status deployment/<service> -n ecommerce
```

**Verification after rollback:**
- Error rate drops to <0.1% within 2 minutes
- Database load returns to baseline
- Customer-facing latency recovers
```

---

## Postmortem Template

One postmortem per incident (18 total). Each is a separate file named: `datasets/notion_mock/postmortems/<service>-INC-YYYY-NNNN.md`

```markdown
# Postmortem: INC-YYYY-NNNN — <Title>

**Date Written:** YYYY-MM-DD
**Incident Date:** YYYY-MM-DD HH:MM–HH:MM UTC
**Duration:** X minutes
**Severity:** P0 / P1 / P2
**DRI:** [Name]
**Attendees:** [Names]

## Executive Summary
[1 paragraph: what happened, impact, cause, how it was fixed]

## Timeline

| Time | Actor | Action | Result |
|---|---|---|---|
| HH:MM | System | Alert fired | `db.replica_lag > 60s` |
| HH:MM | On-call | Paged | Started investigating |
| HH:MM | On-call | Identified queries | Found 22-min full scan |
| HH:MM | On-call | Killed query | Lag recovered in 3 min |

## Root Cause Analysis (5 Whys)

1. Why did the query run?
   → Analyst ran ad-hoc query without `EXPLAIN`

2. Why no timeout?
   → Replica has `statement_timeout=0` (no limit)

3. Why wasn't this caught in pre-flight?
   → No peer review process for ad-hoc queries on production replicas

4. Why did this affect customers?
   → Inventory service rounds-robins across replicas; 50% of reads hit the lagged replica

5. Why no alert?
   → Replica lag alert was at 60s threshold; 4-minute lag was allowed to persist for 10 minutes before firing

## Contributing Factors

- Lack of `statement_timeout` on replicas
- No OLTP/OLAP workload isolation (analytics running on OLTP replicas)
- Inventory read strategy didn't account for lag
- Alert threshold was too permissive

## Remediation (What We Did)

1. Killed the long-running query
2. Routed inventory reads to primary until lag recovered
3. Verified lag dropped below 1s

## Action Items (What We're Doing)

| ID | Action | Owner | Due |
|---|---|---|---|
| A1 | Add `statement_timeout=300s` on all replicas | @data-platform | 2024-09-12 |
| A2 | Create dedicated analytics replica | @data-platform | 2024-10-01 |
| A3 | Add replication lag alert at 30s | @data-platform | 2024-09-10 |
| A4 | Route inventory reads to primary when lag >5s | @catalog-platform | 2024-09-15 |

## Lessons Learned

- **What went well:** On-call responded quickly; root cause identified in <5 minutes
- **What didn't go well:** Query ran for 22 minutes before action; should have caught earlier with a timeout
- **What we'll do differently:** All production queries must have explicit timeouts; no bare ad-hoc queries on replicas

## References

- Runbook: [link to runbook incident section]
- Slack thread: [link if available]
- Related issues: #3744, #3748
```

---

## Pre-Action Checklist Template

One checklist per service. Each is a separate file named: `datasets/notion_mock/checklists/<service>-checklist.md`

```markdown
# <Service> Pre-Action Checklist

Use this checklist before any risky operation: deployments, config changes, major traffic events, maintenance windows.

## Pre-Deploy Checklist

- [ ] All tests passing locally and in CI (`pytest`, `npm test`)
- [ ] Code review approved by 2+ team members
- [ ] `CHANGELOG.md` updated with a 1-sentence summary
- [ ] Environment variables defined in `.env.example` and production
- [ ] Database migrations (if any) tested on staging and have rollback plan
- [ ] Feature flags are configured for gradual rollout (not 100% on day 1)
- [ ] Alert thresholds reviewed; no changes that would suppress alerts
- [ ] Runbook updated if behavior changed
- [ ] On-call engineer notified (ping `#platform-eng`)
- [ ] Deployment window scheduled with team (avoid off-hours unless critical)

**Command to deploy:**
```bash
kubectl set image deployment/<service> <service>=<image:tag> -n ecommerce
kubectl rollout status deployment/<service> -n ecommerce --timeout=5m
```

**Verification after deploy:**
- [ ] Error rate stays <0.1%
- [ ] P99 latency within 10% of baseline
- [ ] Memory usage within expected range
- [ ] No increase in DLQ/error queue depth

## Pre-Sale Checklist (Black Friday, Cyber Monday, etc.)

- [ ] Load test completed: simulate expected peak QPS + 1.5x safety margin
- [ ] Autoscaling policies reviewed: HPA limits, cooldown periods
- [ ] Resource limits adequate: memory, CPU, connection pools
- [ ] Cache pre-warmed: product catalog, pricing, inventory
- [ ] CDN origin shield verified; cache TTLs appropriate
- [ ] Database replicas synced; replication lag <500ms
- [ ] Third-party API providers notified of expected traffic surge
- [ ] On-call coverage confirmed: primary + backup for entire sale window
- [ ] War room Slack channel created and invite sent
- [ ] Synthetic monitoring enabled and dashboard open
- [ ] Circuit breakers configured; fallback modes tested
- [ ] Rate limiters configured per customer/IP
- [ ] Incident commander assigned

**Scaling commands ready to copy-paste:**
```bash
# Scale order-worker
kubectl scale deployment/order-worker --replicas=20 -n ecommerce

# Scale database read replicas
kubectl scale deployment/postgres-replica-2 --replicas=1 -n postgres

# Increase Redis maxmemory
redis-cli CONFIG SET maxmemory 24gb
```

## Pre-Maintenance Checklist (DB upgrades, cluster migrations, etc.)

- [ ] Maintenance window scheduled with at least 1 week notice
- [ ] Stakeholders (product, support, finance) notified of downtime window
- [ ] Data backup completed and tested; restore procedure verified
- [ ] Rollback plan documented with clear steps
- [ ] Staging environment mirrors production (data, size, config)
- [ ] Tested the maintenance procedure on staging 2+ times
- [ ] On-call team briefed; escalation contacts updated
- [ ] Synthetic monitoring disabled (to avoid false alerts)
- [ ] Status page ready to post outage notice 15 minutes before maintenance
- [ ] Communication plan: update frequency (every 15 min), Slack channel, email
- [ ] Post-maintenance verification checklist prepared:
  - [ ] Service responds to requests
  - [ ] Data integrity checks pass
  - [ ] Replication healthy (if applicable)
  - [ ] Alerts firing as expected

## Ongoing Monitoring (Daily/Weekly)

- [ ] Alert thresholds still appropriate (no alert fatigue, no missed issues)
- [ ] SLO compliance tracked; if <99% in rolling 30-day window, initiate post-mortem
- [ ] Slow query log reviewed; new indexes identified
- [ ] Capacity trending; projections for next 3 months
- [ ] Runbook incidents document any recent production issues (even if minor)
```

---

## Task 1: Expand Checkout & Payments Runbook

**Files:**
- Modify: `datasets/notion_mock/checkout-payments-runbook.md`

Add 4 more incidents (total 7), inter-service impact map, and rollback decision tree.

**Incidents to add:**

1. **INC-2024-0201 — Partial Checkout Failures from Payment Gateway Rate Limiting** (P1, 2024-07-20)
   - Payment processor's rate limit kicked in mid-high-traffic day (legitimate volume, not attack). Checkout-service retried too aggressively. 8% of checkouts failed. ~$67k GMV impact. Resolved in 18 minutes by backing off retry frequency.

2. **INC-2024-0456 — Fraud Service Configuration Typo Blocking Legitimate Orders** (P2, 2024-10-12)
   - Deploy changed fraud scoring threshold config from `0.85` to `0.085` (typo: extra zero). Every legitimate order scored >0.085 and was blocked. ~400 customers unable to check out. Detected via customer complaints, not alerts. Fixed in 23 minutes with config rollback.

3. **INC-2025-0118 — Stripe API OAuth Token Expiry During Auto-Renew** (P1, 2025-01-22)
   - Stripe OAuth token silently expired; renewal endpoint was unreachable for 31 minutes due to DNS TTL cache. All Stripe API calls failed. Checkout success rate dropped to 0 for 19 minutes. Root cause: token expiry logic didn't handle network failures gracefully.

4. **INC-2024-0329 — Order Service Database Deadlock Under Concurrent Checkout** (P0, 2024-11-14)
   - Black Friday: order-service INSERT/UPDATE transactions deadlocked on `orders` and `order_items` tables during concurrent checkout bursts. P99 checkout time rose to 18s. 3% of orders rolled back (auto-retried and succeeded). Resolved by reordering SQL operations to avoid circular lock waits.

- [ ] **Step 1:** Read current `checkout-payments-runbook.md` and understand its structure

- [ ] **Step 2:** Add the 4 new incidents (with full description, impact, root cause, resolution steps, follow-up) following the same format as existing incidents

- [ ] **Step 3:** Add "Inter-Service Impact Map" section showing downstream cascade: checkout → order-service → notification-service → webhook-service with time-to-detect

- [ ] **Step 4:** Add "Rollback Decision Tree" section with decision logic and quick rollback commands

- [ ] **Step 5:** Verify file reads correctly and block count

```bash
python datasets/push_notion_mock.py --dry-run 2>&1 | grep checkout
```

- [ ] **Step 6:** Commit

```bash
git add datasets/notion_mock/checkout-payments-runbook.md
git commit -m "docs: expand Checkout & Payments runbook (7 incidents, impact map, rollback tree)"
```

---

## Task 2: Expand Product Catalog Runbook

**Files:**
- Modify: `datasets/notion_mock/product-catalog-runbook.md`

Add 4 more incidents, inter-service impact map, and rollback decision tree.

**Incidents to add:**

1. **INC-2024-0267 — Search Latency Degradation from Elasticsearch GC Pauses** (P1, 2024-08-10)
   - Elasticsearch heap size was 4GB; under heavy indexing, GC pauses stretched to 8 seconds. Search P99 spiked from 180ms to 2.5s. 12% of search requests timed out. Resolved by increasing heap to 6GB and enabling ZGC (low-latency GC).

2. **INC-2025-0087 — Inventory Cache Ttl Too High Causing Oversell** (P1, 2025-02-27)
   - A previous incident (INC-2024-0331) set inventory cache TTL to 5s for sale items. A deploy forgot to revert TTL to 60s after the sale ended. For 8 hours, stale inventory was served; 89 units oversold. Root cause: no integration test to verify TTL rules.

3. **INC-2024-0444 — Elasticsearch Shard Allocation Timeout After Node Failure** (P1, 2024-12-08)
   - A Kubernetes node died; Elasticsearch tried to rebalance shards but hit the `cluster.info.update.interval` timeout. Cluster stayed in YELLOW health for 47 minutes. Search and inventory reads served stale data. Resolved by manually triggering shard allocation and adjusting timeout.

4. **INC-2025-0142 — Product Feed Export Blocking Elasticsearch Reindex** (P2, 2025-03-11)
   - A reporting job read the entire `products` table in a long transaction, holding a shared lock. Reindex-worker couldn't read the changelog for updates. Product changes weren't indexed for 3 hours; 47 updated products (price, description, images) served stale data. Resolved by killing the reporting transaction.

- [ ] **Step 1:** Read current `product-catalog-runbook.md`

- [ ] **Step 2:** Add 4 new incidents with full details

- [ ] **Step 3:** Add "Inter-Service Impact Map" section showing cascade: catalog-api → checkout-service (inventory reads) → order-service → …

- [ ] **Step 4:** Add "Rollback Decision Tree" section

- [ ] **Step 5:** Verify block count

- [ ] **Step 6:** Commit

```bash
git add datasets/notion_mock/product-catalog-runbook.md
git commit -m "docs: expand Product Catalog runbook (7 incidents, impact map, rollback tree)"
```

---

## Task 3: Expand CDN & Storefront Runbook

**Files:**
- Modify: `datasets/notion_mock/cdn-storefront-runbook.md`

Add 4 more incidents, inter-service impact map, and rollback decision tree.

**Incidents to add:**

1. **INC-2024-0198 — Static Asset CSS Load Failure from CDN Path Change** (P1, 2024-05-30)
   - A deploy changed the static asset build hash (normal). The CDN had a 1-hour stale TTL on the manifest file. Old CSS references 404'd. Unstyled website for 1 hour until TTL expired and fresh manifest was fetched. Root cause: manifest TTL too long; should be 5 minutes or less.

2. **INC-2024-0523 — Origin Shield Connection Pool Exhaustion from Slow Clients** (P1, 2024-11-08)
   - CDN edge nodes opened connections to origin shield but slow clients held those connections open with incomplete requests (slowloris-style). Origin shield ran out of connection slots. New legitimate requests queued. Storefront TTFB spiked to 12s. Resolved by increasing connection pool and adding request timeout.

3. **INC-2025-0066 — Next.js Hot Module Reload Regression Causing Hydration Errors** (P2, 2025-02-14)
   - A deploy updated Next.js from 14.0 to 14.1. HMR (hot module reload) in development leaked into production build. Hydration errors on first page load; ~30% of user sessions saw white screen of death. Resolved by downgrading and validating build config.

4. **INC-2024-0301 — Image Service Timeout Cascading to Origin Slowdown** (P1, 2024-10-05)
   - Image-service had a 30-second HTTP timeout on upstream requests. A misconfigured upstream took 15 seconds to respond. Multiple requests queued up waiting. Origin connection pool exhausted. Storefront requests queued behind image requests. Resolved by reducing timeout to 5s and implementing fallback.

- [ ] **Step 1:** Read current `cdn-storefront-runbook.md`

- [ ] **Step 2:** Add 4 new incidents

- [ ] **Step 3:** Add "Inter-Service Impact Map" showing cascade: CDN/image-service → storefront → api-gateway → backend services

- [ ] **Step 4:** Add "Rollback Decision Tree"

- [ ] **Step 5:** Verify block count

- [ ] **Step 6:** Commit

```bash
git add datasets/notion_mock/cdn-storefront-runbook.md
git commit -m "docs: expand CDN & Storefront runbook (7 incidents, impact map, rollback tree)"
```

---

## Task 4: Expand Auth & Sessions Runbook

**Files:**
- Modify: `datasets/notion_mock/auth-sessions-runbook.md`

Add 4 more incidents, inter-service impact map, and rollback decision tree.

**Incidents to add:**

1. **INC-2024-0389 — Password Reset Token Redis Eviction Dropping Reset Requests** (P1, 2024-10-20)
   - Password reset tokens stored in Redis with a 30-minute TTL. Under high volume, Redis memory hit limit and LRU eviction started dropping active reset tokens. Users clicked "reset password" links but the token was already gone. Auth-service returned "invalid token" errors. ~340 users unable to reset password. Resolved by increasing Redis memory.

2. **INC-2025-0029 — Rate Limit Counter Race Condition Allowing Brute Force** (P2, 2025-02-01)
   - Rate limit counters (in Redis) were checked and incremented in separate commands (read + write, not atomic). A race condition allowed ~5 extra login attempts to bypass the rate limiter per window. Not exploited, but discovered in security review. Fixed by using Redis INCR (atomic).

3. **INC-2024-0234 — OIDC Redirect URL Misconfiguration Breaking Apple Login** (P1, 2024-08-03)
   - Apple OAuth config had the wrong `redirect_uri` (staging URL instead of production). All Apple login attempts returned "invalid redirect_uri". ~15% of user base on iOS. Resolved in 4 minutes with config fix, but impacted ~850 sessions during the outage.

4. **INC-2025-0104 — Login Service Pod Restart Cascading from OOM** (P1, 2025-03-05)
   - auth-service pods OOMKilled due to a memory leak in JWT token validation logic (caching entire token payload instead of just claims). 3-minute outage. Resolved by pod restart (and later hotfix for the leak).

- [ ] **Step 1:** Read current `auth-sessions-runbook.md`

- [ ] **Step 2:** Add 4 new incidents

- [ ] **Step 3:** Add "Inter-Service Impact Map" showing cascade: auth-service down → all services reject requests (no valid JWT) → user-facing APIs fail

- [ ] **Step 4:** Add "Rollback Decision Tree"

- [ ] **Step 5:** Verify block count

- [ ] **Step 6:** Commit

```bash
git add datasets/notion_mock/auth-sessions-runbook.md
git commit -m "docs: expand Auth & Sessions runbook (7 incidents, impact map, rollback tree)"
```

---

## Task 5: Expand Queue & Workers Runbook

**Files:**
- Modify: `datasets/notion_mock/queue-workers-runbook.md`

Add 4 more incidents, inter-service impact map, and rollback decision tree.

**Incidents to add:**

1. **INC-2024-0298 — Message Encoding Mismatch Breaking Webhook Worker** (P1, 2024-09-18)
   - A deploy changed message encoding from UTF-8 to UTF-16. Webhook-worker expected UTF-8. All webhook payloads were garbled. 12k webhooks queued for 1 hour. Resolved by reverting deploy.

2. **INC-2025-0073 — Celery Task Timeout Too Short for Large Orders** (P1, 2025-03-03)
   - order-worker had a 60-second task timeout. Orders with >100 line items took 75 seconds to process (inventory checks, fraud scoring, payment). Tasks timed out and were retried. Some orders processed twice. Resolved by increasing timeout to 180 seconds.

3. **INC-2024-0412 — Notification Queue Memory Leak from Unserialized Attachments** (P1, 2024-11-25)
   - notification-worker cached email attachment objects in memory without clearing them. Over 8 hours, memory grew to 2GB (OOM). Resolved by clearing attachment cache every 100 messages.

4. **INC-2024-0156 — RabbitMQ Cluster Majority Loss During Node Failure** (P0, 2024-07-08)
   - A RabbitMQ node failed; the other 2 nodes lost quorum (3-node cluster needs 2/3 majority). All queues became unavailable for 12 minutes until the failed node was removed and quorum re-established. Resolved by scaling cluster to 5 nodes (can tolerate 2 failures).

- [ ] **Step 1:** Read current `queue-workers-runbook.md`

- [ ] **Step 2:** Add 4 new incidents

- [ ] **Step 3:** Add "Inter-Service Impact Map" showing cascade: broker down → all workers stalled → order-service can't enqueue → checkout-service timeouts → API 500s

- [ ] **Step 4:** Add "Rollback Decision Tree"

- [ ] **Step 5:** Verify block count

- [ ] **Step 6:** Commit

```bash
git add datasets/notion_mock/queue-workers-runbook.md
git commit -m "docs: expand Queue & Workers runbook (7 incidents, impact map, rollback tree)"
```

---

## Task 6: Expand Database & Cache Runbook

**Files:**
- Modify: `datasets/notion_mock/database-cache-runbook.md`

Add 4 more incidents, inter-service impact map, and rollback decision tree.

**Incidents to add:**

1. **INC-2024-0176 — PostgreSQL Autovacuum Bloat Causing Full Table Scan Slowdown** (P1, 2024-06-22)
   - Autovacuum was disabled to speed up imports. 3 days later, `products` table had 67% bloat (dead tuples). Queries did full sequential scans taking 45 seconds. Resolved by running manual VACUUM and re-enabling autovacuum.

2. **INC-2025-0037 — Redis Persistence Disk Full Causing RDB Write Failure** (P1, 2025-02-12)
   - Redis disk filled up during RDB (Redis Database) snapshot write. Write failed. Redis threw an error and stopped accepting new keys. All cache writes failed for 8 minutes. Resolved by expanding disk and restarting Redis.

3. **INC-2024-0345 — Connection Leak in Third-Party ORM Library** (P1, 2024-10-15)
   - A third-party ORM library had a connection leak that was triggered by a specific query pattern added in a deploy. Connections drained slowly. After 4 hours, pool was exhausted. Resolved by downgrading library version and redeploying.

4. **INC-2024-0511 — PgBouncer Version Incompatibility Causing Authentication Failures** (P1, 2024-11-30)
   - PgBouncer was upgraded from 1.15 to 1.16. The new version had a bug in the authentication protocol; ~10% of connections randomly rejected with "auth failed". Resolved by downgrading to 1.15.2 (a patch version).

- [ ] **Step 1:** Read current `database-cache-runbook.md`

- [ ] **Step 2:** Add 4 new incidents

- [ ] **Step 3:** Add "Inter-Service Impact Map" showing cascade: DB slow → connection pool fills → API handlers block → user-facing errors

- [ ] **Step 4:** Add "Rollback Decision Tree"

- [ ] **Step 5:** Verify block count

- [ ] **Step 6:** Commit

```bash
git add datasets/notion_mock/database-cache-runbook.md
git commit -m "docs: expand Database & Cache runbook (7 incidents, impact map, rollback tree)"
```

---

## Task 7: Write Postmortems (18 total)

**Files:**
- Create: `datasets/notion_mock/postmortems/checkout-payments-INC-2024-0112.md`
- Create: `datasets/notion_mock/postmortems/checkout-payments-INC-2024-0287.md`
- Create: `datasets/notion_mock/postmortems/checkout-payments-INC-2025-0044.md`
- [+ 15 more postmortems, 3 per service]

Each postmortem follows the template above: Executive Summary, Timeline, RCA (5 Whys), Contributing Factors, Remediation, Action Items, Lessons Learned, References.

- [ ] **Step 1:** Create `datasets/notion_mock/postmortems/` directory

```bash
mkdir -p /Users/felix/incident-triage/datasets/notion_mock/postmortems
```

- [ ] **Step 2:** Write 3 postmortems for Checkout & Payments (one per original incident: INC-2024-0112, INC-2024-0287, INC-2025-0044)

- [ ] **Step 3:** Write 3 postmortems for Product Catalog

- [ ] **Step 4:** Write 3 postmortems for CDN & Storefront

- [ ] **Step 5:** Write 3 postmortems for Auth & Sessions

- [ ] **Step 6:** Write 3 postmortems for Queue & Workers

- [ ] **Step 7:** Write 3 postmortems for Database & Cache

- [ ] **Step 8:** Commit all postmortems

```bash
git add datasets/notion_mock/postmortems/
git commit -m "docs: add 18 postmortems (3 per service)"
```

---

## Task 8: Create Pre-Action Checklists (6 total)

**Files:**
- Create: `datasets/notion_mock/checklists/checkout-payments-checklist.md`
- Create: `datasets/notion_mock/checklists/product-catalog-checklist.md`
- Create: `datasets/notion_mock/checklists/cdn-storefront-checklist.md`
- Create: `datasets/notion_mock/checklists/auth-sessions-checklist.md`
- Create: `datasets/notion_mock/checklists/queue-workers-checklist.md`
- Create: `datasets/notion_mock/checklists/database-cache-checklist.md`

Each checklist follows the template above with: Pre-Deploy, Pre-Sale, Pre-Maintenance, and Ongoing Monitoring sections.

- [ ] **Step 1:** Create `datasets/notion_mock/checklists/` directory

```bash
mkdir -p /Users/felix/incident-triage/datasets/notion_mock/checklists
```

- [ ] **Step 2:** Write checklist for Checkout & Payments (customize for payment processing, fraud checks, idempotency)

- [ ] **Step 3:** Write checklist for Product Catalog (customize for search, inventory, cache warmup)

- [ ] **Step 4:** Write checklist for CDN & Storefront (customize for cache, deployment, image service)

- [ ] **Step 5:** Write checklist for Auth & Sessions (customize for OAuth, token management, session store)

- [ ] **Step 6:** Write checklist for Queue & Workers (customize for broker health, worker scaling, DLQ monitoring)

- [ ] **Step 7:** Write checklist for Database & Cache (customize for replication, connection pools, backups)

- [ ] **Step 8:** Commit all checklists

```bash
git add datasets/notion_mock/checklists/
git commit -m "docs: add 6 pre-action checklists (pre-deploy, pre-sale, pre-maintenance)"
```

---

## Task 9: Push to Notion and Verify

- [ ] **Step 1:** Dry-run to see all files and block counts

```bash
python datasets/push_notion_mock.py --dry-run
```

Expected: 6 expanded runbooks + 18 postmortems + 6 checklists = 30 files total (plus 2 original mock docs)

- [ ] **Step 2:** Push to Notion

```bash
python datasets/push_notion_mock.py
```

- [ ] **Step 3:** Trigger connector sync to ingest into RAG

```bash
curl -X POST http://localhost:8000/connectors/notion/sync
```

Expected: Success with synced_pages count

- [ ] **Step 4:** Verify all runbooks, postmortems, and checklists are listed

```bash
curl http://localhost:8000/connectors/notion/pages | python -m json.tool | head -50
```

- [ ] **Step 5:** Test RAG retrieval on one of the new incidents

```bash
curl -X POST http://localhost:8000/chat/1/stream \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What should I do if Redis memory is exhausted?"}]}'
```

Expected: RAG returns snippets from Database & Cache runbook and related postmortem.

---

**After completing all tasks:**

1. Commit the final state
2. Run `git log --oneline` to verify all commits
3. Estimate final Notion block count and ensure pagination is working correctly
