# Database & Cache Runbook

## Service Overview

**Architecture:** PostgreSQL 15 primary (m5.4xlarge equivalent) with 2 read replicas using streaming replication (`synchronous_commit=off`). PgBouncer connection pooler runs in transaction mode (`pool_size=100`) in front of the primary. Redis 7 cluster comprises 3 primary nodes and 3 replica nodes, used for product/pricing/inventory caching, rate limiting, session store, and feature flags. All services connect to the primary through PgBouncer; read-heavy services route reads directly to the replicas.

**Key dependencies:**
- PostgreSQL primary — all write operations
- Read replicas (replica-1, replica-2) — read scaling for catalog and reporting
- PgBouncer — connection pooling and load management for the primary
- Redis cluster — caching, session store, rate limiting, feature flags

**SLOs:**
- Primary write P99 latency: <50ms
- Read replica replication lag: <500ms
- Redis P99 latency: <5ms
- DB availability: 99.99%
- Redis availability: 99.99%

**Owner:** Data Platform team — PagerDuty service: `data-platform-oncall`

---

## Recorded Incidents

### INC-2024-0203 — Read Replica Lag Causing Stale Inventory Reads

**Date:** 2024-09-05 | **Severity:** P1

**Description:**
At 11:30 UTC, a product analyst accidentally ran a full sequential scan query on `replica-2` against the `order_items` table (890M rows) — they omitted the `EXPLAIN` keyword and executed the query directly. The query ran for 22 minutes. Streaming replication on `replica-2` fell behind as the long-running query held a shared lock that prevented WAL replay. Replication lag on `replica-2` grew to 4 minutes 17 seconds. Because the inventory read service was configured to round-robin across both replicas, approximately 50% of inventory reads were served with 4-minute-stale data during an active flash sale. The alert `db.replica_lag_seconds{replica=replica-2} > 60` fired at 11:44.

**Impact:**
- 89 oversold orders during the flash sale (stale inventory showed stock as available)
- $7,200 in refunds and store credit issued
- Replica lag fully recovered at 11:54 UTC (24 minutes after query start)

**Root Cause:**
Analytics workload was running directly on OLTP read replicas with no query timeout configured. No replication lag monitoring was in place. The inventory read service had no mechanism to exclude a lagging replica or fall back to the primary during elevated lag conditions.

**Resolution:**
```bash
# 1. Identify and kill the long-running query on replica-2
psql -h replica-2 $DATABASE_URL -c "
  SELECT pid, usename, query_start, now() - query_start AS duration, left(query, 100) AS query
  FROM pg_stat_activity
  WHERE state = 'active' AND query_start < now() - interval '5 minutes'
  ORDER BY duration DESC;"

# Kill the query
psql -h replica-2 $DATABASE_URL -c "SELECT pg_terminate_backend(<pid>);"

# 2. Check replication lag recovery on primary
psql $DATABASE_URL -c "
  SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn,
    (sent_lsn - replay_lsn) AS replication_lag_bytes
  FROM pg_stat_replication;"

# 3. Temporarily route all inventory reads to primary while replica catches up
kubectl set env deployment/catalog-api INVENTORY_DB_READ_TARGET=primary -n ecommerce

# 4. Restore round-robin once replica lag drops below 1s
kubectl set env deployment/catalog-api INVENTORY_DB_READ_TARGET=replica -n ecommerce
```

**Follow-up Actions:**
- Added dedicated analytics replica (replica-3) to isolate OLAP workloads from OLTP replicas (PR #3744)
- Set `statement_timeout=300000` (5 minutes) on all OLTP replicas
- Added replication lag alert threshold at 30 seconds (previously no alert existed)
- Configured inventory read service to route to primary automatically when any replica lag exceeds 5s

---

### INC-2024-0419 — Redis Eviction Storm Under Memory Pressure

**Date:** 2024-12-31 | **Severity:** P0

**Description:**
At 22:47 UTC on New Year's Eve, Redis cluster memory hit `maxmemory` (12GB per node) simultaneously across all 3 primary nodes. The `allkeys-lru` eviction policy began aggressively evicting hot cache keys. Each evicted key triggered a cache miss, which triggered a synchronous database read. The PgBouncer-managed connection pool (max 500 connections) became fully saturated within 3 minutes as cache-miss DB reads flooded in. New DB connections were rejected, causing 67% of API requests to fail. The alert `redis.memory_pct > 90%` fired at 22:47 — the same moment the incident began, providing no warning lead time. New Year's Eve traffic was running at 2.3x normal volume.

**Impact:**
- 67% of API request failures for 18 minutes (22:47–23:05 UTC)
- ~4,100 failed checkout attempts
- ~$890k GMV impact
- DB connection pool fully exhausted (500/500)

**Root Cause:**
Redis `maxmemory` was sized for p95 traffic, not p99+ or holiday surge scenarios. The 90% memory alert threshold provided no actionable warning time before hitting the limit. No pre-scaling plan existed for known high-traffic events. DB connection pool exhaustion cascaded directly from the cache miss storm.

**Resolution:**
```bash
# 1. Confirm Redis memory pressure and DB connection pool exhaustion
redis-cli -c INFO memory | grep used_memory_human
psql $DATABASE_URL -c "SELECT COUNT(*) FROM pg_stat_activity;"
# Expected: 500/500 connections used

# 2. Increase Redis maxmemory across all cluster nodes immediately
redis-cli -c CONFIG SET maxmemory 24gb
# Verify all nodes updated
redis-cli -c CONFIG GET maxmemory

# 3. Kill idle DB connections to free the pool
psql $DATABASE_URL -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE state = 'idle'
  AND state_change < now() - interval '30 seconds'
  AND pid != pg_backend_pid();"

# 4. Scale an additional read replica to absorb remaining DB read pressure
kubectl scale deployment/db-replica-3 --replicas=1 -n ecommerce
# Wait for replica to complete initial sync before routing reads to it

# 5. Monitor Redis memory recovery
watch -n 5 'redis-cli -c INFO memory | grep used_memory_pct'
```

**Follow-up Actions:**
- Set `maxmemory` to 75% of available RAM on all Redis nodes (PR #4504)
- Lowered Redis memory alert threshold to 70%
- Added DB connection pool saturation alert at >80%
- Created pre-scaling runbook for holiday events: Redis and DB replicas scaled proactively 2 hours before planned high-traffic windows

---

### INC-2025-0012 — Slow Query Cascade From Missing Index

**Date:** 2025-01-07 | **Severity:** P1

**Description:**
At 09:15 UTC, a post-holiday reporting feature was deployed that introduced a new query filtering the `orders` table (230M rows) by `created_at` range with a `GROUP BY` on `merchant_id`. No index existed on `orders.created_at`. The reporting feature triggered 3 concurrent full sequential scans, each holding an `AccessShareLock` on the table for 8–12 minutes. Under this lock contention, all other queries touching the `orders` table slowed to a P99 of 8.4 seconds. The alert `db.query_p99_ms > 1000` fired at 09:19.

**Impact:**
- API P99 latency rose from 180ms to 8.4s for 22 minutes (09:15–09:37 UTC)
- Checkout error rate hit 14% (checkout queries touch the `orders` table)
- ~1,900 failed checkout attempts
- Resolved at 09:37 after concurrent index creation completed

**Root Cause:**
A new query on a large table was deployed without an index review or `EXPLAIN` plan in the PR. `pg_stat_statements` slow query monitoring was configured with a 5s alert threshold, which was too high to catch the degradation early.

**Resolution:**
```bash
# 1. Identify slow queries and blocking locks
psql $DATABASE_URL -c "
  SELECT pid, usename, query_start, now() - query_start AS duration,
    wait_event_type, wait_event, left(query, 200) AS query
  FROM pg_stat_activity
  WHERE state = 'active'
  ORDER BY duration DESC
  LIMIT 20;"

# 2. Kill the reporting job queries (not production traffic)
psql $DATABASE_URL -c "SELECT pg_terminate_backend(<reporting_pid>);"

# 3. Create the missing index concurrently (no table lock — safe for production writes)
psql $DATABASE_URL -c "
  CREATE INDEX CONCURRENTLY idx_orders_created_at
  ON orders(created_at);"
# This takes approximately 4 minutes for 230M rows; monitor progress:
psql $DATABASE_URL -c "
  SELECT phase, blocks_done, blocks_total,
    round(100.0 * blocks_done / nullif(blocks_total, 0), 1) AS pct_complete
  FROM pg_stat_progress_create_index
  WHERE relid = 'orders'::regclass;"

# 4. Verify the index was created successfully
psql $DATABASE_URL -c "\d+ orders" | grep idx_orders_created_at

# 5. Verify the query now uses the index
psql $DATABASE_URL -c "EXPLAIN SELECT COUNT(*) FROM orders WHERE created_at > now() - interval '7 days';"
```

**Follow-up Actions:**
- Lowered `pg_stat_statements` slow query alert threshold to >500ms (PR #4801)
- Added PR requirement: `EXPLAIN` plan must be included in description for any new query on tables exceeding 10M rows
- Added `orders.created_at` index to schema baseline in `init_db.py`

---

### INC-2024-0176 — PostgreSQL Autovacuum Bloat Causing Full Table Scan Slowdown

**Date:** 2024-06-22 | **Severity:** P1

**Description:**
At 14:45 UTC, the Data Pipelines team disabled PostgreSQL autovacuum on the primary to accelerate a bulk import of 45M product records (non-critical catalog update). The team planned to re-enable autovacuum after the import completed. However, the runbook they followed was outdated — it did not include a step to re-enable autovacuum. For 3 days, autovacuum remained disabled. Dead tuples (deleted/updated rows) accumulated on the `products` table (890M rows). By 2024-06-25, the table had 67% bloat (590M dead tuples). Queries against the table began performing full sequential scans and taking 45 seconds. The alert `db.query_p99_ms > 1000` fired. The inventory-read service timed out queries, returning HTTP 503 errors for a partial product catalog.

**Impact:**
- Inventory API P99 latency: 45s (normal: <200ms)
- Inventory API error rate: 12% (timeout errors) for 4 hours
- ~500 failed product searches during that window
- Merchant dashboard "Products" page loading failed with 503

**Root Cause:**
Autovacuum was disabled without a time-bound re-enable step in the runbook. The import took 8 hours; the team forgot to re-enable autovacuum afterward. Dead tuple bloat accumulated over 3 days, degrading query performance on the heavily-accessed `products` table.

**Resolution:**
```bash
# 1. Check bloat percentage on the products table
psql $DATABASE_URL -c "
  SELECT schemaname, tablename,
    ROUND(100 - (CASE WHEN otta=0 OR sml.relpages = 0 OR sml.relpages = otta
      THEN 100.0 ELSE GREATEST(0, LEAST(100, (sml.relpages - otta) * 100.0 / sml.relpages)) END)::numeric, 2) AS bloat_ratio
  FROM pg_class
  JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
  LEFT JOIN pg_stat_user_tables sml ON pg_class.oid = sml.relid
  WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    AND tablename = 'products';"

# 2. Verify autovacuum is disabled
psql $DATABASE_URL -c "SELECT name, setting FROM pg_settings WHERE name = 'autovacuum';"

# 3. Re-enable autovacuum immediately
psql $DATABASE_URL -c "ALTER SYSTEM SET autovacuum = on;"
# Reload config
psql $DATABASE_URL -c "SELECT pg_reload_conf();"

# 4. Run manual VACUUM on the bloated table (blocks writes temporarily)
psql $DATABASE_URL -c "VACUUM ANALYZE products;"
# For a 890M-row table with 67% bloat, expect 8–15 minutes

# 5. Monitor VACUUM progress
watch -n 10 'psql $DATABASE_URL -c "SELECT pid, phase, heap_blks_total, heap_blks_scanned FROM pg_stat_progress_vacuum WHERE relid = '\''products'\''::regclass;"'

# 6. After VACUUM completes, verify bloat is reduced and query P99 recovers
psql $DATABASE_URL -c "EXPLAIN (ANALYZE, BUFFERS) SELECT COUNT(*) FROM products WHERE category_id = 1;"
```

**Follow-up Actions:**
- Updated autovacuum runbook to require explicit re-enable step with a reminder (PR #3921)
- Set up automated alert for autovacuum being disabled for >2 hours
- Added `autovacuum = on` as a baseline config in `init_db.py` schema setup
- Pinned minimum autovacuum frequency on large tables: `autovacuum_naptime = 10s` for tables >100M rows

---

### INC-2025-0037 — Redis Persistence Disk Full Causing RDB Write Failure

**Date:** 2025-02-12 | **Severity:** P1

**Description:**
At 03:17 UTC, Redis persistence (RDB snapshot) on the primary node began a scheduled save. The `/var/lib/redis` partition on the backing storage had 2GB free space (out of 500GB total). The RDB file size was 1.8GB. The snapshot write succeeded but consumed 1.7GB, leaving only 300MB free. At 03:19, the next RDB snapshot cycle was triggered (configured for every 3,600 seconds or on 1000 key changes — the second threshold was hit). Redis attempted to write a new RDB snapshot but failed with `ENOSPC` (no space). Redis then threw an error and stopped accepting new write commands (SET, HSET, LPUSH, etc.). All cache write operations failed for 8 minutes until the incident was resolved. Read operations (GET, HGET) continued working, causing severe cache staleness.

**Impact:**
- Cache write failures for 8 minutes (03:19–03:27 UTC)
- Session updates failed (user auth tokens could not be refreshed)
- ~200 users forcibly logged out after 30 minutes of inactivity (session refresh failed)
- Price updates and inventory adjustments queued but not persisted
- All cache-write-dependent services returned 5xx errors

**Root Cause:**
Redis persistence disk was sized for steady-state RDB size (1.6GB) with only ~500MB headroom. No monitoring existed on `/var/lib/redis` free space. During a traffic spike, keyspace grew to 1.8GB. The next RDB snapshot attempt failed because free space was insufficient for a atomic write + rotate.

**Resolution:**
```bash
# 1. Confirm Redis is still running but rejecting writes
redis-cli PING
# Should return PONG
redis-cli SET test_key test_value 2>&1 | head -20
# Should show error: OOM command not allowed when used memory > maxmemory

# 2. Check Redis disk space
df -h /var/lib/redis
# Should show <500MB free (in this case 300MB)

# 3. Expand the `/var/lib/redis` partition (or migrate to larger storage)
# If using cloud storage snapshots:
kubectl scale statefulset redis --replicas=0 -n cache
# Wait for pod to terminate
# Expand the PVC to 1000GB (or as needed)
kubectl patch pvc redis-data -n cache -p '{"spec":{"resources":{"requests":{"storage":"1000Gi"}}}}'
kubectl scale statefulset redis --replicas=1 -n cache
# Wait for pod to be ready

# 4. Stop ongoing RDB snapshot writes
redis-cli BGSAVE
# If this hangs, the write is in progress. Wait or kill the background process.

# 5. Once space is freed and pod is healthy, force an RDB save
redis-cli BGSAVE
# Monitor progress
watch -n 5 'redis-cli LASTSAVE && redis-cli INFO persistence | grep -E "rdb_last_save_time|rdb_last_bgsave_status"'

# 6. Re-enable writes
redis-cli CONFIG SET stop-writes-on-bgsave-error no
# (Or restart Redis to reset to default)
```

**Follow-up Actions:**
- Increased `/var/lib/redis` partition from 500GB to 1000GB
- Added monitoring alert for `/var/lib/redis` free space <1GB (trigger page)
- Set `save ""` (disable RDB snapshots) and rely on AOF (append-only file) persistence instead
- Configured AOF rewrite threshold to trigger when AOF file exceeds 500MB
- Added runbook: "Redis RDB Expansion" documenting PVC resizing procedure

---

### INC-2024-0345 — Connection Leak in Third-Party ORM Library

**Date:** 2024-10-15 | **Severity:** P1

**Description:**
At 09:30 UTC, a new version of a third-party Python ORM library was deployed as a dependency update. The library had a known internal bug that leaked database connections under specific query patterns. The product team's new "Smart Recommendations" feature, deployed in the same release window, happened to use exactly the triggering query pattern: `ORM.filter(status='active').join(orders).filter(amount > 500).select()`. This query, executed ~50 times per second during checkout, triggered the connection leak. Each query leaked 1 connection back to the pool without properly closing it. After 4 hours (approximately 720,000 leaked connections * 1 connection leak per 50 queries = ~14,400 leaked connections accumulated), the PgBouncer connection pool (max 500 connections) became exhausted. All new database connections were rejected.

**Impact:**
- PgBouncer connection pool exhausted at 13:30 UTC
- All new API requests failed with "connection pool exhausted"
- API error rate: 100% for 45 minutes
- Checkout service completely down
- ~8,500 failed checkout attempts
- ~$2.1M GMV impact

**Root Cause:**
A third-party ORM library was updated to a version with a connection leak bug. The bug was triggered by a specific query pattern (join + filter + select) introduced in the same deploy. No connection leak testing was performed before deploying the library update.

**Resolution:**
```bash
# 1. Identify connection leak pattern in application logs
grep -i "connection leak\|pool exhausted" /var/log/app.log | tail -50
# Or check active connections by application:
psql $DATABASE_URL -c "
  SELECT application_name, COUNT(*)
  FROM pg_stat_activity
  GROUP BY application_name
  ORDER BY count DESC;"

# 2. Identify the problematic ORM library version
pip freeze | grep -i orm-library-name

# 3. Kill all idle connections to immediately restore some capacity
psql $DATABASE_URL -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE state = 'idle'
    AND state_change < now() - interval '1 minute'
    AND pid != pg_backend_pid();"

# 4. Downgrade the ORM library to the previous known-good version
pip install orm-library-name==2.3.1  # Previous version without the leak
# Rebuild application image and redeploy
kubectl rollout restart deployment/checkout-service -n ecommerce

# 5. Monitor connection count recovery
watch -n 10 'psql $DATABASE_URL -c "SELECT COUNT(*) FROM pg_stat_activity;"'
# Should drop back to <200 as old pods terminate and new pods start

# 6. Verify error rate returns to baseline
watch -n 10 'kubectl logs -l app=checkout-service -n ecommerce --tail=100 | grep -E "5[0-9]{2}|error" | wc -l'
```

**Follow-up Actions:**
- Downgraded ORM library to 2.3.1 (PR #4156)
- Added pre-deployment check: run 1000-request load test against new library versions before merging
- Added Sentry error tracking for "connection pool exhausted" alerts with severity P0
- Configured PgBouncer `client_idle_timeout = 600` to auto-close idle client connections after 10 minutes

---

### INC-2024-0511 — PgBouncer Version Incompatibility Causing Authentication Failures

**Date:** 2024-11-30 | **Severity:** P1

**Description:**
At 22:15 UTC, the infrastructure team upgraded PgBouncer from version 1.15 to 1.16 as a routine maintenance task (no major security fixes noted, just "improvements"). The upgrade was rolled out to the prod cluster without testing. PgBouncer 1.16 introduced a subtle bug in the PostgreSQL authentication protocol handler: under high connection load, approximately 10% of new connection attempts were randomly rejected with "auth failed" error, even though credentials were correct. The error was not deterministic — retrying the connection usually succeeded on the second attempt. This caused request latency spikes and intermittent 5xx errors across all API services.

**Impact:**
- ~10% of new connection attempts failed with "auth failed" (non-deterministic)
- API P99 latency spiked from 200ms to 4s (due to connection retry logic)
- API error rate: 3–5% across all services (503 errors from timeout retries)
- Incident duration: 2 hours (22:15–00:15 UTC)
- User-facing impact: slow page loads, checkout timeouts

**Root Cause:**
PgBouncer 1.16 had an authentication protocol bug that manifested under high load. The bug was not caught in the release notes or security advisories. No canary or staging test was performed before the prod rollout.

**Resolution:**
```bash
# 1. Confirm PgBouncer version and auth errors in logs
kubectl exec -it deployment/pgbouncer-0 -n ecommerce -- pgbouncer --version
# Output: pgbouncer 1.16

# Check logs for auth failures
kubectl logs deployment/pgbouncer -n ecommerce | grep -i "auth" | tail -50

# 2. Downgrade PgBouncer to the previous stable version
# Update the deployment image tag in the Helm values or Dockerfile:
# Change: pgbouncer:1.16 → pgbouncer:1.15.2-debian
# Then redeploy:
helm upgrade pgbouncer ./helm/pgbouncer -f helm/values.yaml \
  --set pgbouncer.image.tag=1.15.2-debian -n ecommerce

# Wait for rollout to complete
kubectl rollout status deployment/pgbouncer -n ecommerce

# 3. Verify auth errors have ceased
watch -n 5 'kubectl logs deployment/pgbouncer -n ecommerce --tail=50 | grep -i "auth" | wc -l'
# Should drop to zero or near-zero

# 4. Monitor API error rate recovery
watch -n 10 'kubectl logs -l app=catalog-api -n ecommerce --tail=100 | grep -E "5[0-9]{2}" | wc -l'
# Should return to baseline (<1% error rate)

# 5. Verify connection pool health
psql $DATABASE_URL -c "
  SELECT client_addr, state, COUNT(*)
  FROM pg_stat_activity
  GROUP BY client_addr, state
  ORDER BY count DESC;"
```

**Follow-up Actions:**
- Downgraded PgBouncer to 1.15.2 (Pin in Helm values)
- Added pre-deployment testing: all infrastructure component upgrades must be tested in staging for 24 hours before prod rollout
- Disabled auto-upgrade of PgBouncer; now requires explicit approval
- Added monitoring alert for "auth failed" errors from PgBouncer (threshold: >10 in 5 minutes)

---

## Failure Mode Catalog

### Connection Pool Exhaustion (PgBouncer Saturation)

**Symptoms:**
- Applications report: `remaining connection slots are reserved for non-replication superuser connections`
- `psql` connections hang indefinitely at connect time
- API error rate spikes across all services
- `psql $DATABASE_URL -c "SELECT COUNT(*) FROM pg_stat_activity;"` returns a value near `max_connections` (500)

**Diagnosis:**
```sql
-- Break down connections by state to identify the problem type
SELECT state, COUNT(*)
FROM pg_stat_activity
GROUP BY state
ORDER BY count DESC;
```
A large count of `idle` connections indicates connection leaks (application not returning connections to the pool). A large count of `idle in transaction` indicates transactions not being committed or rolled back — these may be holding locks.

**Resolution:**

Kill idle connections (safest — no active queries affected):
```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle'
  AND state_change < now() - interval '1 minute'
  AND pid != pg_backend_pid();
```

Kill idle-in-transaction connections (may be holding locks — confirm with app team first):
```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND query_start < now() - interval '5 minutes';
```

If killing connections does not relieve pressure, restart PgBouncer:
```bash
kubectl rollout restart deployment/pgbouncer -n ecommerce
```

**Escalate if:** Killing idle connections does not relieve pressure. The primary DB may need a connection limit increase, or there may be a connection leak requiring an application-level fix.

---

### Replication Slot Lag Bloat (WAL Accumulation)

**Symptoms:**
- Primary disk usage growing rapidly and unexpectedly
- `df -h /var/lib/postgresql` shows unusual growth in the data directory
- A replication slot shows `active=false` in `pg_replication_slots`
- Monitoring alerts on primary disk utilization

**Diagnosis:**
```sql
-- Check all replication slots and their WAL lag
SELECT slot_name, active,
  pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS lag
FROM pg_replication_slots;
```
A large lag value on an inactive slot means WAL segments are being retained on disk waiting for a replica that is no longer consuming them.

**Resolution:**

If the replica associated with the slot is permanently decommissioned or will not reconnect, drop the slot to allow WAL cleanup:
```sql
SELECT pg_drop_replication_slot('<slot_name>');
```
WAL segments will be cleaned up on the next checkpoint cycle. If the replica is temporarily down and expected to reconnect, wait for it to reconnect before dropping the slot.

**IMPORTANT: Do not drop slots for replicas that are actively replicating.** Dropping an active slot will break replication and require a full replica resync.

**Escalate if:** Primary disk utilization exceeds 85%. Risk of the primary running out of disk and crashing entirely. Contact Data Platform lead immediately.

---

### Cache Stampede on Cold Start

**Symptoms:**
- Occurs after a Redis restart, rolling restart, or intentional cache flush
- DB CPU spikes to 100% immediately after Redis becomes available
- API latency rises significantly
- Redis keyspace hit rate near 0% (`redis-cli INFO stats | grep keyspace_hits`)
- DB active connection count spikes

**Diagnosis:**
```bash
# Check Redis miss rate
redis-cli INFO stats | grep keyspace_misses

# Check concurrent active DB queries
psql $DATABASE_URL -c "SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active';"
```
If misses are very high and DB active connections are elevated, a stampede is in progress.

**Resolution:**
1. Enable stampede protection on affected services (probabilistic early recomputation):
   ```bash
   kubectl set env deployment/catalog-api deployment/checkout-service \
     CACHE_STAMPEDE_PROTECTION=true -n ecommerce
   ```
2. Scale read replicas to absorb the elevated DB read load:
   ```bash
   kubectl scale deployment/db-replica-2 --replicas=2 -n ecommerce
   ```
3. Allow 5–10 minutes for the cache to warm naturally. Do not force a bulk pre-warm — this can itself cause a write storm.
4. Once Redis hit rate recovers above 80%, disable stampede protection:
   ```bash
   kubectl set env deployment/catalog-api deployment/checkout-service \
     CACHE_STAMPEDE_PROTECTION=false -n ecommerce
   ```

**Escalate if:** DB connections become fully exhausted during warmup. May need to temporarily throttle inbound application traffic to prevent complete DB saturation.

---

### Primary Failover (Manual Promotion)

**Symptoms:**
- Primary is unreachable; all write operations failing across services
- Applications report: `could not connect to server: Connection refused`
- PgBouncer logs show repeated connection failures to primary
- All checkout and order-creation endpoints returning 5xx errors

**Diagnosis:**
```bash
# Test primary connectivity
psql -h db-primary $DATABASE_URL -c "SELECT 1;"
# If this times out or errors, the primary is down

# Check pod status
kubectl get pods -n postgres
```

**Resolution:**

1. Confirm the primary is down (do not promote prematurely — a false positive triggers a split-brain scenario)
2. Identify the most up-to-date replica by comparing LSN positions:
   ```bash
   psql -h db-replica-1 $DATABASE_URL -c "SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn();"
   psql -h db-replica-2 $DATABASE_URL -c "SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn();"
   ```
   Promote the replica with the higher `replay_lsn`.
3. Promote the selected replica:
   ```bash
   kubectl exec -it postgres-replica-1 -n postgres -- \
     pg_ctl promote -D /var/lib/postgresql/data
   ```
4. Verify promotion succeeded (`pg_is_in_recovery()` must return `false`):
   ```sql
   SELECT pg_is_in_recovery();
   ```
5. Update application `DATABASE_URL` environment variables:
   ```bash
   kubectl set env deployment/checkout-service deployment/catalog-api \
     DATABASE_URL=postgresql://user:pass@db-replica-1:5432/opsrelay -n ecommerce
   ```
6. Update PgBouncer to point to the new primary and restart:
   ```bash
   # Edit pgbouncer.ini: update host= in the [databases] section to db-replica-1
   kubectl rollout restart deployment/pgbouncer -n ecommerce
   ```
7. Notify the Data Platform team to rebuild the failed primary as a new standby replica.

**Escalate if:** Both primary and replica-1 are unreachable. Contact Data Platform lead immediately — this constitutes a critical data availability emergency.

---

## Runbook Procedures

### Procedure: Emergency Connection Pool Flush

Use when PgBouncer is saturated or DB connections are exhausted. This procedure frees connections without restarting the database.

**Step 1 — Kill idle connections (safest, no active queries affected):**
```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle'
  AND state_change < now() - interval '1 minute'
  AND pid != pg_backend_pid();
```

**Step 2 — Kill idle-in-transaction connections (may be holding locks; confirm with app team before running):**
```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND query_start < now() - interval '5 minutes';
```

**Step 3 — If connections do not free up, restart PgBouncer:**
```bash
kubectl rollout restart deployment/pgbouncer -n ecommerce
```
PgBouncer will re-establish its pool against the primary. Expect a brief (<5s) connectivity blip.

**Step 4 — Verify the pool is freed:**
```bash
psql $DATABASE_URL -c "SELECT COUNT(*) FROM pg_stat_activity;"
# Should be well below max_connections (500)
```

---

### Procedure: Promote Read Replica to Primary

Use when the primary PostgreSQL instance is down and cannot be recovered within the RTO. This is a destructive, one-way operation — the promoted replica becomes the new primary and cannot be reverted without data loss risk.

**Step 1 — Confirm the primary is genuinely down:**
```bash
psql -h db-primary $DATABASE_URL -c "SELECT 1;"
# Must timeout or return a connection error — not just a slow response
```

**Step 2 — Identify the most up-to-date replica:**
```bash
psql -h db-replica-1 $DATABASE_URL -c \
  "SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn();"
psql -h db-replica-2 $DATABASE_URL -c \
  "SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn();"
```
Select the replica with the higher `replay_lsn` to minimize data loss.

**Step 3 — Promote the selected replica:**
```bash
kubectl exec -it postgres-replica-1 -n postgres -- \
  pg_ctl promote -D /var/lib/postgresql/data
```

**Step 4 — Verify promotion:**
```bash
psql -h db-replica-1 $DATABASE_URL -c "SELECT pg_is_in_recovery();"
# Must return: f (false)
```

**Step 5 — Update all application DATABASE_URL env vars:**
```bash
kubectl set env deployment/checkout-service deployment/catalog-api \
  DATABASE_URL=postgresql://user:pass@db-replica-1:5432/opsrelay -n ecommerce
```

**Step 6 — Update PgBouncer config and restart:**
```bash
# Edit pgbouncer.ini: change host= in [databases] section to db-replica-1
kubectl rollout restart deployment/pgbouncer -n ecommerce
```

**Step 7 — Notify Data Platform team** to rebuild the failed original primary as a new streaming replica of the promoted node.

---

### Procedure: Add Index Concurrently Without Table Lock

Use when a missing index is causing slow queries in production. `CREATE INDEX CONCURRENTLY` builds the index without blocking writes to the table.

**Step 1 — Confirm the query is slow and identify the missing index:**
```sql
EXPLAIN (ANALYZE, BUFFERS) <slow_query_here>;
-- Look for "Seq Scan" on a large table in the output
-- If the table has millions of rows and no filter index, an index is needed
```

**Step 2 — Create the index concurrently (runs in background; writes are not blocked):**
```sql
CREATE INDEX CONCURRENTLY idx_<table>_<column>
ON <table>(<column>);
```
Note: `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block. If you are connected via psql, ensure `\echo :AUTOCOMMIT` shows `on`.

**Step 3 — Monitor index build progress:**
```sql
SELECT phase, blocks_done, blocks_total,
  round(100.0 * blocks_done / nullif(blocks_total, 0), 1) AS pct_complete
FROM pg_stat_progress_create_index
WHERE relid = '<table>'::regclass;
```
For a 230M-row table, expect approximately 4–8 minutes. The query returns no rows when the build is complete.

**Step 4 — Verify the index was created and the query uses it:**
```sql
EXPLAIN <slow_query>;
-- Should now show "Index Scan using idx_<table>_<column>" instead of "Seq Scan"
```

**Step 5 — Add the index to the schema baseline** by opening a PR to add the `CREATE INDEX` statement to `init_db.py` (or the migrations directory). An index that exists only in production will be lost on the next `--drop` reset.

---

### Procedure: Emergency Redis Flush (Cache Only, Not Sessions)

Use when Redis contains corrupt or poisoned cache data that must be purged immediately. This procedure targets only cache key namespaces. **Do NOT run `FLUSHALL` or `FLUSHDB`** — those commands also destroy session data (logging out all active users), rate limiter state, and feature flags.

**Step 1 — Verify the scope of affected keys before deleting:**
```bash
redis-cli --scan --pattern "product:*" | wc -l
redis-cli --scan --pattern "price:*" | wc -l
redis-cli --scan --pattern "inventory:*" | wc -l
```

**Step 2 — Flush product cache:**
```bash
redis-cli --scan --pattern "product:*" | xargs redis-cli DEL
```

**Step 3 — Flush price cache:**
```bash
redis-cli --scan --pattern "price:*" | xargs redis-cli DEL
```

**Step 4 — Flush inventory cache:**
```bash
redis-cli --scan --pattern "inventory:*" | xargs redis-cli DEL
```

**Step 5 — Confirm session keys are intact:**
```bash
redis-cli --scan --pattern "session:*" | wc -l
# Should be non-zero if users are active; zero would indicate sessions were accidentally flushed
```

**Step 6 — Monitor cache miss rate and DB load during warmup:**
```bash
watch -n 10 'redis-cli INFO stats | grep -E "keyspace_hits|keyspace_misses"'
```
Expect 5–10 minutes of elevated DB query volume while the cache re-warms. Monitor DB connection counts and be prepared to execute the Emergency Connection Pool Flush procedure if DB connections saturate.

---

## Monitoring & Alerts

| Alert | Threshold | Meaning | First Response |
|---|---|---|---|
| `db.connections_pct` | >80% for 2 min | PgBouncer pool filling up | Kill idle connections; check for connection leaks in application logs |
| `db.replica_lag_seconds` | >30s any replica | Replica falling behind primary | Check for long-running queries on the lagging replica; route reads to primary if lag >5s |
| `db.query_p99_ms` | >500ms for 3 min | Slow queries degrading service | Check `pg_stat_activity` for blocking or long-running queries |
| `redis.memory_pct` | >70% for 5 min | Redis approaching memory limit | Increase `maxmemory`; audit TTLs for bloated keys |
| `redis.evicted_keys_per_sec` | >100 | Redis evicting hot cache keys | Scale `maxmemory` immediately; check for traffic surge |
| `pgbouncer.pool_saturation` | >90% | Connection pool nearly full | Kill idle connections; restart PgBouncer if unresponsive |
| `db.primary_reachable` | false | Primary DB unreachable | Begin failover procedure immediately; page `data-platform-oncall` |

**Dashboards:**
- DB Overview: connection count by state, query P50/P95/P99, replication lag per replica
- Redis Overview: memory utilization per node, eviction rate, hit/miss ratio, key count by namespace
- PgBouncer: pool utilization, client wait time, server connection count

---

## Escalation Policy

**Severity Definitions:**

| Severity | Conditions |
|---|---|
| P0 | Primary DB down; DB connection pool 100% exhausted (complete write failure); Redis cluster down |
| P1 | DB write P99 >500ms sustained; replication lag >5 minutes; Redis eviction storm cascading to DB; checkout error rate >5% |
| P2 | Read replica lag 30s–5min; Redis memory >80%; slow queries >500ms not yet causing user-facing failures |
| P3 | Non-urgent: index optimization opportunities, minor cache hit rate degradation, non-urgent capacity planning |

**Escalation Tiers:**

**P0 — Immediate:**
1. Page `data-platform-oncall` immediately via PagerDuty
2. Page `platform-oncall` — all application services depend on the database
3. Notify CTO within 5 minutes of P0 declaration
4. Post status update to `#incidents` every 5 minutes until resolved

**P1 — Urgent:**
1. Page `data-platform-oncall` via PagerDuty
2. Escalate to `platform-oncall` if end-user-facing services are impacted (checkout failures, elevated 5xx rates)
3. Post initial status update to `#incidents` at incident start; post resolution update when resolved

**P2/P3 — Non-urgent:**
1. Post to `#data-platform` Slack channel during business hours (09:00–18:00 local)
2. Create a ticket in the Data Platform backlog with observed metrics attached
3. No PagerDuty page required

**Communication Template (P0):**
```
[P0 INCIDENT - Database & Cache]
Status: INVESTIGATING
Impact: [Primary DB down / Connection pool exhausted / Redis cluster down]
API error rate: [X]%
What we know: [1 sentence describing root cause hypothesis]
Failover status: [not started / in progress / complete]
Next update: [HH:MM UTC]
```
Post this template as the first message in `#incidents` at incident declaration. Update it in-thread every 5 minutes. Pin the thread at incident start and unpin at resolution.

---

## Inter-Service Impact Map

When Database & Cache degrades, the cascade looks like:

| Stage | Service | Impact | Time to Detect |
|---|---|---|---|
| Immediate | DB/Redis | reads slow or fail, cache misses storm | <1 min |
| +2 min | all API services | handlers block waiting for DB, request timeouts | +2 min |
| +5 min | api-gateway | connection pool saturated, new requests queued | +5 min |
| +10 min | checkout-service | checkout P99 >10s, error rate spikes | +10 min |

**How to read this:** DB/cache degradation is the root of almost all cascades. It's foundational.

**Isolation actions:** DB circuit breaker: after 3 consecutive query timeouts, return cached data (even if stale). Scale read replicas. Disable non-critical writes (analytics, reporting).

---

## Rollback Decision Tree

**When to rollback vs. hotfix:**

1. **DB connection pool >80% for >2 minutes?**
   - **YES** → Kill idle connections first. If persists, scale read replicas. Rollback only if recent deploy introduced connection leak.
   - **NO** → Proceed to step 2

2. **Query P99 >500ms sustained?**
   - **YES** → If from recent deploy, rollback. If data volume issue, hotfix (e.g., add index).
   - **NO** → Proceed to step 3

3. **Replication lag >30 seconds?**
   - **YES** → Check for long-running queries on replica. Kill if necessary. Escalate if primary is down.
   - **NO** → Wait and monitor

**Quick rollback command:**
```bash
kubectl rollout undo deployment/api-service -n ecommerce
# If connection pool issue, also kill idle connections:
psql $DATABASE_URL -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state='idle' AND state_change < now() - interval '1 minute';"
```

**Verification after rollback:**
- Connection pool usage <50%
- Query P99 <200ms
- Replication lag <500ms
- No new connection errors in logs
