# Product Catalog Runbook

## Service Overview

**Service:** Product Catalog (catalog-api)
**Owner:** Catalog Platform team
**PagerDuty:** catalog-platform-oncall
**On-call rotation:** 1-week rotations, escalates to Search Infra team for ES cluster issues

### Architecture

The Product Catalog system is a three-tier distributed service:

```
catalog-api (FastAPI, 3 replicas)
  ↓ reads/writes
PostgreSQL (source of truth for products, inventory, pricing)
  ↑
Elasticsearch 8.x (search index, 3-node cluster: es-master, es-data-1, es-data-2)
  ↑
Redis (cache layer: prices, inventory, search facets, TTL 60s)
  ↑
reindex-worker (async service, currently 2 replicas)
  └→ Watches PostgreSQL changelog queue, re-indexes Elasticsearch asynchronously
```

**Key flow:**
1. Product create/update → PostgreSQL → Changelog queue
2. reindex-worker polls changelog → formats documents → writes to Elasticsearch `products_live` alias
3. catalog-api search requests hit Elasticsearch, cache hits on Redis
4. catalog-api inventory/price reads check Redis first, fallback to PostgreSQL with write-through cache

### Key Dependencies

- **Elasticsearch 8.x cluster** (3-node): primary constraint for latency SLOs
- **PostgreSQL 15** (RDS multi-AZ): source of truth, replication lag monitors
- **Redis 7.0 cluster** (3 nodes): cache coherency critical, eviction policy must be `allkeys-lru`
- **reindex-worker** (Celery/Python): changelog consumer, indexing throughput bottleneck

### SLOs & Targets

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Search P99 latency | <200ms | >250ms for 5 min |
| Inventory read P99 | <50ms | >100ms for 5 min |
| Catalog availability | 99.99% | <99.90% in any 5-min window |
| Index lag (doc count %) | <2% | >5% for 10 min |
| Redis cache hit rate | >85% | <75% for 10 min |

---

## Recorded Incidents

### INC-2024-0198 — Search Index Corruption During Reindex

**Severity:** P1
**Date:** 2024-09-22
**Duration:** 14 minutes
**Status:** Resolved + Follow-up Complete

#### Description

A zero-downtime reindex operation was in progress to apply new field mappings. The reindex job created index `products_v42` and began populating it from PostgreSQL. At 34% completion, a misconfigured deployment script prematurely swapped the `products_live` alias from `products_v41` to `products_v42` via the Elasticsearch aliases API.

Live search traffic (averaging 12k req/sec) was immediately routed to the incomplete index. Customers experienced:
- 38% of search queries returned empty results
- 21% returned wrong/outdated products
- Zero-result rates spiked from 0.1% baseline to 38.2%

The incident was detected by automated alerts on zero-result rate and manually discovered during customer escalations.

#### Impact

- **User impact:** ~4,500 search queries failed or returned wrong results over 14 minutes
- **Business impact:** Estimated 18–24 lost order attempts, ~$3,200 estimated revenue
- **Severity:** P1 (search is critical path for browsing)

#### Root Cause

1. **Inadequate pre-swap validation:** The reindex orchestration script did not check Elasticsearch cluster health or index health status before swapping aliases.
2. **Missing doc count drift check:** No validation that the target index had ingested ≥95% of source documents before swap.
3. **Manual alias management:** Aliases were swapped via ad-hoc curl commands in a CI/CD step, not idempotent.

#### Resolution Steps

**Immediate (minute 0–2):**
1. Received alert: "search zero-result rate >30%"
2. Checked Elasticsearch index stats:
   ```bash
   curl -s "http://elasticsearch:9200/_cat/indices?v" | grep products_v
   ```
   Output showed `products_v42` with 8.2M docs (target: 24M docs — only 34%).

3. **Swap alias back immediately:**
   ```bash
   curl -X POST "http://elasticsearch:9200/_aliases" \
     -H "Content-Type: application/json" \
     -d '{
       "actions": [
         {"remove": {"index": "products_v42", "alias": "products_live"}},
         {"add": {"index": "products_v41", "alias": "products_live"}}
       ]
     }'
   ```

4. Verified alias swap completed:
   ```bash
   curl -s "http://elasticsearch:9200/_alias/products_live" | jq '.[] | keys'
   ```
   Confirmed `products_v41` is now live alias.

5. **Rolled back catalog-api deployment** to previous version to clear any cached index metadata:
   ```bash
   kubectl rollout undo deployment/catalog-api -n ecommerce
   kubectl rollout status deployment/catalog-api -n ecommerce
   ```

**Short-term (minute 2–5):**
6. Monitored zero-result rate recovery:
   ```bash
   # Via Prometheus (substitute your dashboard)
   curl -G http://prometheus:9090/api/v1/query_range \
     --data-urlencode 'query=rate(search_zero_results_total[1m])' \
     --data-urlencode 'start=1727000000' \
     --data-urlencode 'end=1727001000' \
     --data-urlencode 'step=10'
   ```
   Zero-result rate dropped to <2% within 90 seconds of alias swap.

7. **Deleted incomplete index** to prevent future confusion:
   ```bash
   curl -X DELETE "http://elasticsearch:9200/products_v42"
   ```

8. **Killed the reindex-worker job** that was still writing to the now-removed index:
   ```bash
   kubectl delete job/reindex-job-2024-09-22-abc123 -n ecommerce
   ```

**Recovery (minute 5–60):**
9. **Restarted reindex cleanly** with fixed deployment script:
   ```bash
   kubectl apply -f k8s/reindex-job.yaml -n ecommerce
   # Monitor progress
   kubectl logs -f job/reindex-job-2024-09-22-fixed -n ecommerce
   ```

10. **Validated index quality before next swap:**
    ```bash
    # Check doc count matches source
    curl -s "http://elasticsearch:9200/products_v43/_count" | jq .count
    # Should match: SELECT COUNT(*) FROM products;
    psql -h $RDS_ENDPOINT -d ecommerce -c "SELECT COUNT(*) FROM products;"

    # Check cluster health
    curl -s "http://elasticsearch:9200/_cluster/health" | jq '.status'
    # Must be "green" before swap
    ```

11. **Verified no data inconsistency** between PostgreSQL and Elasticsearch:
    ```bash
    # Sample 100 random product IDs from Elasticsearch
    curl -s "http://elasticsearch:9200/products_v41/_search?q=*&size=100" | jq '.hits.hits[].fields.product_id' > es_sample.txt
    # Cross-check against PostgreSQL
    psql -h $RDS_ENDPOINT -d ecommerce -c "SELECT id FROM products WHERE id IN (SELECT unnest(string_to_array($(cat es_sample.txt | tr '\n' ','), ',')));"
    ```

#### Follow-up Actions

**Completed:**
1. **Gated alias swap logic** in reindex orchestrator (`backend/jobs/reindex_orchestrator.py`):
   - Check ES cluster health == "green"
   - Verify target index health == "green"
   - Verify doc count within 1% of PostgreSQL source before swap
   - Implemented as reusable step in reindex-worker

2. **Added monitoring dashboard** for reindex progress:
   - Index creation time vs. estimated ingestion time
   - Real-time doc count drift warning (alerts if >2% behind)
   - Replica sync status before swap approval

3. **Wrote automated reindex test** (`tests/integration/test_reindex_safety.py`):
   - Creates test index with 1k docs
   - Validates alias swap gates
   - Ensures zero-result rate remains <1%

---

### INC-2024-0331 — Inventory Oversell During Flash Sale

**Severity:** P1
**Date:** 2024-12-12
**Duration:** 8 minutes
**Status:** Resolved + Monitoring Enhanced

#### Description

A flash sale promotion launched with limited inventory (500 units) for a high-demand product (gaming GPU). The product inventory was cached in Redis with default TTL of 60 seconds. At sale start, Redis was queried by the storefront and returned 500 units.

Within 8 minutes, the inventory in PostgreSQL was decremented to 0 units (500 orders placed). However, Redis still served the original 500-unit value to newly arriving customers due to TTL overlap. During this window:
- Customer 1 placed order: DB reads 0, Redis reads 213 → order accepted
- Customers 2–214 similarly placed orders reading stale cache
- 214 additional orders were processed against non-existent inventory

The incident was discovered when orders exceeded available stock and the fulfillment team flagged it.

#### Impact

- **Orders oversold:** 214 units (43% above limit)
- **Refunds issued:** 214 orders, ~$18,400 cost
- **Fulfillment delay:** Partial shipments, customer support escalation
- **Reputation:** ~12 negative social media posts from affected customers

#### Root Cause

1. **Write-through cache invalidation not implemented:** When inventory decremented in PostgreSQL, the cache was not invalidated. Only natural TTL expiration (60s) cleared stale data.
2. **TTL too long for flash sales:** 60-second TTL assumes gradual sales rate. During flash sale (12 orders/sec), cache becomes unreliable within 10 seconds.
3. **No flash-sale-mode:** System lacked a way to dynamically adjust cache behavior for high-urgency inventory.

#### Resolution Steps

**Immediate (minute 0–2):**
1. Detected via alert: "Inventory variance >10%"
   ```bash
   # Checked actual inventory in DB
   psql -h $RDS_ENDPOINT -d ecommerce -c \
     "SELECT product_id, quantity FROM inventory WHERE product_id = 'GPU-RTX-4090' AND quantity < 0;"
   ```
   Output: quantity = -214

2. **Emergency inventory lock** — disabled all inventory decrements for this product:
   ```bash
   # Connect to Redis and set override flag
   redis-cli -h $REDIS_HOST -p 6379 \
     SET inventory:lock:GPU-RTX-4090 '{"reason":"oversell-incident","timestamp":"2024-12-12T14:32:00Z","locked":true}' EX 86400

   # Confirm lock is set
   redis-cli -h $REDIS_HOST -p 6379 GET inventory:lock:GPU-RTX-4090
   ```

3. **Purged stale cache** for affected product:
   ```bash
   redis-cli -h $REDIS_HOST -p 6379 DEL inventory:GPU-RTX-4090
   redis-cli -h $REDIS_HOST -p 6379 DEL inventory:pricing:GPU-RTX-4090
   redis-cli -h $REDIS_HOST -p 6379 DEL inventory:cache:GPU-RTX-4090
   ```

4. **Switched inventory reads to DB** with short TTL via environment variable:
   ```bash
   kubectl set env deployment/catalog-api \
     INVENTORY_CACHE_TTL_SECONDS=5 \
     INVENTORY_FORCE_DB_READ=true \
     -n ecommerce

   kubectl rollout status deployment/catalog-api -n ecommerce
   ```

5. **Validated DB consistency** and halted new orders:
   ```bash
   psql -h $RDS_ENDPOINT -d ecommerce -c \
     "SELECT COUNT(*) FROM orders WHERE product_id = 'GPU-RTX-4090' AND status = 'pending' ORDER BY created_at DESC LIMIT 214;"
   ```

**Short-term (minute 2–30):**
6. **Refund all oversold orders** (automated + manual):
   ```bash
   # Mark 214 orders for refund
   psql -h $RDS_ENDPOINT -d ecommerce -c \
     "UPDATE orders SET status = 'refunded', refund_reason = 'oversell-incident' \
      WHERE product_id = 'GPU-RTX-4090' AND created_at > '2024-12-12T14:32:00Z' \
      AND id NOT IN (SELECT order_id FROM order_fulfillment WHERE status = 'shipped');"

   # Trigger refund processing
   curl -X POST http://catalog-api:8000/admin/refunds/batch \
     -H "Content-Type: application/json" \
     -d '{"incident_id":"INC-2024-0331","dry_run":false}'
   ```

7. **Unlocked inventory** once cache was safely rebuilt:
   ```bash
   redis-cli -h $REDIS_HOST -p 6379 DEL inventory:lock:GPU-RTX-4090
   kubectl set env deployment/catalog-api \
     INVENTORY_CACHE_TTL_SECONDS=60 \
     INVENTORY_FORCE_DB_READ=false \
     -n ecommerce
   ```

**Recovery (minute 30+):**
8. **Analyzed root cause** and updated cache invalidation strategy:
   - Implemented write-through cache invalidation in `backend/app/services/inventory.py`
   - Added `cache.invalidate_on_decrement()` hook to inventory writes

#### Follow-up Actions

**Completed:**
1. **Implemented write-through cache invalidation:**
   - When `inventory.decrement(product_id, qty)` is called, immediately delete Redis key
   - Replaced with explicit TTL-based re-population on reads
   - Verified in prod: oversell test now fails as expected

2. **Added flash-sale-mode** with dynamic TTL:
   ```python
   # In catalog-api, detect active promotions and adjust cache behavior
   if is_active_flash_sale(product_id):
       INVENTORY_CACHE_TTL = 5  # seconds
       INVENTORY_BYPASS_CACHE = False  # still use cache, but very short
   else:
       INVENTORY_CACHE_TTL = 60  # default
   ```

3. **Monitoring alerts:**
   - Alert if inventory variance (DB count vs. orders) exceeds 5 units for any product
   - Alert if cache eviction rate spikes (sign of stampede)
   - Alert if Redis key TTL expires without being re-queried (sign of abandoned cache)

4. **Documentation:**
   - Added flash-sale pre-flight checklist (low cache TTL required)
   - Updated inventory procedure in this runbook

---

### INC-2025-0071 — Price Update Propagation Lag

**Severity:** P2
**Date:** 2025-03-08
**Duration:** 4 hours 15 minutes (queue drain)
**Status:** Resolved

#### Description

A bulk price update was requested for 120,000 products across a catalog refresh. The update enqueued 120k changelog messages into the reindex-worker task queue. The reindex-worker deployment had 2 replicas and was processing changes single-threaded (one changelog item per worker per time).

Queue buildup occurred immediately. At peak, the queue had 98k pending items with an effective throughput of ~8 items/sec. Customers browsed products and saw old (lower) prices cached in Redis and stale in Elasticsearch. Approximately 218 orders were placed at below-market prices, with ~$4,200 in lost margin.

The incident was detected by:
1. Queue depth alert (>50k pending items)
2. Pricing API latency spike (fallback to slow DB queries)
3. Manual customer escalation ("why is product X cheaper in our app?")

#### Impact

- **Orders at wrong price:** 218 orders at ~$19.27 avg. discount = ~$4,200 lost margin
- **Queue drain time:** 4 hours 15 minutes (manual scaling required to reduce to 40 min)
- **Customer service:** 23 support tickets from price mismatch complaints
- **Reputation:** Minor; customers generally happy with lower prices

#### Root Cause

1. **Insufficient reindex-worker capacity:** Only 2 replicas for potentially large bulk updates
2. **Single-threaded changelog processing:** Each pod processed one changelog item sequentially, not in batches
3. **No priority queue:** All changelog items (product images, descriptions, prices) processed in FIFO order, but prices are more time-sensitive
4. **Manual scaling required:** No auto-scaling based on queue depth

#### Resolution Steps

**Immediate (minute 0–5):**
1. Detected alert: "reindex_queue_depth > 50000"
   ```bash
   # Checked queue depth
   redis-cli -h $REDIS_HOST LLEN changelog:queue
   # Output: 98234 items pending
   ```

2. **Checked current worker throughput:**
   ```bash
   kubectl logs -f deployment/catalog-reindex-worker -n ecommerce --tail=50 | grep "processed"
   # Output: ~8 items/sec, ETA to clear = 3.4 hours
   ```

3. **Scaled reindex-worker to 8 replicas** to increase parallelism:
   ```bash
   kubectl scale deployment/catalog-reindex-worker --replicas=8 -n ecommerce
   kubectl rollout status deployment/catalog-reindex-worker -n ecommerce
   ```

4. **Monitored queue drain rate:**
   ```bash
   # Watch queue depth decline
   while true; do
     depth=$(redis-cli -h $REDIS_HOST LLEN changelog:queue)
     echo "$(date): Queue depth = $depth"
     sleep 30
   done
   ```
   Queue decreased from 98k → 50k in 12 minutes, fully drained in 40 minutes.

**Short-term (minute 5–50):**
5. **Flushed stale price cache** to ensure customers see DB values:
   ```bash
   # Purge all pricing keys from Redis
   redis-cli -h $REDIS_HOST --scan --pattern "pricing:*" | xargs redis-cli DEL
   ```

6. **Monitored pricing API latency** to confirm recovery:
   ```bash
   # Via monitoring dashboard or Prometheus
   curl -G http://prometheus:9090/api/v1/query \
     --data-urlencode 'query=histogram_quantile(0.99, catalog_pricing_read_duration_seconds)' | jq '.data.result[0].value'
   ```
   P99 latency dropped from 580ms (DB fallback) to 45ms (cache hit) after queue cleared.

**Post-incident (hour 4+):**
7. **Verified order pricing** was consistent with market rates:
   ```bash
   psql -h $RDS_ENDPOINT -d ecommerce -c \
     "SELECT COUNT(*), AVG(price_paid) FROM orders WHERE created_at > '2025-03-08T10:00:00Z';"
   # Confirmed: prices below $18 were from orders during incident
   ```

8. **Scaled reindex-worker back to 2 replicas** once queue cleared:
   ```bash
   kubectl scale deployment/catalog-reindex-worker --replicas=2 -n ecommerce
   ```

#### Follow-up Actions

**Completed:**
1. **Implemented priority queue lanes** in changelog processor:
   - High priority: price and inventory changes (1-min SLA)
   - Low priority: description, image, metadata changes (1-hour SLA)
   - Separate queue lanes with weighted worker allocation

2. **Added horizontal autoscaling:**
   ```yaml
   # In k8s/catalog-reindex-worker-hpa.yaml
   apiVersion: autoscaling/v2
   kind: HorizontalPodAutoscaler
   metadata:
     name: catalog-reindex-worker-autoscaling
   spec:
     scaleTargetRef:
       apiVersion: apps/v1
       kind: Deployment
       name: catalog-reindex-worker
     minReplicas: 2
     maxReplicas: 16
     metrics:
     - type: External
       external:
         metric:
           name: changelog_queue_depth
         target:
           type: AverageValue
           averageValue: "5000"  # scale up if avg queue > 5k items per pod
   ```

3. **Batch changelog processing:** Increased throughput from 8 items/sec to 120 items/sec by processing batches of 20 in parallel

4. **Monitoring:**
   - Alert if queue depth exceeds 10k items
   - Alert if price propagation lag exceeds 5 minutes (Elasticsearch doc vs. PostgreSQL timestamp)

---

## Failure Mode Catalog

### Failure Mode 1: Elasticsearch Split-Brain (Cluster Red, No Primary Shards)

**Symptoms:**
- Cluster health endpoint returns `"status": "red"`
- No primary shards assigned: `"active_primary_shards": 0`
- Search requests timeout or return connection errors
- Elasticsearch logs show "master node is no longer alive"

**Root causes:**
- Network partition between nodes (e.g., EC2 security group misconfiguration)
- Disk space exhausted on master node (ES pauses writes; cluster quorum lost)
- Java heap exhaustion on a master node (GC pauses >30s, node dropped)
- Misconfigured minimum_master_nodes (should be `(n/2)+1` for n nodes)

**Diagnosis:**
```bash
# Check cluster health
curl -s http://elasticsearch:9200/_cluster/health | jq '{status,active_primary_shards,active_shards,relocating_shards}'

# List all nodes and their status
curl -s http://elasticsearch:9200/_cat/nodes?v

# Check for node disconnections in logs
kubectl logs -n ecommerce sts/elasticsearch | grep -i "disconnected\|removed\|dropped"

# Check disk usage on each node
curl -s http://elasticsearch:9200/_cat/allocation?v

# Inspect index allocation explanation (why shards aren't assigned)
curl -s http://elasticsearch:9200/_cluster/allocation/explain | jq '.allocations[] | {index,shard,primary,current_node,node_allocation_attempt}'
```

**Recovery steps:**

1. **Verify network connectivity** between Elasticsearch pods:
   ```bash
   # SSH into a pod and ping other nodes
   kubectl exec -it pod/elasticsearch-0 -n ecommerce -- bash
   ping elasticsearch-1.elasticsearch-headless
   ping elasticsearch-2.elasticsearch-headless
   ```

2. **Check disk space** on all nodes:
   ```bash
   kubectl exec -it sts/elasticsearch -n ecommerce -- df -h | grep /data
   # If full (>85%), delete old indices or expand PVC

   # Delete non-critical indices if out of space
   curl -X DELETE http://elasticsearch:9200/logs-*-old
   ```

3. **Force cluster bootstrap** (nuclear option, only if >1 node is permanently gone):
   ```bash
   # Mark a node as master-eligible for re-election
   curl -X POST http://elasticsearch:9200/_cluster/voting_config_exclusions?node_names=elasticsearch-2
   # Then delete/restart the broken node
   kubectl delete pod elasticsearch-2 -n ecommerce

   # Wait for cluster to stabilize
   kubectl wait --for=condition=Ready pod/elasticsearch-2 -n ecommerce --timeout=5m

   # Check health
   curl -s http://elasticsearch:9200/_cluster/health
   ```

4. **Reallocate shards** if stuck in unassigned state:
   ```bash
   # Explicitly assign replicas
   curl -X POST http://elasticsearch:9200/_cluster/reroute \
     -H "Content-Type: application/json" \
     -d '{
       "commands": [{
         "allocate_replica": {
           "index": "products_live",
           "shard": 0,
           "node": "elasticsearch-1"
         }
       }]
     }'
   ```

5. **Monitor recovery**:
   ```bash
   # Watch shard allocation in real-time
   watch -n 5 'curl -s http://elasticsearch:9200/_cat/shards | grep products_live | head -20'
   # Shards should move from UNASSIGNED → INITIALIZING → STARTED
   ```

---

### Failure Mode 2: Cache Stampede on Popular Product Page

**Symptoms:**
- Redis hit rate drops from >90% to <30%
- Massive spike in database connection count (connection pool exhausted)
- PostgreSQL CPU jumps to 90%+
- Slow query log fills with repeated `SELECT ... FROM product_details`
- API latency spikes to 1–2 seconds

**Root cause:**
- A very popular product page (e.g., viral social media link) receives 1000s of concurrent requests
- Cache miss (TTL expired, key evicted, or server restart)
- 100+ concurrent requests all hit the same cache miss simultaneously
- All requests query PostgreSQL simultaneously → query queue backlog → slow responses → thundering herd

**Diagnosis:**
```bash
# Check Redis memory and eviction
redis-cli -h $REDIS_HOST INFO memory | grep -E "used_memory|evicted_keys"
redis-cli -h $REDIS_HOST INFO stats | grep -E "keyspace_hits|keyspace_misses"

# Calculate hit rate
redis-cli -h $REDIS_HOST INFO stats | grep -E "keyspace_hits|keyspace_misses" | awk -F: '{s+=$2} END {print "Hit rate:", s[1]/(s[1]+s[2])}'

# Check database connection pool
psql -h $RDS_ENDPOINT -d ecommerce -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"

# Identify slow queries
psql -h $RDS_ENDPOINT -d ecommerce -c "SELECT query, mean_time, calls FROM pg_stat_statements WHERE mean_time > 100 ORDER BY mean_time DESC LIMIT 10;"

# Check which product is being hit
kubectl logs -n ecommerce deployment/catalog-api --tail=200 | grep "product_id" | sort | uniq -c | sort -rn | head -5
```

**Prevention & mitigation:**

1. **Cache stampede protection** — use probabilistic early revalidation (refresh cache before expiration):
   ```python
   # In catalog-api: if cache hits miss and load is high,
   # use a "lock" key to ensure only one request fetches from DB
   def get_product_with_stampede_guard(product_id):
       value = redis.get(f"product:{product_id}")
       if value:
           return json.loads(value)

       # Cache miss: use distributed lock
       lock_key = f"product:{product_id}:lock"
       if redis.set(lock_key, "1", nx=True, ex=10):  # Only one setter
           try:
               value = db.query_product(product_id)
               redis.setex(f"product:{product_id}", 60, json.dumps(value))
           finally:
               redis.delete(lock_key)
           return value
       else:
           # Another request is fetching; wait and retry
           time.sleep(0.1)
           return get_product_with_stampede_guard(product_id)
   ```

2. **Increase cache TTL for popular products:**
   ```bash
   # Identify products by view count
   psql -h $RDS_ENDPOINT -d ecommerce -c \
     "SELECT product_id, COUNT(*) as view_count FROM product_views WHERE viewed_at > NOW() - INTERVAL '1 hour' GROUP BY product_id ORDER BY view_count DESC LIMIT 100;" > /tmp/popular_products.txt

   # Set extended TTL for top 100
   cat /tmp/popular_products.txt | awk '{print $1}' | while read pid; do
       redis-cli -h $REDIS_HOST EXPIRE "product:$pid" 300  # 5 min instead of 60s
   done
   ```

3. **Scale database connections:**
   ```bash
   # Increase RDS `max_connections` parameter (requires instance restart)
   aws rds modify-db-parameter-group \
     --db-parameter-group-name ecommerce-postgres \
     --parameters "ParameterName=max_connections,ParameterValue=500,ApplyMethod=immediate"

   # Also increase PgBouncer pool size (connection proxy)
   kubectl set env deployment/pgbouncer \
     PGBOUNCER_POOL_SIZE=100 \
     -n ecommerce
   ```

4. **Implement request coalescing** (merge concurrent identical queries):
   ```bash
   # At load balancer: track request fingerprints and coalesce identical requests
   # (This is complex; often easier to just increase cache TTL + DB capacity)
   ```

---

### Failure Mode 3: Slow Reindex Blocking Write Operations

**Symptoms:**
- Reindex-worker CPU at 100% for hours
- Changelog queue depth grows unbounded (>100k items)
- New product writes are slow (enqueue only, index lag grows)
- Elasticsearch indexing request latency spikes (p99 > 1 second)
- Elasticsearch disk I/O is saturated

**Root cause:**
- Large bulk index operation (reindex or refresh) running while normal writes continue
- Elasticsearch merging segments in background; CPU + disk I/O throttle write throughput
- No backpressure mechanism to pause changelog ingestion during reindex
- Elasticsearch `index.refresh_interval` set too low (default 1s), causing frequent flush operations

**Diagnosis:**
```bash
# Check reindex-worker CPU and queue
kubectl top pod -l app=catalog-reindex-worker -n ecommerce
redis-cli -h $REDIS_HOST LLEN changelog:queue

# Check Elasticsearch indexing rate and resource usage
curl -s http://elasticsearch:9200/_cat/indices?bytes | grep products_live
curl -s http://elasticsearch:9200/_nodes/stats/indices | jq '.nodes[].indices.indexing | {index_total,index_time_in_millis}'

# Check for active merge operations (heavy I/O)
curl -s http://elasticsearch:9200/_cat/thread_pool?h=host,name,active,rejected | grep merge

# Check Elasticsearch disk I/O
kubectl exec -it pod/elasticsearch-0 -n ecommerce -- iostat -x 1 5

# Identify slow write operations
curl -s http://elasticsearch:9200/_nodes/hot_threads?threads=10 | grep -A5 "indexing"
```

**Mitigation steps:**

1. **Pause changelog ingestion** while reindex is running:
   ```bash
   # Set a flag to pause reindex-worker
   redis-cli -h $REDIS_HOST SET reindex:paused true EX 7200  # 2 hours

   # reindex-worker code checks this flag and sleeps if set
   # Changelog messages queue in Redis, not processed
   ```

2. **Increase Elasticsearch refresh_interval** to reduce flush pressure:
   ```bash
   # Temporarily increase refresh interval during reindex
   curl -X PUT http://elasticsearch:9200/products_v43/_settings \
     -H "Content-Type: application/json" \
     -d '{"settings": {"index.refresh_interval": "30s"}}'

   # Restore to normal after reindex
   curl -X PUT http://elasticsearch:9200/products_v43/_settings \
     -H "Content-Type: application/json" \
     -d '{"settings": {"index.refresh_interval": "1s"}}'
   ```

3. **Reduce indexing concurrency** in reindex-worker:
   ```bash
   # Scale reindex-worker down to 1 replica
   kubectl scale deployment/catalog-reindex-worker --replicas=1 -n ecommerce

   # Reduce batch size in worker (update ConfigMap)
   kubectl set env deployment/catalog-reindex-worker \
     REINDEX_BATCH_SIZE=10 \
     -n ecommerce
   ```

4. **Force Elasticsearch merge** to consolidate segments and reduce future I/O:
   ```bash
   # After reindex completes, manually trigger merge
   curl -X POST http://elasticsearch:9200/products_live/_forcemerge?max_num_segments=1
   # Note: this takes a long time (hours) but reduces long-term I/O
   ```

---

### Failure Mode 4: Search Timeout Under Heavy Indexing Pressure

**Symptoms:**
- Search requests timeout (>30 second wait)
- Elasticsearch query latency p99 > 5 seconds
- ES logs show "GC overhead limit exceeded" or "merging segments"
- User-facing search fails intermittently
- Indexing is active and producing high CPU

**Root cause:**
- Index merge operations triggered by segment count threshold
- Merging is CPU and I/O intensive; pauses other queries
- JVM heap pressure from large merge buffers
- No separate index/search thread pools; merge and query compete for resources

**Diagnosis:**
```bash
# Check Elasticsearch thread pool stats
curl -s http://elasticsearch:9200/_cat/thread_pool?h=host,name,active,queue,rejected

# Check ongoing merge operations
curl -s http://elasticsearch:9200/_segments | jq '.indices.products_live.shards[] | length as $num_shards | "Segments per shard: \($num_shards)"'

# Check JVM heap usage
curl -s http://elasticsearch:9200/_nodes/stats/jvm | jq '.nodes[].jvm.mem | {heap_used_in_bytes,heap_max_in_bytes}'

# Check GC pauses in logs
kubectl logs -n ecommerce sts/elasticsearch | grep -i "gc overhead\|full gc\|pause"
```

**Mitigation steps:**

1. **Lower merge threshold** to trigger merges more frequently (smaller merges, less blocking):
   ```bash
   curl -X PUT http://elasticsearch:9200/products_live/_settings \
     -H "Content-Type: application/json" \
     -d '{
       "settings": {
         "index.merge.policy.segments_per_tier": 10,
         "index.merge.policy.max_merge_at_once": 5
       }
     }'
   ```

2. **Increase JVM heap allocation** (requires pod restart):
   ```bash
   kubectl set env statefulset/elasticsearch \
     -c elasticsearch \
     ES_JAVA_OPTS="-Xms4g -Xmx4g" \
     -n ecommerce
   kubectl rollout restart statefulset/elasticsearch -n ecommerce
   ```

3. **Disable search request throttling** temporarily (allow more concurrent queries):
   ```bash
   # Increase thread pool for search
   curl -X PUT http://elasticsearch:9200/_cluster/settings \
     -H "Content-Type: application/json" \
     -d '{
       "transient": {
         "thread_pool.search.queue_size": 1000,
         "thread_pool.search.size": 32
       }
     }'
   ```

4. **Reduce indexing pressure**:
   ```bash
   # Scale back reindex-worker replicas temporarily
   kubectl scale deployment/catalog-reindex-worker --replicas=1 -n ecommerce

   # Or pause reindex
   redis-cli -h $REDIS_HOST SET reindex:paused true EX 1800
   ```

5. **Monitor query latency recovery**:
   ```bash
   watch -n 5 'curl -s http://elasticsearch:9200/_cat/indices?h=index,search.fetch_time,search.fetch_count | grep products_live'
   ```

---

## Runbook Procedures

### Procedure: Rebuild Search Index From Scratch

**When to use:** After index corruption, complete data loss, or mapping changes that are not backward-compatible.

**Estimated time:** 15–45 minutes (depending on product count: ~24M products takes ~30 min)

**Prerequisites:**
- PostgreSQL is healthy and has full product data
- Elasticsearch cluster is healthy (`_cluster/health` shows "green")
- Confirm backup/export is available if rollback is needed

**Steps:**

1. **Create new index with correct mappings:**
   ```bash
   curl -X PUT "http://elasticsearch:9200/products_new" \
     -H "Content-Type: application/json" \
     -d '{
       "settings": {
         "number_of_shards": 3,
         "number_of_replicas": 1,
         "index.refresh_interval": "30s",
         "analysis": {
           "analyzer": {
             "product_analyzer": {
               "type": "custom",
               "tokenizer": "standard",
               "filter": ["lowercase", "stop"]
             }
           }
         }
       },
       "mappings": {
         "properties": {
           "product_id": {"type": "keyword"},
           "name": {"type": "text", "analyzer": "product_analyzer"},
           "description": {"type": "text", "analyzer": "product_analyzer"},
           "category": {"type": "keyword"},
           "price": {"type": "float"},
           "in_stock": {"type": "boolean"},
           "created_at": {"type": "date"}
         }
       }
     }'
   ```

2. **Verify index creation:**
   ```bash
   curl -s http://elasticsearch:9200/products_new/_settings | jq '.products_new'
   ```

3. **Enqueue full reindex job** (via Celery or direct trigger):
   ```bash
   # Option A: Via reindex-worker API
   curl -X POST http://catalog-api:8000/admin/reindex \
     -H "Content-Type: application/json" \
     -d '{
       "source_index": "products_new",
       "dry_run": false,
       "batch_size": 1000
     }'

   # Option B: Direct Celery trigger
   python -c "
   from backend.app.workers.tasks import full_reindex
   full_reindex.delay(target_index='products_new')
   "
   ```

4. **Monitor reindex progress:**
   ```bash
   # Check doc count growth
   while true; do
     count=$(curl -s http://elasticsearch:9200/products_new/_count | jq .count)
     target=$(psql -h $RDS_ENDPOINT -d ecommerce -t -c "SELECT COUNT(*) FROM products;")
     pct=$((count * 100 / target))
     echo "$(date): $count / $target ($pct%)"
     sleep 10
   done

   # Monitor reindex-worker logs
   kubectl logs -f deployment/catalog-reindex-worker -n ecommerce | grep "processed\|error"
   ```

5. **Once reindex reaches 100%**, validate index health:
   ```bash
   # Check doc count matches source
   curl -s http://elasticsearch:9200/products_new/_count | jq '.count'
   psql -h $RDS_ENDPOINT -d ecommerce -t -c "SELECT COUNT(*) FROM products;"

   # Test sample queries
   curl -s "http://elasticsearch:9200/products_new/_search?q=laptop&size=5" | jq '.hits.total.value'

   # Check cluster health
   curl -s http://elasticsearch:9200/_cluster/health | jq '.status'
   # Should be "green"
   ```

6. **Create alias and swap** (no downtime):
   ```bash
   # Add alias to new index
   curl -X POST http://elasticsearch:9200/_aliases \
     -H "Content-Type: application/json" \
     -d '{
       "actions": [
         {"add": {"index": "products_new", "alias": "products_live"}}
       ]
     }'

   # Remove alias from old index
   curl -X POST http://elasticsearch:9200/_aliases \
     -H "Content-Type: application/json" \
     -d '{
       "actions": [
         {"remove": {"index": "products_v41", "alias": "products_live"}}
       ]
     }'

   # Verify swap
   curl -s http://elasticsearch:9200/_alias/products_live | jq 'keys'
   # Should show ["products_new"]
   ```

7. **Reset catalog-api cache and verify**:
   ```bash
   # Flush search cache
   redis-cli -h $REDIS_HOST --scan --pattern "search:*" | xargs redis-cli DEL

   # Monitor search latency
   kubectl logs -f deployment/catalog-api -n ecommerce | grep "search.*ms"
   # P99 should be <200ms within 1 minute
   ```

8. **Delete old index** (after confirming no issues):
   ```bash
   curl -X DELETE http://elasticsearch:9200/products_v41
   ```

---

### Procedure: Emergency Inventory Lock (Flash Sale Oversell Prevention)

**When to use:** Active overselling detected during flash sale, or as preventive measure during high-traffic promo.

**Estimated time:** 2–5 minutes (instant effect)

**Steps:**

1. **Identify product(s) to lock:**
   ```bash
   # From incident alert or manual discovery
   PRODUCT_IDS="GPU-RTX-4090,PS5-BUNDLE,IPHONE-15-PRO"
   ```

2. **Engage team** (async message to #incidents):
   ```
   :alert: Inventory lock engaged for [$PRODUCT_IDS]. Reason: flash-sale oversell prevention. Locked at 2025-03-08T14:32:00Z.
   ```

3. **Set lock flags in Redis:**
   ```bash
   for pid in $(echo $PRODUCT_IDS | tr ',' '\n'); do
       redis-cli -h $REDIS_HOST \
         SET "inventory:lock:$pid" \
         "{\"reason\":\"flash-sale-oversell\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"locked_by\":\"$ONCALL_USER\"}" \
         EX 86400  # 24 hour expiry
       echo "Locked: $pid"
   done
   ```

4. **Verify locks are set:**
   ```bash
   redis-cli -h $REDIS_HOST MGET inventory:lock:GPU-RTX-4090 inventory:lock:PS5-BUNDLE
   ```

5. **Update API deployment** to check locks:
   ```python
   # In catalog-api/app/services/inventory.py
   def can_decrement_inventory(product_id):
       lock = redis.get(f"inventory:lock:{product_id}")
       if lock:
           return False, "Product is locked for inventory changes"
       return True, "OK"
   ```

6. **Purge related caches** to ensure fresh DB reads:
   ```bash
   for pid in $(echo $PRODUCT_IDS | tr ',' '\n'); do
       redis-cli -h $REDIS_HOST DEL "inventory:$pid" "pricing:$pid" "inventory:cache:$pid"
   done
   ```

7. **Monitor that orders are rejected** (test manually):
   ```bash
   curl -X POST http://catalog-api:8000/checkout \
     -H "Content-Type: application/json" \
     -d '{"items": [{"product_id": "GPU-RTX-4090", "quantity": 1}]}' \
     -v
   # Should return 409 Conflict or 422 Unprocessable Entity
   ```

8. **Unlock after event** (manually or after 24h TTL):
   ```bash
   for pid in $(echo $PRODUCT_IDS | tr ',' '\n'); do
       redis-cli -h $REDIS_HOST DEL "inventory:lock:$pid"
   done
   ```

---

### Procedure: Purge Product Cache (Targeted Invalidation)

**When to use:** Stale product data detected (wrong prices, incorrect descriptions), or after manual data corrections in DB.

**Estimated time:** 1–2 minutes

**Steps:**

1. **Identify affected products** by pattern or ID list:
   ```bash
   # Option A: By product pattern (prefix match)
   PATTERN="GPU-*"

   # Option B: By product IDs (from CSV or alert)
   PRODUCT_IDS=$(cat /tmp/affected_products.csv | head -1000)
   ```

2. **List keys to be deleted** (dry run):
   ```bash
   # For pattern-based deletion
   redis-cli -h $REDIS_HOST --scan --pattern "product:$PATTERN" | head -20
   redis-cli -h $REDIS_HOST --scan --pattern "pricing:$PATTERN" | head -20

   # For ID-based deletion
   for pid in $(echo $PRODUCT_IDS | tr ',' '\n'); do
       redis-cli -h $REDIS_HOST SCAN 0 MATCH "*:$pid"
   done
   ```

3. **Purge cache** (be cautious: do NOT use FLUSHALL):
   ```bash
   # By pattern
   redis-cli -h $REDIS_HOST --scan --pattern "product:GPU-*" | xargs redis-cli DEL
   redis-cli -h $REDIS_HOST --scan --pattern "pricing:GPU-*" | xargs redis-cli DEL

   # By ID list
   for pid in $(echo $PRODUCT_IDS | tr ',' '\n'); do
       redis-cli -h $REDIS_HOST DEL "product:$pid" "pricing:$pid" "product:details:$pid"
   done
   ```

4. **Verify deletion:**
   ```bash
   redis-cli -h $REDIS_HOST --scan --pattern "product:GPU-*" | wc -l
   # Should return 0
   ```

5. **Monitor cache rebuilding** (API requests will trigger fresh DB reads):
   ```bash
   # Watch Redis memory decrease as eviction clears more keys
   watch -n 5 'redis-cli -h $REDIS_HOST INFO memory | grep used_memory_human'

   # Monitor API latency (DB reads will be slower until cache rebuilds)
   kubectl logs -f deployment/catalog-api -n ecommerce | grep "latency"
   # P99 should return to <50ms within 2 minutes
   ```

6. **Cross-check with PostgreSQL** if needed:
   ```bash
   # Verify product prices in DB are correct
   psql -h $RDS_ENDPOINT -d ecommerce -c \
     "SELECT id, name, price FROM products WHERE id IN (SELECT unnest(string_to_array('GPU-RTX-4090,GPU-RTX-4080', ',')) AS id LIMIT 10;"
   ```

---

### Procedure: Pause Reindex Worker (Stop Changelog Processing)

**When to use:** Index health degradation, database load spikes, or emergency maintenance on Elasticsearch.

**Estimated time:** <1 minute (instant)

**Steps:**

1. **Set pause flag in Redis:**
   ```bash
   redis-cli -h $REDIS_HOST \
     SET reindex:paused true \
     EX 3600  # 1 hour auto-expiry
   echo "Reindex paused until $(date -d '+1 hour')"
   ```

2. **Verify pause is active:**
   ```bash
   redis-cli -h $REDIS_HOST GET reindex:paused
   # Output: "true"
   ```

3. **Monitor reindex-worker logs** to confirm it stops processing:
   ```bash
   kubectl logs -f deployment/catalog-reindex-worker -n ecommerce | grep -E "paused|sleeping"
   # Should see: "Reindex is paused; sleeping for 60s"
   ```

4. **Verify changelog queue is accumulating** (not being drained):
   ```bash
   initial_depth=$(redis-cli -h $REDIS_HOST LLEN changelog:queue)
   sleep 30
   after_30s=$(redis-cli -h $REDIS_HOST LLEN changelog:queue)

   if [ $after_30s -gt $initial_depth ]; then
       echo "Queue is accumulating (as expected): $initial_depth → $after_30s"
   else
       echo "WARNING: Queue not growing; worker may not be paused"
   fi
   ```

5. **Scale worker to 0 replicas** (optional, for resource savings):
   ```bash
   kubectl scale deployment/catalog-reindex-worker --replicas=0 -n ecommerce
   ```

6. **Perform maintenance** (e.g., Elasticsearch restart, rebalancing):
   ```bash
   # Example: restart Elasticsearch cluster
   kubectl rollout restart statefulset/elasticsearch -n ecommerce
   kubectl rollout status statefulset/elasticsearch -n ecommerce --timeout=10m
   ```

7. **Resume reindex worker** when ready:
   ```bash
   # Manually remove pause flag
   redis-cli -h $REDIS_HOST DEL reindex:paused

   # Or scale back to normal
   kubectl scale deployment/catalog-reindex-worker --replicas=2 -n ecommerce

   # Verify queue is being drained
   watch -n 5 'redis-cli -h $REDIS_HOST LLEN changelog:queue'
   # Queue depth should decrease over time
   ```

8. **Monitor queue drain** until caught up:
   ```bash
   while true; do
       depth=$(redis-cli -h $REDIS_HOST LLEN changelog:queue)
       echo "$(date): Queue depth = $depth"
       [ $depth -eq 0 ] && echo "Queue fully drained!" && break
       sleep 30
   done
   ```

---

## Monitoring & Alerts

### Key Metrics & Thresholds

| Metric | Query / Source | Alert Threshold | Severity |
|--------|---|---|---|
| **Search Latency P99** | `histogram_quantile(0.99, catalog_search_duration_seconds)` | >250ms for 5 min | P2 |
| **Search Zero-Result Rate** | `rate(search_zero_results_total[5m]) / rate(search_total[5m])` | >5% for 5 min | P2 |
| **Inventory Read P99** | `histogram_quantile(0.99, catalog_inventory_read_duration_seconds)` | >100ms for 5 min | P2 |
| **Elasticsearch Cluster Health** | `curl http://elasticsearch:9200/_cluster/health` | Status != "green" for 2 min | P1 |
| **Index Doc Count Drift** | `ABS(ES_doc_count - DB_product_count) / DB_product_count` | >5% for 10 min | P2 |
| **Changelog Queue Depth** | `redis-cli LLEN changelog:queue` | >50k items for 5 min | P2 |
| **Reindex Lag (minutes)** | `(NOW() - max(changelog_timestamp)) / 60` | >30 min for 15 min | P3 |
| **Redis Cache Hit Rate** | `keyspace_hits / (keyspace_hits + keyspace_misses)` | <75% for 10 min | P3 |
| **Inventory Variance** | `ABS(DB_count - Orders_count)` | >10 units for single product | P1 |
| **Elasticsearch Disk Usage** | `curl http://elasticsearch:9200/_cat/allocation` | >85% for 5 min | P2 |
| **PostgreSQL Replication Lag** | `SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))` | >30s for 5 min | P2 |

### Alert Routing & Automation

**PagerDuty Integration:**
- P1 alerts: Immediately page on-call (SMS + call)
- P2 alerts: Page after 5 min, escalate to Search Infra after 15 min
- P3 alerts: Slack notification only, no page

**Prometheus Rules Examples:**

```yaml
groups:
  - name: catalog.rules
    interval: 30s
    rules:
      - alert: CatalogSearchLatencyHigh
        expr: histogram_quantile(0.99, catalog_search_duration_seconds) > 0.25
        for: 5m
        labels:
          severity: P2
          service: catalog
        annotations:
          summary: "Search P99 latency > 250ms ({{ $value | humanizeDuration }})"
          runbook: "https://docs.company.com/runbooks/catalog#search-timeout"

      - alert: ElasticsearchClusterRed
        expr: elasticsearch_cluster_health_status{color="red"} > 0
        for: 2m
        labels:
          severity: P1
          service: catalog
        annotations:
          summary: "Elasticsearch cluster is RED"
          runbook: "https://docs.company.com/runbooks/catalog#es-split-brain"

      - alert: ChangelogQueueBackup
        expr: redis_changelog_queue_length > 50000
        for: 5m
        labels:
          severity: P2
          service: catalog
        annotations:
          summary: "Changelog queue backup: {{ $value }} items pending"
          runbook: "https://docs.company.com/runbooks/catalog#reindex-lag"

      - alert: InventoryVariance
        expr: abs(postgres_inventory_count - orders_sum_quantity) > 10
        for: 5m
        labels:
          severity: P1
          service: catalog
        annotations:
          summary: "Inventory variance detected: {{ $value }} units"
          runbook: "https://docs.company.com/runbooks/catalog#oversell"
```

### Dashboard Panels

Create a Grafana dashboard titled "Product Catalog Health" with:
1. **Search Performance** (timeseries): P50, P99 latency, zero-result %, query throughput
2. **Elasticsearch** (status cards): Cluster health, shard allocation, index size, disk usage
3. **Reindex Progress** (gauge): Queue depth, lag in minutes, throughput (docs/sec)
4. **Inventory Health** (number): Variance, cache hit rate, DB connection count
5. **Redis** (heatmap): Key eviction rate, memory usage, commands/sec

---

## Escalation Policy

### Definition & Severity Levels

| Severity | Response SLA | Escalation Path | Example |
|----------|---|---|---|
| **P0** | Immediate (5 min) | Catalog Platform on-call → Eng Manager (if not resolved in 5 min) | Complete service outage (0% availability) |
| **P1** | 15 minutes | Catalog Platform on-call → Search Infra on-call (if not resolved in 15 min) | Elasticsearch cluster red, overselling, data loss |
| **P2** | 30 minutes | Catalog Platform on-call → Slack #incidents (if not resolved in 30 min) | High latency (>1s), significant feature degradation |
| **P3** | 2 hours | Create ticket, assign to backlog | Minor latency increase, non-critical monitoring gap |

### Escalation Tiers

**Tier 1: Catalog Platform On-Call (First responder)**
- Handles initial triage and mitigation
- Executes runbook procedures (cache purge, inventory lock, reindex pause)
- Can modify feature flags and environment variables (via kubectl/redis-cli)
- Escalates to Tier 2 if issue is unresolved after 15 min (P1) or 30 min (P2)

**Tier 2: Search Infrastructure Team (Elasticsearch/performance specialists)**
- Engaged for cluster-level issues (split-brain, rebalancing, performance tuning)
- Can restart Elasticsearch, adjust JVM settings, modify index settings
- Requires access to k8s cluster admin (AWS IAM role `search-infra-admin`)
- Escalates to Tier 3 if root cause not identified in 30 min

**Tier 3: Database Team (PostgreSQL/replication)**
- Engaged for database performance, replication lag, or connection pool exhaustion
- Can restart RDS instance, modify parameters, promote replica
- Escalates to AWS support for infrastructure issues
- Post-incident: RCA meeting within 4 hours

### Escalation Decision Tree

```
Issue detected (alert fired)
  ↓
Tier 1 on-call notified (SMS/Slack)
  ↓
  ├─ P0 (total outage): Call escalation immediately
  │   ├─ Execute emergency procedures (see Procedures section)
  │   └─ Page Eng Manager + Search Infra on-call
  │
  ├─ P1 (service degradation):
  │   ├─ Acknowledge alert in PagerDuty (<2 min)
  │   ├─ Execute triage (check metrics, logs, redis-cli)
  │   ├─ If root cause identified → execute runbook procedure
  │   └─ If unresolved after 15 min → Page Search Infra on-call (async)
  │
  └─ P2 (performance/availability risk):
      ├─ Acknowledge alert (<5 min)
      ├─ Create incident ticket in Jira
      ├─ Assess impact (user-facing? data corruption? revenue impact?)
      └─ If unresolved after 30 min → Slack #incidents + escalate
```

### Communication Template

**For Slack #incidents (P1/P0):**

```
:red_alert: P1 Incident: [SERVICE] [BRIEF TITLE]
• Status: INVESTIGATING / MITIGATING / RESOLVED
• Impact: [X] customers affected, [Y] transactions failed, [Z] revenue impact
• Root cause: [Description or TBD]
• Tier 1 on-call: @username (ETA to update: 15 min)
• Runbook: [Link to relevant section]
• Last update: [timestamp UTC]
```

**For stakeholders (post-incident):**

```
Product Catalog Incident Summary (INC-2025-XXXX)
• Timeline: 2025-03-08 14:32 – 14:46 UTC (14 minutes)
• Severity: P1
• User impact: 4,500 failed searches (0.8% of 10-min traffic)
• Root cause: [XXX]
• Resolution: [YYY]
• Prevention: [ZZZ]
• Follow-ups: [1, 2, 3] (tracked in Jira)
• RCA meeting: [Date/time]
```

### On-Call Handoff

**At shift change** (every Monday 9am):
1. Outgoing on-call reviews escalation contacts and recent incidents
2. Verifies all alerts are properly routed (PagerDuty → Slack → Escalation)
3. Briefs incoming on-call on:
   - Any active incidents or watchlist items
   - Recent changes to runbook or procedures
   - Known flaky alerts or false positives
   - Scheduled maintenance windows (reindex, backups, etc.)

**Escalation Contact Sheet:**
- **Catalog Platform on-call:** PagerDuty rotation `catalog-platform-oncall`
- **Search Infra on-call:** PagerDuty rotation `search-infra-oncall`
- **Engineering Manager (Paul):** paul@company.com, Slack @paul-eng
- **AWS Support case escalation:** Support plan Enterprise, case prefix ECOM-

---

## Appendix: Quick Reference Commands

### System Status Check (1-minute audit)

```bash
#!/bin/bash
echo "=== CATALOG SYSTEM HEALTH CHECK ==="

# Elasticsearch
echo "\n1. Elasticsearch:"
curl -s http://elasticsearch:9200/_cluster/health | jq '{status,active_shards,relocating_shards}'

# PostgreSQL
echo "\n2. PostgreSQL:"
psql -h $RDS_ENDPOINT -d ecommerce -t -c "SELECT 'DB OK: ' || count(*) || ' products' FROM products;" || echo "DB ERROR"

# Redis
echo "\n3. Redis:"
redis-cli -h $REDIS_HOST PING && redis-cli -h $REDIS_HOST INFO stats | grep -E "keyspace_hits|keyspace_misses"

# Reindex queue
echo "\n4. Reindex Queue:"
redis-cli -h $REDIS_HOST LLEN changelog:queue

# API health
echo "\n5. Catalog API:"
curl -s http://catalog-api:8000/health | jq '.status'
```

### Emergency Procedures Summary

| Issue | Command |
|-------|---------|
| **Swap alias back** | `curl -X POST http://elasticsearch:9200/_aliases -d '{"actions":[{"remove":{"index":"products_v42","alias":"products_live"}},{"add":{"index":"products_v41","alias":"products_live"}}]}'` |
| **Lock inventory** | `redis-cli SET inventory:lock:PRODUCT_ID true EX 86400` |
| **Flush cache** | `redis-cli --scan --pattern "product:*" \| xargs redis-cli DEL` |
| **Pause reindex** | `redis-cli SET reindex:paused true EX 3600` |
| **Scale workers** | `kubectl scale deployment/catalog-reindex-worker --replicas=8 -n ecommerce` |
| **Check queue depth** | `redis-cli LLEN changelog:queue` |

---

**Last Updated:** 2025-03-21
**Document Owner:** Catalog Platform Team
**Review Frequency:** Quarterly (next review: 2025-06-21)
