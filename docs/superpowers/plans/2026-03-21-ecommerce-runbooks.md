# Ecommerce Platform Runbooks Implementation Plan

**Goal:** Write six comprehensive on-call runbooks for an ecommerce platform and update `push_notion_mock.py` to handle Notion's 100-block limit.

**Architecture:** Six static markdown files authored in `datasets/notion_mock/`, each a standalone service bible with recorded incidents, failure mode catalog, procedures, monitoring, and escalation policy. A code fix to `push_notion_mock.py` paginates block appends so large files don't get silently truncated by the Notion API.

**Tech Stack:** Python 3, Notion REST API, Markdown, requests, python-dotenv

---

## Files

| Action | Path | Purpose |
|---|---|---|
| Modify | `datasets/push_notion_mock.py` | Add block pagination (100-block Notion limit) |
| Create | `datasets/notion_mock/checkout-payments-runbook.md` | Checkout & Payments service bible |
| Create | `datasets/notion_mock/product-catalog-runbook.md` | Product Catalog service bible |
| Create | `datasets/notion_mock/cdn-storefront-runbook.md` | CDN & Storefront service bible |
| Create | `datasets/notion_mock/auth-sessions-runbook.md` | Auth & Sessions service bible |
| Create | `datasets/notion_mock/queue-workers-runbook.md` | Queue & Workers service bible |
| Create | `datasets/notion_mock/database-cache-runbook.md` | Database & Cache service bible |

---

## Runbook Template

Every runbook must follow this schema exactly. H1 heading must match the spec table precisely.

```markdown
# <Service Name> Runbook

## Service Overview
[Architecture, dependencies, SLOs, owning team]

## Recorded Incidents

### INC-YYYY-NNNN — <Short Title>
**Date:** YYYY-MM-DD | **Severity:** P0/P1/P2
**Description:** ...
**Impact:** ...
**Root Cause:** ...
**Resolution Steps:**
[commands, queries, config changes]
**Follow-up Actions:** ...

[repeat for 2 more incidents]

## Failure Mode Catalog

### <Failure Mode Name>
**Symptoms:** ...
**Diagnosis:** ...
**Resolution:** ...
**Escalate if:** ...

[repeat for 3-5 failure modes]

## Runbook Procedures

### Procedure: <Name>
[numbered steps with exact commands]

## Monitoring & Alerts

| Alert | Threshold | Meaning | First Response |
|---|---|---|---|

## Escalation Policy
[P0-P3 definitions, on-call tiers, comms template]
```

**Content rules:**
- Incidents named `INC-YYYY-NNNN — <Short Title>`, dates between 2024-01-01 and 2025-12-31
- Realistic metrics: "P99 rose to 14s", "error rate hit 34%", "1,847 failed checkouts"
- Real CLI commands: `kubectl`, `psql`, `redis-cli`, `curl`
- Provider-agnostic: PostgreSQL/Redis/Kubernetes (not RDS/ElastiCache/EKS)
- Each resolution step block stays under a single `###` heading, ~2,000 chars max

---

## Task 1: Fix push_notion_mock.py — block pagination

**Files:**
- Modify: `datasets/push_notion_mock.py:91-101`

The `create_page` function currently passes all blocks in one payload. Notion rejects payloads with >100 blocks. Fix: send the first 100 blocks on page creation, then append the rest in batches of 100 via `PATCH /blocks/{page_id}/children`.

- [ ] **Step 1: Add `append_blocks` helper after `create_page`**

```python
NOTION_BLOCK_LIMIT = 100

def append_blocks(session: requests.Session, block_id: str, blocks: list) -> None:
    """Append blocks to an existing Notion block in batches of 100."""
    for i in range(0, len(blocks), NOTION_BLOCK_LIMIT):
        batch = blocks[i : i + NOTION_BLOCK_LIMIT]
        resp = session.patch(
            f"{NOTION_API_BASE}/blocks/{block_id}/children",
            json={"children": batch},
            timeout=30,
        )
        resp.raise_for_status()
```

- [ ] **Step 2: Update `create_page` to cap initial children at 100**

Replace the existing `create_page` function:

```python
def create_page(session: requests.Session, parent_id: str, title: str, blocks: list) -> dict:
    payload = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
        "children": blocks[:NOTION_BLOCK_LIMIT],
    }
    resp = session.post(f"{NOTION_API_BASE}/pages", json=payload, timeout=30)
    resp.raise_for_status()
    page = resp.json()

    if len(blocks) > NOTION_BLOCK_LIMIT:
        append_blocks(session, page["id"], blocks[NOTION_BLOCK_LIMIT:])

    return page
```

- [ ] **Step 3: Update dry-run output to show block count and batches**

In the dry-run block in `main()`:
```python
if args.dry_run:
    batches = (len(blocks) + NOTION_BLOCK_LIMIT - 1) // NOTION_BLOCK_LIMIT
    print(f"[dry-run] Would create: '{title}' ({len(blocks)} blocks, {batches} batch(es))")
    continue
```

- [ ] **Step 4: Verify with dry-run**

```bash
python datasets/push_notion_mock.py --dry-run
```

Expected: each existing file shows block count and batch count, no errors.

- [ ] **Step 5: Commit**

```bash
git add datasets/push_notion_mock.py
git commit -m "fix: paginate Notion block appends to handle >100 blocks per page"
```

---

## Task 2: Checkout & Payments Runbook

**Files:**
- Create: `datasets/notion_mock/checkout-payments-runbook.md`

H1: `# Checkout & Payments Runbook`

**Service overview content:**
- Architecture: checkout-service → payment-processor (Stripe/Adyen abstraction) → fraud-service → order-service → DB. Redis holds cart sessions and idempotency keys.
- SLOs: 99.95% availability, P99 checkout completion <3s, payment error rate <0.1%
- Owner: Payments Platform team

**Three incidents to write:**

1. `INC-2024-0112 — Black Friday Checkout Latency Spike` (P0, 2024-11-29)
   - Redis cart session reads hit 98% memory, eviction policy `allkeys-lru` started dropping active carts mid-checkout
   - Impact: 1,847 abandoned checkouts over 23 minutes, ~$340k GMV loss
   - Root cause: `maxmemory` set to 4GB but 6GB of cart data under Black Friday load
   - Resolution: `redis-cli CONFIG SET maxmemory 8gb`, then `kubectl scale deployment/checkout-service --replicas=12`
   - Follow-up: add memory headroom alert at 70%, pre-scale Redis before sale events

2. `INC-2024-0287 — Payment Webhook Storm` (P1, 2024-08-14)
   - Payment provider sent 45k duplicate `payment.succeeded` webhooks over 8 minutes after their infrastructure incident
   - Impact: duplicate order creation attempts (idempotency key dedup prevented most, but 312 orders created twice)
   - Root cause: provider-side retry storm without exponential backoff
   - Resolution: enabled circuit breaker on webhook ingestion endpoint, manually voided 312 duplicate orders via `psql`
   - Follow-up: add idempotency key TTL extension, add duplicate-order detection job

3. `INC-2025-0044 — Fraud Service Timeout Cascade` (P1, 2025-02-03)
   - fraud-service ML model redeployment caused 30s cold start; checkout-service had no timeout on fraud check, held connections
   - Impact: checkout P99 rose to 47s, 94% of checkouts failed for 11 minutes
   - Root cause: missing timeout + no fallback mode on fraud service call
   - Resolution: `kubectl rollout undo deployment/fraud-service`, added `FRAUD_SERVICE_TIMEOUT_MS=2000` env var
   - Follow-up: implement allow-on-timeout fallback for fraud checks below $500

**Failure modes catalog (4 modes):** idempotency key collision, payment gateway 502 storm, order creation DB deadlock, cart session stampede on cache miss

**Procedures:** emergency disable fraud check, rollback payment gateway config, drain and replay failed payment events

**Monitoring:** checkout error rate, payment gateway latency p99, fraud service timeout rate, cart Redis memory %

**Escalation:** P0 = page Payments on-call immediately + VP Eng within 5min; P1 = page on-call, escalate if no resolution in 30min

- [ ] **Step 1: Write the file** following the template above with full realistic content
- [ ] **Step 2: Verify dry-run**

```bash
python datasets/push_notion_mock.py --dry-run 2>&1 | grep checkout
```

Expected: `checkout-payments-runbook` appears with block count >50.

- [ ] **Step 3: Commit**

```bash
git add datasets/notion_mock/checkout-payments-runbook.md
git commit -m "docs: add Checkout & Payments on-call runbook"
```

---

## Task 3: Product Catalog Runbook

**Files:**
- Create: `datasets/notion_mock/product-catalog-runbook.md`

H1: `# Product Catalog Runbook`

**Service overview content:**
- Architecture: catalog-api → Elasticsearch (search) → PostgreSQL (source of truth) → Redis (price/inventory cache). Async reindex worker syncs DB → ES on product changes.
- SLOs: search P99 <200ms, inventory read P99 <50ms, catalog availability 99.99%
- Owner: Catalog Platform team

**Three incidents to write:**

1. `INC-2024-0198 — Search Index Corruption During Reindex` (P1, 2024-09-22)
   - Zero-downtime reindex job wrote to wrong alias due to a misconfigured `index.aliases` setting; live traffic was pointed at the partially-built index for 14 minutes
   - Impact: 38% of search queries returned empty results or incorrect products
   - Root cause: alias swap logic didn't verify index health before swapping
   - Resolution: `curl -X POST "localhost:9200/_aliases" -d '{"actions":[{"add":{"index":"products_v41","alias":"products_live"}}]}'`, rolled back alias to previous index
   - Follow-up: add green-health gate before alias swap, add search result count monitoring

2. `INC-2024-0331 — Inventory Oversell During Flash Sale` (P1, 2024-12-12)
   - Flash sale set inventory to 500 units; Redis cache served stale inventory count (TTL 60s) while DB was already at 0; 214 extra orders accepted
   - Impact: 214 oversold orders, customer service cost ~$18k in refunds/coupons
   - Root cause: inventory reads served from Redis without write-through invalidation on decrement
   - Resolution: `redis-cli DEL inventory:*`, switched to read-through with TTL=5s for sale items
   - Follow-up: implement write-through cache invalidation on inventory decrement

3. `INC-2025-0071 — Price Update Propagation Lag` (P2, 2025-03-08)
   - Bulk price update for 120k products queued a reindex; worker fell behind by 4 hours; customers saw old prices
   - Impact: $4,200 in orders at incorrect (lower) prices, all honored
   - Root cause: reindex worker single-threaded, no priority queue for price changes vs. description changes
   - Resolution: `kubectl scale deployment/catalog-worker --replicas=8`, drained queue in 40 minutes
   - Follow-up: add priority lanes in reindex queue (price/inventory = high, descriptions = low)

**Failure modes (4 modes):** Elasticsearch split-brain, cache stampede on popular product page, slow reindex blocking writes, search timeout under indexing pressure

**Procedures:** rebuild search index from scratch, emergency inventory lock (disable decrement), purge product cache, pause reindex worker

**Monitoring:** search latency p99, index lag (DB vs ES), cache hit rate, inventory read error rate

**Escalation:** P0 = page Catalog on-call + search infra team; P1 = page on-call

- [ ] **Step 1: Write the file** following the template with full realistic content
- [ ] **Step 2: Commit**

```bash
git add datasets/notion_mock/product-catalog-runbook.md
git commit -m "docs: add Product Catalog on-call runbook"
```

---

## Task 4: CDN & Storefront Runbook

**Files:**
- Create: `datasets/notion_mock/cdn-storefront-runbook.md`

H1: `# CDN & Storefront Runbook`

**Service overview content:**
- Architecture: browser → CDN edge (Varnish/Fastly-equivalent) → origin shield → Next.js storefront → backend API. Image delivery via separate image-service with CDN passthrough.
- SLOs: storefront TTFB <800ms p99 at edge, image delivery <300ms p95, CDN cache hit rate >85%
- Owner: Storefront Platform team

**Three incidents to write:**

1. `INC-2024-0089 — Origin Shield Misconfiguration Causing Cache Bypass` (P1, 2024-06-17)
   - Config deploy changed `Surrogate-Control` header from `max-age=300` to `no-store` on product pages; CDN stopped caching; all requests hit origin
   - Impact: origin traffic spiked 40x, storefront P99 rose to 9s, 12% error rate for 31 minutes
   - Root cause: config template variable substitution bug in deploy pipeline
   - Resolution: `curl -X POST https://api.cdn.internal/purge -d '{"paths":["/*"]}'` + config rollback via `kubectl rollout undo deployment/storefront`
   - Follow-up: add cache-hit-rate alert at <70%, add config diff check in deploy pipeline

2. `INC-2024-0445 — Image Service OOM Under Holiday Load` (P0, 2024-12-26)
   - image-service pods OOMKilled under post-Christmas traffic; image requests returned 502 for 19 minutes
   - Impact: all product images broken sitewide, estimated 22% conversion drop
   - Root cause: memory limit set to 512Mi but image resizing of large uploads required up to 2GB
   - Resolution: `kubectl set resources deployment/image-service --limits=memory=2Gi`, rolled out new pods
   - Follow-up: add image upload size validation, set memory request=limit to avoid OOM scheduling

3. `INC-2025-0019 — Frontend Deploy Causing Storefront 500s` (P1, 2025-01-15)
   - Next.js build deployed with a missing environment variable (`NEXT_PUBLIC_CHECKOUT_URL`); checkout button rendered as broken link
   - Impact: checkout button non-functional for 8 minutes before detected; ~400 affected sessions
   - Root cause: env var not added to production deploy manifest
   - Resolution: `kubectl rollout undo deployment/storefront`, restored previous image
   - Follow-up: add smoke test verifying checkout URL renders correctly post-deploy

**Failure modes (4 modes):** CDN cache stampede on origin, stale CDN edge after failed purge, image service CPU spike on malformed uploads, static asset 404 after deploy

**Procedures:** emergency CDN purge (all paths / specific path), storefront rollback, disable image resizing fallback to raw CDN, increase origin pool size

**Monitoring:** CDN cache hit rate, origin error rate, image service latency p95, storefront TTFB p99

**Escalation:** P0 (site down/images broken sitewide) = page Storefront on-call + CDN vendor escalation contact; P1 = page on-call

- [ ] **Step 1: Write the file** following the template with full realistic content
- [ ] **Step 2: Commit**

```bash
git add datasets/notion_mock/cdn-storefront-runbook.md
git commit -m "docs: add CDN & Storefront on-call runbook"
```

---

## Task 5: Auth & Sessions Runbook

**Files:**
- Create: `datasets/notion_mock/auth-sessions-runbook.md`

H1: `# Auth & Sessions Runbook`

**Service overview content:**
- Architecture: auth-service → PostgreSQL (user accounts) → Redis (session store, rate limit counters) → JWT signing (RSA key pair in Vault). OAuth via Google/Apple passthrough.
- SLOs: login P99 <500ms, session validation P99 <20ms (Redis), auth availability 99.99%
- Owner: Identity Platform team

**Three incidents to write:**

1. `INC-2024-0156 — Redis Session Store Memory Exhaustion` (P0, 2024-07-04)
   - Session Redis instance hit `maxmemory` limit; `noeviction` policy caused all new session writes to fail; users could not log in
   - Impact: login failures for 100% of new sessions for 26 minutes; existing sessions unaffected
   - Root cause: session TTL set to 30 days after a UX change; expected active sessions grew from 2M to 11M
   - Resolution: `redis-cli CONFIG SET maxmemory-policy allkeys-lru`, immediately freed 40% memory; then `redis-cli CONFIG SET maxmemory 16gb`
   - Follow-up: set session TTL back to 7 days, add memory alert at 75%, separate session Redis from rate-limit Redis

2. `INC-2024-0302 — JWT Signing Key Rotation Causing Mass Logout` (P1, 2024-10-30)
   - Vault key rotation script rotated the JWT RSA private key but did not update auth-service; all existing JWTs became invalid
   - Impact: all ~800k active sessions invalidated simultaneously; mass logout of entire user base; login queue spiked
   - Root cause: key rotation runbook did not include auth-service restart step
   - Resolution: reloaded old key from Vault backup, restarted auth-service with correct key reference
   - Follow-up: implement dual-key validation window during rotation (accept old + new key for 10 minutes)

3. `INC-2025-0033 — OAuth Provider Outage Locking Out Social Login Users` (P2, 2025-02-18)
   - Google OAuth endpoint returned 503 for 47 minutes; all Google-authenticated users could not log in
   - Impact: ~31% of user base uses Google OAuth; support ticket volume spiked 8x
   - Root cause: external provider incident, no fallback path for social login users
   - Resolution: enabled "continue with email link" emergency fallback via feature flag `auth.social_login_fallback=email_magic_link`
   - Follow-up: add magic link fallback as default for OAuth users, add status page integration for OAuth providers

**Failure modes (4 modes):** session fixation after cache eviction, rate limit counter desync, token replay attack detection gap, auth-service cold start under traffic spike

**Procedures:** flush expired sessions only (safe), emergency rotate JWT key with dual-key window, enable guest checkout bypass, disable social login and force email auth

**Monitoring:** login error rate, session write latency, Redis session memory %, JWT validation failure rate

**Escalation:** P0 (users cannot log in) = page Identity on-call immediately + Security team; P1 = page on-call, escalate if >15 minutes

- [ ] **Step 1: Write the file** following the template with full realistic content
- [ ] **Step 2: Commit**

```bash
git add datasets/notion_mock/auth-sessions-runbook.md
git commit -m "docs: add Auth & Sessions on-call runbook"
```

---

## Task 6: Queue & Workers Runbook

**Files:**
- Create: `datasets/notion_mock/queue-workers-runbook.md`

H1: `# Queue & Workers Runbook`

**Service overview content:**
- Architecture: RabbitMQ/Redis Streams for task queues. Workers: order-worker (order fulfillment), notification-worker (email/SMS/push), webhook-worker (outbound merchant webhooks), fulfillment-worker (3PL integration). DLQ per worker type.
- SLOs: order processing P99 <30s end-to-end, notification delivery <2 min, webhook delivery <5 min with 3 retries
- Owner: Platform Engineering team

**Three incidents to write:**

1. `INC-2024-0118 — Order Queue Backlog During Black Friday` (P0, 2024-11-29)
   - order-worker throughput (120 orders/min) could not keep up with 1,400 orders/min peak; queue grew to 87k messages; order confirmation emails delayed 11 hours
   - Impact: customers saw "order pending" for hours, ~12k support contacts, $45k support cost
   - Root cause: worker scaled to only 4 replicas; HPA max was hardcoded at 4 in the deploy manifest
   - Resolution: `kubectl patch hpa order-worker -p '{"spec":{"maxReplicas":40}}'`; queue drained in 90 minutes
   - Follow-up: load test pre-Black Friday, set HPA max to 50, add queue depth alert at 10k messages

2. `INC-2024-0377 — Notification Worker Crash Loop` (P1, 2024-12-03)
   - notification-worker entered CrashLoopBackOff after a deploy; a malformed email template caused an unhandled exception on message deserialization
   - Impact: all transactional emails (order confirmation, shipping) paused for 2 hours; 34k emails delayed
   - Root cause: template change not validated against message schema; no dead-letter handling for deserialization errors
   - Resolution: `kubectl rollout undo deployment/notification-worker`; manually replayed 34k messages from DLQ
   - Follow-up: add schema validation on worker startup, add DLQ replay tooling

3. `INC-2025-0058 — Webhook Delivery Retry Storm` (P1, 2025-03-01)
   - A merchant's webhook endpoint returned 500 for 6 hours; webhook-worker retried with exponential backoff but 1.2M retry attempts accumulated; overwhelmed the message broker
   - Impact: webhook delivery to all other merchants degraded; order-worker latency spiked due to broker contention
   - Root cause: per-merchant retry limit not enforced; one bad endpoint consumed all broker capacity
   - Resolution: `redis-cli SREM webhook:active_merchants <merchant_id>` to pause retries; manually disabled merchant's webhook endpoint in DB
   - Follow-up: add per-merchant circuit breaker, cap retry queue depth per endpoint

**Failure modes (4 modes):** DLQ overflow (messages lost), worker OOM on oversized payload, duplicate message processing (at-least-once delivery edge case), broker connection pool exhaustion

**Procedures:** pause a specific worker type, drain and replay DLQ, emergency scale workers, disable non-critical queues (notifications only, keep order processing)

**Monitoring:** queue depth per queue, DLQ message count, worker processing rate, consumer lag, broker memory %

**Escalation:** P0 (order processing stopped) = page Platform on-call + Payments team; P1 = page on-call

- [ ] **Step 1: Write the file** following the template with full realistic content
- [ ] **Step 2: Commit**

```bash
git add datasets/notion_mock/queue-workers-runbook.md
git commit -m "docs: add Queue & Workers on-call runbook"
```

---

## Task 7: Database & Cache Runbook

**Files:**
- Create: `datasets/notion_mock/database-cache-runbook.md`

H1: `# Database & Cache Runbook`

**Service overview content:**
- Architecture: PostgreSQL primary + 2 read replicas (streaming replication). Redis cluster (3 nodes) for caching, rate limiting, and session store. PgBouncer connection pooler in front of primary.
- SLOs: primary write P99 <50ms, read replica lag <500ms, Redis P99 <5ms, DB availability 99.99%
- Owner: Data Platform team

**Three incidents to write:**

1. `INC-2024-0203 — Read Replica Lag Causing Stale Inventory Reads` (P1, 2024-09-05)
   - A long-running analytics query on replica-2 caused replication lag to grow to 4 minutes; inventory reads (routed to replicas) served 4-minute-stale data; oversells occurred
   - Impact: 89 oversold orders during a flash sale, $7,200 in refunds
   - Root cause: analytics workload not isolated from OLTP replicas; no replication lag monitoring
   - Resolution: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE query_start < now() - interval '5 minutes' AND state = 'active';`; lag recovered in 3 minutes; rerouted inventory reads to primary
   - Follow-up: add dedicated analytics replica, add replication lag alert at 30s, route inventory reads to primary during sales

2. `INC-2024-0419 — Redis Eviction Storm Under Memory Pressure` (P0, 2024-12-31)
   - New Year's Eve traffic caused Redis memory to hit `maxmemory`; `allkeys-lru` eviction started dropping hot cache keys; every evicted key triggered a DB read; DB connections exhausted
   - Impact: DB connection pool exhausted (500/500 connections), 67% of API requests failed for 18 minutes
   - Root cause: Redis `maxmemory` sized for average load; no memory headroom for traffic spikes
   - Resolution: `redis-cli CONFIG SET maxmemory 24gb` (from 12gb); added 4 read replicas via `kubectl scale`; connection pressure relieved in 8 minutes
   - Follow-up: set `maxmemory` to 75% of available RAM, add Redis memory alert at 70%

3. `INC-2025-0012 — Slow Query Cascade From Missing Index` (P1, 2025-01-07)
   - Post-holiday reporting job added a query on `orders.created_at` without an index; full table scans (230M rows) locked shared buffers; all queries slowed
   - Impact: API P99 rose to 8s for 22 minutes; checkout error rate 14%
   - Root cause: query deployed without EXPLAIN review; no slow query alerting
   - Resolution: `CREATE INDEX CONCURRENTLY idx_orders_created_at ON orders(created_at);` (completed in 4 minutes); killed the reporting job
   - Follow-up: add `pg_stat_statements` slow query alert (>1s), require EXPLAIN plan in PR for new queries on large tables

**Failure modes (4 modes):** connection pool exhaustion (PgBouncer saturation), replication slot lag bloat (WAL accumulation), cache stampede on cold start, primary failover (manual promotion)

**Procedures:**
- Emergency connection pool flush: kill idle connections, restart PgBouncer
- Promote read replica to primary (step-by-step)
- Add index concurrently without table lock
- Emergency Redis flush (cache-only keys, not sessions)

**Monitoring:** DB connection count (used/max), replication lag per replica, slow query count (>500ms), Redis memory %, PgBouncer pool saturation

**Escalation:** P0 (primary DB down or connection pool full) = page Data Platform on-call immediately + CTO; P1 = page on-call, escalate if >20 minutes

- [ ] **Step 1: Write the file** following the template with full realistic content
- [ ] **Step 2: Commit**

```bash
git add datasets/notion_mock/database-cache-runbook.md
git commit -m "docs: add Database & Cache on-call runbook"
```

---

## Task 8: Push to Notion and sync

- [ ] **Step 1: Dry-run to verify all 6 files and block counts**

```bash
python datasets/push_notion_mock.py --dry-run
```

Expected: 6 files listed, each showing >50 blocks and multiple batches.

- [ ] **Step 2: Push to Notion**

```bash
python datasets/push_notion_mock.py
```

Expected: 6 lines of `Created: '<Title>' -> https://www.notion.so/...`

- [ ] **Step 3: Trigger connector sync**

```bash
curl -X POST http://localhost:8000/connectors/notion/sync
```

Expected: `{"status": "success", "synced_pages": ..., "inserted_chunks": ...}`

- [ ] **Step 4: Verify chunks ingested**

```bash
curl "http://localhost:8000/connectors/notion/pages" | python -m json.tool
```

Expected: 6+ pages listed with chunk counts.
