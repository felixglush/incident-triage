# Checkout & Payments Runbook

## Service Overview

**Service Name:** Checkout & Payments Platform
**Owner:** Payments Platform Team
**PagerDuty Escalation:** `payments-platform-oncall`
**Slack Channel:** `#payments-incidents`

### Architecture

The Checkout & Payments system is a multi-tier payment processing pipeline:

```
User → checkout-service (Go, gRPC)
  ↓
payment-processor abstraction (Router)
  ├→ Stripe API client (primary provider)
  └→ Adyen API client (fallback provider)
  ↓
fraud-service (Python FastAPI, ML-based scoring)
  ↓
order-service (Node.js gRPC)
  ↓
PostgreSQL (orders, payment_events tables)

Supporting:
- Redis (cart sessions, TTL 2h; idempotency keys, TTL 24h)
- payment-events DLQ (failed webhook processing, RabbitMQ)
```

### Service Tier & SLOs

| Metric | Target | P99 Latency | Alerting Threshold |
|--------|--------|------------|-------------------|
| Checkout availability | 99.95% | <3s | <99.85% over 5 min |
| Payment error rate | <0.1% | — | >0.15% over 2 min |
| Cart session eviction | 0% | — | >5% Redis maxmemory reached |
| Fraud service response | <500ms | — | p99 >2000ms |
| Idempotency dedup latency | <10ms | — | p99 >50ms |

### Dependencies & Critical Paths

- **Stripe API:** Payment capture, refunds, webhooks (incident escalation: Stripe status page)
- **Fraud-service ML model:** Cold starts ≤30s post-deploy (monitor via `fraud_service_startup_duration_ms`)
- **PostgreSQL:** order creation RPS target 2000; deadlock monitor via `pg_stat_activity`
- **Redis:** Cart session peak 1M keys; idempotency keys 500k keys; total memory ceiling 8GB

---

## Recorded Incidents

### INC-2024-0112 — Black Friday Checkout Latency Spike

**Severity:** P0
**Date:** 2024-11-29
**Duration:** 23 minutes (14:17 UTC – 14:40 UTC)
**On-Call:** Jamie Chen, Payments Platform

#### Description

During Black Friday peak traffic (11:17 UTC), checkout success rate dropped to 38% and P99 latency spiked from 1.2s to 47s. User reports of cart session loss mid-checkout flooded Slack. Datadog alerts triggered:
- `redis.memory.used_percent > 98%` (checkout-redis instance)
- `checkout_service.p99_latency_ms > 20000` (10 min rolling)

#### Impact

- **Checkout conversion:** 1,847 abandoned checkouts over 23 min
- **GMV lost:** ~$340,000 (based on Black Friday ARPU $184)
- **Customers affected:** 12,300+
- **Recovery:** Manual retry campaign, ~67% recovery rate

#### Root Cause

Redis cart session store (`checkout-redis`) had `maxmemory=4GB` configured since July. Peak Black Friday traffic (3.2M concurrent sessions) consumed 6.1GB of memory. Eviction policy `allkeys-lru` dropped active cart sessions randomly. Checkout-service queries resulted in cache misses, which fell back to session reconstruction from database—creating thundering herd on PostgreSQL session table, saturating connection pool.

Timeline:
- **14:10 UTC:** Redis memory reaches 96%
- **14:13 UTC:** Eviction kicks in at 98%; P99 latency rises to 8s
- **14:15 UTC:** Session reconstruction fallback cascades; PostgreSQL CPU 89%
- **14:17 UTC:** PagerDuty P0 alert fires; on-call joins war room
- **14:25 UTC:** Root cause identified (memory exhaustion)
- **14:27 UTC:** Emergency remediation begins
- **14:40 UTC:** Service stabilized; P99 latency returns to 1.4s

#### Resolution Steps

**Step 1: Immediate memory expansion**
```bash
redis-cli -h checkout-redis.ecommerce CONFIG SET maxmemory 8gb
redis-cli -h checkout-redis.ecommerce CONFIG SET maxmemory-policy allkeys-lru
redis-cli -h checkout-redis.ecommerce CONFIG REWRITE
```
Verified:
```bash
redis-cli -h checkout-redis.ecommerce INFO memory | grep maxmemory
# maxmemory:8589934592
# maxmemory_human:8.00G
# used_memory_percent:62.3%
```

**Step 2: Scale checkout-service replicas (horizontal load distribution)**
```bash
kubectl scale deployment/checkout-service --replicas=12 -n ecommerce
# deployment.apps/checkout-service scaled
# 12 replicas confirmed at 14:35 UTC
```

**Step 3: Drain and re-balance cart sessions**
Manual trigger of cache-warming job:
```bash
kubectl exec -it job/checkout-cache-warmup-$(date +%s) -n ecommerce -- \
  python scripts/replay_active_sessions.py \
  --source=postgresql \
  --destination=redis \
  --batch-size=5000
# Loaded 2,847,291 active sessions in 8 minutes
```

**Step 4: Monitor recovery**
```bash
# Watch P99 latency return to baseline
watch -n 5 'redis-cli -h checkout-redis.ecommerce INFO stats | grep -E "instantaneous_ops_per_sec|used_memory_human"'
# P99 returned to 1.4s at 14:40 UTC
```

#### Follow-Up Actions

1. **Alert threshold lowered:** Memory alert moved from 85% → 70% threshold
2. **Pre-event scaling runbook created:** Auto-scale checkout-service to 8 replicas and pre-allocate 6GB Redis memory 2 hours before sale events (Black Friday, Cyber Monday, Prime Day)
3. **Cache eviction monitoring added:** New Datadog dashboard tracking Redis eviction rate (target: <0.5% keys/min)
4. **Incident postmortem:** Scheduled 2024-12-04, action items assigned to platform engineers

---

### INC-2024-0287 — Payment Webhook Storm

**Severity:** P1
**Date:** 2024-08-14
**Duration:** 18 minutes (09:42 UTC – 10:00 UTC)
**On-Call:** Marcus Wong, Payments Platform

#### Description

Stripe payment webhook processing experienced a retry storm. Between 09:42 and 09:50 UTC, the `POST /webhooks/stripe/events` endpoint received 45,287 duplicate `payment.succeeded` webhook events. While the service's idempotency key deduplication logic caught ~99.3% of duplicates, 312 orders were inadvertently created twice with identical user and cart data.

Alerts triggered:
- `stripe_webhook_events_per_minute > 15000` (normal: 2,500)
- `checkout_service.external_api_latency[stripe_webhook] p99 > 5000ms`
- `orders_table.create_rate_anomaly` (internal rate 6,240 orders/min vs. baseline 1,200)

#### Impact

- **Duplicate orders created:** 312 (later voided)
- **Payment capture attempts:** 312 additional Stripe API calls (benign, idempotent)
- **Customer support tickets:** 47 reports of "two orders in my account"
- **Manual remediation time:** 4 hours (finding, voiding, and refunding duplicate orders)
- **Stripe support escalation:** Yes (investigation into webhook retry behavior)

#### Root Cause

Stripe experienced upstream infrastructure issues (internal queue lag, not disclosed in real-time status page). Their webhook delivery system entered retry mode, exponentially re-sending recent successful webhooks. Checkout-service's idempotency key logic was based on Stripe's `event.id` field (unique per event) and stored in Redis with TTL 1 hour. However, Stripe re-sent the same `event.id` with fresh timestamps; the dedup cache was hit, but rate-limiting on the webhook endpoint was not in place. A single downstream service outage (order-service briefly hung for 6 seconds) caused idempotency requests to back up, and by the time they cleared, 312 orders had already been created in the race condition window.

#### Resolution Steps

**Step 1: Enable circuit breaker on webhook endpoint (feature flag)**
```bash
# Activate circuit breaker to prevent further duplicate ingestion
curl -X POST http://checkout-service.ecommerce:8000/admin/feature-flags \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -d '{
    "flag": "payments.webhook_circuit_breaker",
    "enabled": true,
    "threshold": 10000,
    "window_seconds": 60,
    "action": "reject"
  }' \
  -H "Content-Type: application/json"
# Circuit breaker enabled; subsequent webhook POST requests returning 429 Too Many Requests
```

**Step 2: Identify and void duplicate orders**
```bash
# Query for duplicate orders (same external_payment_id, created within 10 seconds)
psql $DATABASE_URL -c "
  SELECT external_payment_id, COUNT(*) as count, array_agg(id) as order_ids
  FROM orders
  WHERE created_at > NOW() - INTERVAL '30 minutes'
  GROUP BY external_payment_id
  HAVING COUNT(*) > 1
  ORDER BY count DESC
;" | tee duplicate_orders_$(date +%s).txt

# Output: 312 duplicate order groups identified
```

**Step 3: Void duplicate orders (keep earliest, void rest)**
```bash
# Carefully void all but the first order in each group
psql $DATABASE_URL << 'SQL'
WITH duplicates AS (
  SELECT
    external_payment_id,
    id,
    ROW_NUMBER() OVER (PARTITION BY external_payment_id ORDER BY id ASC) as rn
  FROM orders
  WHERE created_at > NOW() - INTERVAL '30 minutes'
    AND external_payment_id IN (
      SELECT external_payment_id FROM orders
      WHERE created_at > NOW() - INTERVAL '30 minutes'
      GROUP BY external_payment_id HAVING COUNT(*) > 1
    )
)
UPDATE orders
SET
  status = 'voided',
  void_reason = 'INC-2024-0287 duplicate order from webhook storm',
  updated_at = NOW()
WHERE id IN (SELECT id FROM duplicates WHERE rn > 1)
RETURNING external_payment_id, id, status;
SQL
# 312 orders marked as voided
```

**Step 4: Process refunds for voided orders**
```bash
# Trigger async refund job for voided orders
curl -X POST http://order-service.ecommerce:50051/admin/batch-refund \
  -H "Authorization: Bearer ${SERVICE_TOKEN}" \
  -d '{
    "reason": "INC-2024-0287 duplicate order",
    "order_ids_from_query": "SELECT id FROM orders WHERE void_reason = \u0027INC-2024-0287 duplicate order from webhook storm\u0027"
  }' \
  -H "Content-Type: application/json"
# Refund job queued; processing 312 refunds asynchronously
```

**Step 5: Disable circuit breaker (restore normal operation)**
Wait 30 minutes, then re-enable webhook processing after validation:
```bash
curl -X POST http://checkout-service.ecommerce:8000/admin/feature-flags \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -d '{
    "flag": "payments.webhook_circuit_breaker",
    "enabled": false
  }' \
  -H "Content-Type: application/json"
# Circuit breaker disabled; webhook processing resumed at 10:00 UTC
```

#### Follow-Up Actions

1. **Idempotency key TTL extension:** Increased from 1 hour → 48 hours (prevents replication of same webhook if delayed)
2. **Duplicate order detection job:** New scheduled job (`checkout_duplicate_detection_job`) runs every 5 minutes, queries for orders with identical `(user_id, cart_total, created_at within 10s)`, alerts on-call if count > 5
3. **Webhook endpoint timeout hardening:** Added `order_service.timeout_ms = 5000` to prevent long-tail latency hangs
4. **Stripe API health monitoring:** Integrated Stripe status feed into PagerDuty incident management; auto-acknowledge webhook spike alerts if Stripe is under incident
5. **Postmortem:** 2024-08-18, investigation into race condition window and potential distributed lock improvements

---

### INC-2025-0044 — Fraud Service Timeout Cascade

**Severity:** P1
**Date:** 2025-02-03
**Duration:** 11 minutes (16:24 UTC – 16:35 UTC)
**On-Call:** Aisha Patel, Payments Platform

#### Description

At 16:24 UTC, the fraud-service deployment was rolled out with an updated ML model. The new pod cold start caused a 30-second initialization hang before the service became ready. During this window, checkout-service had no timeout configured on its RPC call to fraud-service for ML risk scoring. Goroutines accumulated in the checkout-service connection pool, exhausting available database connections to order-service. Checkout error rate climbed to 94%, and P99 latency reached 47 seconds.

Alerts triggered:
- `checkout_service.grpc_connection_pool_exhausted` (pool at 512/512 connections)
- `checkout_service.p99_latency_ms > 45000` (baseline 1.2s)
- `checkout_service.http_5xx_rate > 50%` (baseline 0.1%)
- `fraud_service.pod_startup_duration_ms = 30000` (baseline 2s)

#### Impact

- **Checkout success rate:** 6% (down from 99.2%)
- **Transactions affected:** 8,900 failed checkout attempts over 11 min
- **GMV lost:** ~$1.6M (assuming ARPU $180)
- **Customer experience:** Timeouts, "please try again" errors, cart abandonment
- **On-call effort:** War room coordination, multiple rollback attempts, ~2 hours post-incident cleanup

#### Root Cause

The fraud-service ML model update introduced a cold-start warm-up phase. The Python FastAPI service used to load the transformer model (DistilBERT-based risk classifier) during `__init__`, which now took 30 seconds instead of 2 seconds. Kubernetes readiness probes did not detect this (probes succeeded immediately after port binding). Checkout-service had no timeout on the fraud-service RPC call (`fraud_service.risk_score()`) and no circuit breaker. When the pods restarted, the first 30 seconds of requests hung indefinitely. Checkout-service goroutines piled up waiting for the RPC response, eventually exhausting the connection pool. The order-service connection pool then ran out of available slots, causing all order creation calls to fail.

#### Resolution Steps

**Step 1: Immediate rollback of fraud-service (fastest recovery)**
```bash
kubectl rollout undo deployment/fraud-service -n ecommerce
# deployment.apps/fraud-service rolled back
# 4 pods restarted; cold start ~2s each
```

Verify pods are healthy:
```bash
kubectl rollout status deployment/fraud-service -n ecommerce --timeout=120s
# rollout status: "successfully rolled out"
# All replicas ready at 16:26 UTC
```

**Step 2: Monitor checkout-service recovery**
```bash
# Watch connection pool drain
watch -n 2 'kubectl logs deployment/checkout-service -n ecommerce --tail=5 | grep -i "pool\|latency"'

# Check metrics for latency normalization
curl -s http://prometheus.ecommerce:9090/api/v1/query \
  --data-urlencode 'query=histogram_quantile(0.99, checkout_service_latency_ms)' | jq '.data.result'
# P99 latency: 47s → 12s → 3.2s → 1.4s (stabilized by 16:29 UTC)
```

**Step 3: Add timeout to fraud-service RPC calls**
While fraud-service is running stable, permanently fix checkout-service to prevent cascades:
```bash
kubectl set env deployment/checkout-service \
  -n ecommerce \
  FRAUD_SERVICE_TIMEOUT_MS=2000 \
  FRAUD_SERVICE_CIRCUIT_BREAKER_THRESHOLD=10 \
  FRAUD_SERVICE_CIRCUIT_BREAKER_TIMEOUT_S=30
# Deployment updated; 8 pods rolling
```

Verify environment variable is set:
```bash
kubectl exec -it deployment/checkout-service -n ecommerce -- \
  env | grep FRAUD_SERVICE_TIMEOUT
# FRAUD_SERVICE_TIMEOUT_MS=2000
```

**Step 4: Redeploy fraud-service with improved startup diagnostics**
Create a patch to improve cold-start time and add startup probes:
```bash
kubectl patch deployment fraud-service -n ecommerce --type='json' -p='[
  {
    "op": "replace",
    "path": "/spec/template/spec/containers/0/startupProbe",
    "value": {
      "httpGet": {"path": "/health/startup", "port": 8000},
      "failureThreshold": 30,
      "periodSeconds": 2
    }
  },
  {
    "op": "replace",
    "path": "/spec/template/spec/containers/0/readinessProbe",
    "value": {
      "httpGet": {"path": "/health/ready", "port": 8000},
      "periodSeconds": 2,
      "timeoutSeconds": 1
    }
  }
]'
# Deployment patched; rolling update initiated
```

Trigger new deployment:
```bash
kubectl rollout restart deployment/fraud-service -n ecommerce
# Restarting with startup probe; pods will not mark Ready until /health/startup succeeds
```

Monitor startup:
```bash
kubectl get events -n ecommerce --sort-by='.lastTimestamp' | grep fraud-service
# Confirm pods reach Ready state in ~35s (with startup probe overhead)
```

#### Follow-Up Actions

1. **Fraud-service cold-start optimization:** Profile and reduce ML model initialization time to <2s (parallel loading, pre-cached embeddings)
2. **Fallback scoring strategy:** Implement allow-on-timeout fallback for orders <$500 (low-risk tier) so checkout doesn't fail during fraud-service outages
   ```yaml
   # Feature flag
   fraud_service_timeout_fallback:
     enabled: true
     order_amount_threshold_cents: 50000
     fallback_action: "allow"
   ```
3. **Startup probes added to all critical services:** fraud-service, order-service, checkout-service (prevents similar cascades)
4. **Deployment validation test:** Require checkout success rate >99% for 2 minutes before marking fraud-service deployment as complete
5. **Postmortem:** 2025-02-05, review model deployment strategy and circuit breaker coverage

---

### INC-2024-0201 — Partial Checkout Failures from Payment Gateway Rate Limiting

**Severity:** P1
**Date:** 2024-07-20
**Duration:** 18 minutes (14:32 UTC – 14:50 UTC)
**On-Call:** Chen Wei, Payments Platform

#### Description

At 14:32 UTC, the payment processor (Stripe) encountered rate limits during a legitimately high-traffic day (peak load 8,500 requests/minute, normal baseline 3,200). Stripe's API began returning `429 Too Many Requests` responses. Checkout-service's retry logic was configured to retry aggressively without backoff, causing exponential request amplification. Checkout error rate climbed to 8%, and customers received "payment processing unavailable" errors.

Alerts triggered:
- `payment_gateway_5xx_rate > 5%` (actually 429 rate-limiting, not 5xx)
- `checkout_service.payment_provider_error_rate > 5%`
- `checkout_service.retry_loop_depth > 3` (aggressive retry amplification)

#### Impact

- **Checkout failure rate:** 8% for 18 minutes
- **Failed checkout attempts:** ~3,400 transactions
- **GMV lost:** ~$67,000 (based on ARPU $197)
- **Customers affected:** 2,100+
- **Payment provider escalation:** No; legitimate rate limiting

#### Root Cause

Payment processor applied standard rate-limiting during peak traffic. Checkout-service had retry policy configured with `max_retries=10`, `initial_backoff_ms=100`, and exponential backoff factor of `1.5x` (no jitter). This caused the retry storm to compound, sending 15-20x amplified load back to the payment processor. When legitimate traffic spike combined with retry traffic, checkout-service became a dos vector against the payment gateway.

#### Resolution Steps

**Step 1: Reduce checkout-service retry aggressiveness (feature flag)**
```bash
curl -X POST http://checkout-service.ecommerce:8000/admin/feature-flags \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -d '{
    "flag": "payment_processor.retry_policy",
    "max_retries": 3,
    "initial_backoff_ms": 500,
    "max_backoff_ms": 5000,
    "backoff_factor": 2.0,
    "jitter_enabled": true
  }' \
  -H "Content-Type: application/json"
# Retry policy updated; checkout-service now uses 3 retries with exponential backoff + jitter
```

**Step 2: Monitor checkout error recovery**
```bash
watch -n 5 'curl -s http://prometheus.ecommerce:9090/api/v1/query --data-urlencode "query=rate(checkout_service_errors_total[1m])" | jq ".data.result[0].value[1]"'
# Error rate should drop from 8% to <0.5% within 2 minutes
```

**Step 3: Scale checkout-service to distribute load**
```bash
kubectl scale deployment/checkout-service --replicas=14 -n ecommerce
# 14 replicas now; reduces per-instance request rate to payment processor
```

**Step 4: Implement circuit breaker for payment processor (permanent fix)**
While system recovers, permanently add circuit breaker:
```bash
kubectl set env deployment/checkout-service \
  -n ecommerce \
  PAYMENT_PROCESSOR_CIRCUIT_BREAKER_THRESHOLD=50 \
  PAYMENT_PROCESSOR_CIRCUIT_BREAKER_TIMEOUT_S=60
# Deployment updated; circuit breaker now trips after 50 consecutive failures
```

#### Follow-Up Actions

1. **Retry policy hardened:** Max retries reduced from 10 → 3, backoff jitter added to prevent thundering herd
2. **Payment processor circuit breaker:** Implemented to reject new payment attempts if 10+ consecutive failures occur
3. **Rate-limit aware monitoring:** Added alert `payment_gateway_429_rate > 100/min` to detect early
4. **Load test pre-event planning:** Coordinate with Stripe on expected peak load before major sales events
5. **Postmortem:** 2024-07-24, review retry strategy and payment processor communication

---

### INC-2024-0456 — Fraud Service Configuration Typo Blocking Legitimate Orders

**Severity:** P2
**Date:** 2024-10-12
**Duration:** 23 minutes (11:15 UTC – 11:38 UTC)
**On-Call:** Marcus Wong, Payments Platform

#### Description

A configuration deployment changed the fraud risk scoring threshold for order blocking from `0.85` (block high-risk orders >85% risk) to `0.085` (block >8.5% risk). This single-digit typo meant virtually all orders were flagged as fraudulent and blocked at checkout. Customers received "order blocked for fraud review" messages. Approximately 400 customers complained via support within 10 minutes. The incident was detected via support ticket spike, not automated alerts.

Impact was silent to monitoring (no error rate spike; orders were blocked gracefully, not errored).

#### Impact

- **Checkout block rate:** 97% of orders flagged and blocked
- **Failed checkouts:** ~400 customers over 23 minutes
- **GMV blocked:** ~$85,000 (estimated from typical order patterns)
- **Support tickets:** 47 complaints received
- **Detection method:** Manual (no automated threshold alert)
- **Time to identify cause:** 12 minutes (manual investigation of config history)

#### Root Cause

Configuration file `backend/config/fraud_rules.yml` was updated via automated deployment. A typo in the YAML config set:
```yaml
fraud_scoring:
  block_threshold: 0.085  # WRONG: intended 0.85, extra zero added
```

The fraud-service loaded this config at startup and applied it to all order scoring. Legitimate orders with fraud scores 0.15–0.80 were now blocked. The config change was not caught during code review (human readable as "8.5%" risk threshold, which sounds plausible to a human).

#### Resolution Steps

**Step 1: Identify the problematic config**
```bash
git log --oneline backend/config/fraud_rules.yml | head -5
# Commit: a7f3e2c Update fraud thresholds for Q4 campaign
git diff a7f3e2c~1 a7f3e2c backend/config/fraud_rules.yml
# Shows: block_threshold: 0.85 → 0.085 (typo detected)
```

**Step 2: Immediate rollback of config**
```bash
git checkout HEAD~1 -- backend/config/fraud_rules.yml
git commit -m "rollback: fraud config typo (INC-2024-0456)"
git push origin main
# Config file reverted to 0.85 threshold
```

**Step 3: Redeploy fraud-service with corrected config**
```bash
kubectl rollout restart deployment/fraud-service -n ecommerce
# 4 pods restarting; config reload ETA 30 seconds
```

**Step 4: Monitor fraud block rate recovery**
```bash
watch -n 5 'psql $DATABASE_URL -c "SELECT DATE_TRUNC(\u0027minute\u0027, created_at) as minute, COUNT(*) as blocked_count FROM orders WHERE fraud_check_blocked = true AND created_at > NOW() - INTERVAL \u00271 hour\u0027 GROUP BY DATE_TRUNC(\u0027minute\u0027, created_at) ORDER BY minute DESC LIMIT 10;"'
# Block rate should drop from 97% to <2% baseline within 1 minute
```

**Step 5: Unbind fraudulently blocked orders (allow customer checkout retry)**
```bash
psql $DATABASE_URL << 'SQL'
UPDATE orders
SET fraud_check_blocked = false, fraud_block_reason = 'Configuration error (INC-2024-0456); order re-enabled'
WHERE fraud_check_blocked = true
  AND created_at > NOW() - INTERVAL '30 minutes'
  AND fraud_score < 0.9;  -- Only unblock plausible orders
RETURNING id, user_id, fraud_score;
SQL
# ~385 orders unblocked
```

**Step 6: Send customer outreach (CS team)**
```
Email template to blocked customers:
"We've fixed a configuration issue that temporarily prevented your order. Your cart is ready to checkout again. Use code SORRY10 for 10% off to apologize for the inconvenience."
```

#### Follow-Up Actions

1. **Config validation test:** Add pre-commit hook to validate fraud threshold is between 0.5 and 0.99 (catch typos)
2. **Code review checklist:** Highlight numerical thresholds in config diffs (human review should catch 8.5% label)
3. **Fraud block rate monitoring:** Add dashboard tracking `orders_blocked_by_fraud_percent` to detect sudden spikes
4. **Postmortem:** 2024-10-14, implement preventive validation for numerical configs

---

### INC-2025-0118 — Stripe API OAuth Token Expiry During Auto-Renew

**Severity:** P1
**Date:** 2025-01-22
**Duration:** 31 minutes (09:14 UTC – 09:45 UTC)
**On-Call:** Aisha Patel, Payments Platform

#### Description

Checkout-service maintains a long-lived OAuth token for Stripe API access. Token expiry is set to 12 hours. At 09:14 UTC, the token expired. Checkout-service detected expiry and attempted to call the token renewal endpoint. However, the renewal endpoint was temporarily unreachable due to a DNS TTL cache miss (internal DNS SRV record had 300-second TTL; the DNS resolver cached the old record pointing to a decommissioned server). All Stripe API calls failed immediately with `"invalid_token"` errors. Checkout success rate dropped to 0% for 19 minutes until DNS TTL expired and the resolver re-queried.

Alerts triggered:
- `checkout_service.stripe_api_auth_failure_rate > 90%`
- `checkout_service.p99_latency_ms > 5000` (timeouts on token renewal endpoint)

#### Impact

- **Checkout success rate:** 0% for 19 minutes (complete outage during token renewal window)
- **Failed checkouts:** ~4,200 transactions
- **GMV lost:** ~$823,000 (assuming ARPU $196)
- **Customers affected:** 2,100+
- **Incident duration:** 31 minutes total; 19 minutes with zero success

#### Root Cause

Checkout-service token renewal logic did not gracefully handle network failures:
1. Token expired at 09:14 UTC
2. Attempted renewal via `POST /stripe/oauth/token` endpoint
3. DNS resolver returned stale cached record (300s TTL)
4. Renewal request timed out (TCP timeout 30s)
5. Checkout-service did not implement retry-with-backoff or fallback mechanism
6. Every checkout request attempted token renewal, then failed when renewal hung
7. At 09:44 UTC, DNS TTL expired; resolver re-queried and received correct record
8. Subsequent renewals succeeded; checkout recovered

#### Resolution Steps

**Step 1: Force immediate token renewal (bypass cached DNS)**
```bash
# Manually request token renewal using alternative DNS resolver (e.g., 8.8.8.8)
curl -X POST https://oauth.stripe.com/oauth/token \
  --resolve oauth.stripe.com:443:52.89.123.45 \  # Use hardcoded IP instead of DNS
  -d "client_id=${STRIPE_CLIENT_ID}" \
  -d "client_secret=${STRIPE_CLIENT_SECRET}" \
  -d "grant_type=client_credentials" | jq '.access_token'
# Response: "sk_live_51234567890..." (new token)

# Store new token in Kubernetes secret
kubectl set env deployment/checkout-service \
  -n ecommerce \
  STRIPE_OAUTH_TOKEN="sk_live_51234567890..."
# Secret updated; deployment rolling
```

**Step 2: Monitor checkout recovery**
```bash
watch -n 5 'curl -s http://prometheus.ecommerce:9090/api/v1/query --data-urlencode "query=rate(checkout_service_errors_total[1m])" | jq ".data.result[0].value[1]"'
# Error rate should drop from 100% to <0.5% within 2 minutes
```

**Step 3: Implement token renewal retry logic (permanent fix)**
Deploy code change to checkout-service:
```bash
git diff HEAD~1 backend/app/services/stripe_client.py
# Shows: Added ExponentialBackoff(max_retries=5, backoff_factor=2) to token_renewal_request
git commit -m "fix: add retry logic to Stripe token renewal (INC-2025-0118)"
git push origin main

# Redeploy checkout-service
kubectl rollout restart deployment/checkout-service -n ecommerce
# 8 pods restarting with improved token renewal resilience
```

**Step 4: Hardcode Stripe API IPs as fallback (optional)**
```bash
# In checkout-service configuration, add fallback IPs for api.stripe.com and oauth.stripe.com
kubectl set env deployment/checkout-service \
  -n ecommerce \
  STRIPE_API_FALLBACK_IPS="52.89.214.12,52.89.214.13" \
  STRIPE_OAUTH_FALLBACK_IPS="52.89.123.45,52.89.123.46"
# If DNS fails, service will retry using hardcoded IPs
```

#### Follow-Up Actions

1. **Token renewal timeout hardened:** Implement 10-second timeout with 3 retries + exponential backoff
2. **Stripe IP fallback:** Maintain list of Stripe API server IPs for fallback DNS resolution
3. **Token expiry warning:** Log warning at 30% of token lifetime, 10% of lifetime (proactive renewal before hard expiry)
4. **DNS health monitoring:** Add monitoring for internal DNS resolution latency and error rate
5. **Postmortem:** 2025-01-24, review OAuth token management and dependency resilience patterns

---

### INC-2024-0329 — Order Service Database Deadlock Under Concurrent Checkout

**Severity:** P0
**Date:** 2024-11-14
**Duration:** 12 minutes (19:32 UTC – 19:44 UTC)
**On-Call:** Jamie Chen, Payments Platform

#### Description

Black Friday peak traffic hit order-service at 19:32 UTC with concurrent checkout burst (9,200 simultaneous orders/minute, peak baseline 2,100). Order-service's SQL transaction logic locked the `orders` table, then attempted to lock `order_items`. Meanwhile, concurrent transactions attempted the reverse lock order, creating a circular wait (deadlock cycle). PostgreSQL detected the deadlock and killed one of the transactions. Checkout-service received `409 Conflict` responses. P99 checkout latency spiked to 18 seconds (baseline 1.2s). Auto-retry logic caught ~97% of failed orders and succeeded on second attempt, but 3% of orders were lost (user never received "order confirmed").

Alerts triggered:
- `postgres_deadlocks_per_minute > 5` (baseline 0)
- `checkout_service.p99_latency_ms > 10000`
- `order_service.conflict_error_rate > 2%`

#### Impact

- **Checkout conflict rate:** 3% of 9,200 orders = ~276 orders affected
- **Orders rolled back/re-attempted:** ~95% succeeded on retry; ~5% gave up (user abandoned)
- **GMV directly lost:** ~$54,000 (276 orders × $196 ARPU)
- **Customer experience:** ~140 customers saw "order failed" message (some retried successfully)
- **P99 latency during incident:** 18 seconds (5x baseline)

#### Root Cause

Order-service transaction logic acquired locks in inconsistent order:
- **Transaction A:** Lock `orders` table (for new order insert) → then lock `order_items` table (for line items)
- **Transaction B:** Lock `order_items` table first (for inventory check) → then lock `orders` table (for order metadata update)

Under high concurrency:
1. Transaction A locks `orders`, waits for `order_items`
2. Transaction B locks `order_items`, waits for `orders`
3. Circular wait detected by PostgreSQL deadlock detector (~500ms)
4. PostgreSQL kills one transaction (random selection)
5. Killed transaction rolls back; client sees 409 Conflict error
6. Checkout-service retries; new transaction succeeds

#### Resolution Steps

**Step 1: Identify deadlocked queries**
```bash
kubectl logs deployment/order-service -n ecommerce --tail=500 | grep -i "deadlock\|conflict"
# Output: "deadlock detected" messages appear 5-10 times in last 500 logs
```

**Step 2: Reorder SQL lock acquisition (code fix)**
```bash
git diff HEAD~1 backend/app/services/order_service.py
# Shows:
# OLD: INSERT orders table, then INSERT order_items
# NEW: INSERT order_items FIRST (inventory-dependent), then INSERT orders

git commit -m "fix: reorder database locks to prevent deadlock (INC-2024-0329)"
git push origin main

# Redeploy order-service
kubectl rollout restart deployment/order-service -n ecommerce
# 6 pods restarting with consistent lock order
```

**Step 3: Monitor deadlock resolution**
```bash
watch -n 2 'kubectl logs deployment/order-service -n ecommerce --tail=100 | grep -c "deadlock"'
# Deadlock count should drop to 0 within 1 minute of redeploy
```

**Step 4: Monitor checkout latency recovery**
```bash
watch -n 5 'curl -s http://prometheus.ecommerce:9090/api/v1/query --data-urlencode "query=histogram_quantile(0.99, checkout_latency_ms)" | jq ".data.result[0].value[1]"'
# P99 latency should recover from 18s to <2s within 3 minutes
```

**Step 5: Increase checkout-service retry tolerance (temporary)**
```bash
kubectl set env deployment/checkout-service \
  -n ecommerce \
  ORDER_SERVICE_MAX_RETRIES=5 \
  ORDER_SERVICE_RETRY_BACKOFF_MS=200
# Allows checkout-service to retry order creation up to 5 times; helps catch deadlock victims
```

#### Follow-Up Actions

1. **Lock ordering audit:** Review all multi-table transactions in order-service for consistent lock acquisition order
2. **Deadlock prevention test:** Add integration test that simulates concurrent order creation; verify zero deadlocks under 10k RPS
3. **Database index review:** Optimize `order_items` index on `order_id` to reduce lock contention
4. **Explicit transaction isolation level:** Set `SERIALIZABLE` isolation for inventory check transaction (prevents phantom reads, caught earlier)
5. **Postmortem:** 2024-11-16, implement deadlock prevention strategy; consider order-service DB sharding by customer

---

## Failure Mode Catalog

### Failure Mode: Idempotency Key Collision

**Description:** A checkout request is retried with the same idempotency key, but due to Redis eviction or TTL expiration, the key is not found. A second order is created for the same payment.

**Symptoms:**
- Duplicate order in user's account
- Datadog alert: `orders_duplicate_key_rate > 5 per minute`
- Customer reports via support

**Diagnosis:**

1. Check Redis for idempotency key presence:
   ```bash
   redis-cli -h checkout-redis.ecommerce KEYS "idempotency:*" | wc -l
   # Baseline: ~500k keys; if <100k, eviction may be occurring

   redis-cli -h checkout-redis.ecommerce INFO stats | grep evicted_keys
   # Check eviction rate; if >1000/sec, memory is over-committed
   ```

2. Query PostgreSQL for duplicate orders:
   ```bash
   psql $DATABASE_URL -c "
     SELECT user_id, SUM(amount) as duplicate_amount, COUNT(*) as count,
            array_agg(id) as order_ids, array_agg(created_at) as created_times
     FROM orders
     WHERE created_at > NOW() - INTERVAL '1 hour'
     GROUP BY user_id
     HAVING COUNT(*) > 1
     ORDER BY count DESC
     LIMIT 20;
   "
   ```

3. Identify root cause (Redis eviction vs. TTL expiration):
   ```bash
   redis-cli -h checkout-redis.ecommerce CONFIG GET maxmemory-policy
   # Should be "allkeys-lru"; if "noeviction", duplicates indicate code bug

   redis-cli -h checkout-redis.ecommerce CONFIG GET maxmemory
   # Compare used_memory to maxmemory threshold
   ```

**Resolution:**

1. **If Redis eviction is the cause:**
   ```bash
   # Increase Redis maxmemory
   redis-cli -h checkout-redis.ecommerce CONFIG SET maxmemory 10gb
   redis-cli -h checkout-redis.ecommerce CONFIG REWRITE

   # Scale checkout-service replicas to reduce individual instance memory pressure
   kubectl scale deployment/checkout-service --replicas=14 -n ecommerce
   ```

2. **If TTL expiration is the cause:**
   ```bash
   # Extend idempotency key TTL from 1h to 48h
   kubectl set env deployment/checkout-service \
     -n ecommerce \
     IDEMPOTENCY_KEY_TTL_HOURS=48
   ```

3. **Void duplicate orders (manual process):**
   ```bash
   # See INC-2024-0287 Resolution Step 3 for the exact SQL query
   psql $DATABASE_URL << 'SQL'
   WITH duplicates AS (
     SELECT user_id, id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY id ASC) as rn
     FROM orders WHERE created_at > NOW() - INTERVAL '1 hour' AND user_id IN (
       SELECT user_id FROM orders WHERE created_at > NOW() - INTERVAL '1 hour' GROUP BY user_id HAVING COUNT(*) > 1
     )
   )
   UPDATE orders SET status = 'voided', void_reason = 'Idempotency key collision' WHERE id IN (SELECT id FROM duplicates WHERE rn > 1);
   SQL
   ```

---

### Failure Mode: Payment Gateway 502 Storm

**Description:** Payment provider (Stripe or Adyen) returns 502 Bad Gateway responses for capture/refund operations. Checkout-service has no fallback to alternate provider.

**Symptoms:**
- Datadog alert: `payment_gateway_5xx_rate > 10%`
- Error logs: `upstream_error: 502 Bad Gateway (stripe)`
- Slack reports: "payments are broken"

**Diagnosis:**

1. Check payment gateway status:
   ```bash
   curl -s https://status.stripe.com/api/v2/incidents.json | jq '.incidents[0]'
   curl -s https://status.adyen.com/api/v2/incidents.json | jq '.incidents[0]'
   # If an incident is open, gateway is known to be down
   ```

2. Check checkout-service logs:
   ```bash
   kubectl logs deployment/checkout-service -n ecommerce --tail=500 | grep -i "502\|stripe\|gateway"
   # Count 502s and correlate with time
   ```

3. Check circuit breaker state:
   ```bash
   curl http://checkout-service.ecommerce:8000/admin/circuit-breaker/status \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   # Response: { "stripe": { "state": "open", "failures": 124, "last_error": "502 Bad Gateway" } }
   ```

**Resolution:**

1. **Enable fallback payment provider (circuit breaker):**
   ```bash
   curl -X POST http://checkout-service.ecommerce:8000/admin/feature-flags \
     -H "Authorization: Bearer ${ADMIN_TOKEN}" \
     -d '{"flag": "payments.gateway_failover", "enabled": true, "primary": "stripe", "fallback": "adyen"}' \
     -H "Content-Type: application/json"
   # New transactions will route to Adyen (secondary processor)
   ```

2. **Monitor Adyen processing:**
   ```bash
   watch -n 5 'kubectl logs deployment/checkout-service -n ecommerce --tail=100 | grep -E "adyen|gateway"'
   # Verify transactions are processing through Adyen with <2% error rate
   ```

3. **Restore Stripe route (once provider recovers):**
   Monitor Stripe status page for recovery confirmation (no errors for 10+ minutes), then:
   ```bash
   curl -X POST http://checkout-service.ecommerce:8000/admin/feature-flags \
     -H "Authorization: Bearer ${ADMIN_TOKEN}" \
     -d '{"flag": "payments.gateway_failover", "enabled": false}' \
     -H "Content-Type: application/json"
   # Route primary transactions back to Stripe
   ```

4. **Reconcile transactions processed via Adyen:**
   ```bash
   # Query orders created during failover window
   psql $DATABASE_URL -c "
     SELECT id, payment_processor, status, created_at
     FROM orders
     WHERE payment_processor = 'adyen'
       AND created_at BETWEEN '2025-02-10 14:00:00' AND '2025-02-10 14:45:00'
     ORDER BY created_at;
   "
   # Generate settlement report for finance team (monthly reconciliation)
   ```

---

### Failure Mode: Order Creation Database Deadlock

**Description:** PostgreSQL detects a deadlock cycle between checkout-service and order-service transactions updating the orders table. Deadlock victim transaction is rolled back; client receives 409 Conflict error.

**Symptoms:**
- Datadog alert: `postgres_deadlocks_per_minute > 0`
- Checkout-service error rate spikes to 3-5% (increased from baseline <0.1%)
- Logs: `pq: deadlock detected`
- Customer impact: ~1-2% of checkouts fail with "please try again"

**Diagnosis:**

1. Check PostgreSQL active transactions:
   ```bash
   psql $DATABASE_URL -c "
     SELECT
       pg_stat_activity.pid,
       pg_stat_activity.query,
       pg_locks.locktype,
       pg_locks.relation::regclass,
       pg_locks.mode
     FROM pg_stat_activity
     JOIN pg_locks ON pg_stat_activity.pid = pg_locks.pid
     WHERE pg_stat_activity.query NOT ILIKE '%pg_stat_activity%'
     ORDER BY pg_stat_activity.backend_start;
   " | head -20
   ```

2. Identify blocked queries:
   ```bash
   psql $DATABASE_URL -c "
     SELECT
       blocked_locks.pid AS blocked_pid,
       blocked_activity.query AS blocked_query,
       blocking_locks.pid AS blocking_pid,
       blocking_activity.query AS blocking_query,
       blocked_activity.application_name AS blocked_app,
       blocking_activity.application_name AS blocking_app
     FROM pg_catalog.pg_locks blocked_locks
     JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
     JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
       AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
       AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
       AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
       AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
       AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
       AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
       AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
       AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
       AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
       AND blocking_locks.pid != blocked_locks.pid
     JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
     WHERE NOT blocked_locks.granted;
   "
   # Shows which PIDs are blocking others
   ```

3. Check deadlock log for patterns:
   ```bash
   # PostgreSQL log file (location varies; typically /var/log/postgresql/postgresql.log or docker logs)
   kubectl logs deployment/postgres -n ecommerce --tail=200 | grep -i deadlock
   # Example output:
   # ERROR: deadlock detected
   # DETAIL: Process 123 waits for RowExclusiveLock on relation 9999 of relation oid 1234567; blocked by process 456.
   #         Process 456 waits for ShareLock on relation 9999 of relation oid 1234567; blocked by process 123.
   ```

**Resolution:**

1. **Identify blocking PIDs and terminate non-critical ones:**
   ```bash
   # Get PIDs of blocking transactions
   BLOCKING_PIDS=$(psql $DATABASE_URL -t -c "
     SELECT blocking_locks.pid FROM pg_catalog.pg_locks blocking_locks
     WHERE blocking_locks.pid IN (SELECT pid FROM pg_stat_activity WHERE query ILIKE '%order%' AND state = 'idle in transaction')
     LIMIT 3;
   ")

   # Terminate blocking transaction(s) (only if safe; prefer waiting)
   for pid in $BLOCKING_PIDS; do
     echo "Checking PID $pid..."
     psql $DATABASE_URL -c "SELECT pid, query, backend_start FROM pg_stat_activity WHERE pid = $pid;"
     # Review query before terminating; if it's a simple query, wait 30 seconds first
     sleep 30
     psql $DATABASE_URL -c "SELECT pg_terminate_backend($pid);"
   done
   ```

2. **Monitor deadlock resolution:**
   ```bash
   watch -n 2 'psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity WHERE state = \u0027blocked\u0027;"'
   # Should return to 0 after blocking transaction completes or is terminated
   ```

3. **Prevent future deadlocks (code review + deploy):**
   - Ensure all transactions that access orders table use the same lock acquisition order
   - Example: Always lock orders first, then order_items, then payments (consistent ordering)
   - Add test case to validate deadlock-free concurrent updates

4. **Temporary mitigation (if deadlocks continue):**
   ```bash
   # Reduce checkout concurrency by setting a connection pool limit
   kubectl set env deployment/checkout-service \
     -n ecommerce \
     DB_POOL_SIZE=10 \
     DB_POOL_TIMEOUT_S=5
   # Serializes orders table updates; reduces deadlock rate at cost of slightly higher latency
   ```

---

### Failure Mode: Cart Session Stampede on Redis Cache Miss

**Description:** A sudden wave of cart session reads causes Redis cache miss rate to spike. Cart reconstruction falls back to PostgreSQL, creating a thundering herd of database queries. PostgreSQL connection pool exhausts; checkout-service goroutines pile up; P99 latency climbs.

**Symptoms:**
- Datadog alert: `redis_cache_hit_rate < 90%` (baseline >99%)
- High database connection utilization: `postgresql.connection_pool_used_percent > 85%`
- Checkout-service P99 latency > 10s
- Logs: `cart_session_cache_miss` spike

**Diagnosis:**

1. Check Redis hit rate and eviction:
   ```bash
   redis-cli -h checkout-redis.ecommerce INFO stats
   # keyspace_hits: 1234567
   # keyspace_misses: 567890
   # hit_rate = 1234567 / (1234567 + 567890) = 68% (bad; baseline >99%)

   redis-cli -h checkout-redis.ecommerce INFO stats | grep evicted_keys
   # evicted_keys: 45000 (indicates memory pressure)
   ```

2. Check PostgreSQL connection pool:
   ```bash
   psql $DATABASE_URL -c "
     SELECT datname, count(*) as connections, max_conn
     FROM pg_stat_activity, (SELECT setting::int as max_conn FROM pg_settings WHERE name = 'max_connections')
     GROUP BY datname, max_conn;
   "
   # If connections are at 95% of max_conn, pool is exhausted
   ```

3. Check checkout-service goroutine/thread count:
   ```bash
   kubectl exec -it deployment/checkout-service -n ecommerce -- curl -s localhost:6060/debug/pprof/goroutine | head -20
   # If goroutine count is increasing linearly, threads are piling up waiting for I/O
   ```

4. Identify cart session query bottleneck:
   ```bash
   kubectl logs deployment/checkout-service -n ecommerce --tail=300 | \
     grep -i "cart_session\|database\|slow" | \
     awk '{print $NF}' | sort | uniq -c | sort -rn
   ```

**Resolution:**

1. **Increase Redis memory and connection pool:**
   ```bash
   redis-cli -h checkout-redis.ecommerce CONFIG SET maxmemory 10gb
   redis-cli -h checkout-redis.ecommerce CONFIG REWRITE

   # Clear eviction stats
   redis-cli -h checkout-redis.ecommerce CONFIG RESETSTAT
   ```

2. **Scale checkout-service to reduce per-instance pressure:**
   ```bash
   kubectl scale deployment/checkout-service --replicas=16 -n ecommerce
   # Each pod now has fewer active goroutines; reduces I/O wait time
   ```

3. **Implement aggressive cart session pre-warming:**
   ```bash
   # Pre-load hot cart sessions (user sessions expected to checkout in next 30 min)
   kubectl exec -it job/cart-session-preload -n ecommerce -- \
     python scripts/preload_cart_sessions.py \
     --min_session_age_min=5 \
     --max_session_age_hours=2 \
     --batch_size=10000
   # Loaded 847,392 cart sessions from PostgreSQL into Redis in 3 minutes
   ```

4. **Monitor recovery:**
   ```bash
   watch -n 5 'redis-cli -h checkout-redis.ecommerce INFO stats | grep -E "keyspace|used_memory"'
   # Hit rate should return to >99% within 2 minutes

   watch -n 5 'psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity WHERE datname=\u0027ecommerce\u0027;"'
   # Connection count should drop from 95% to <30%
   ```

5. **Investigate root cause of cache miss spike:**
   - Did Redis pod restart? Check: `kubectl get pods -n ecommerce | grep redis`
   - Did a deployment flush cache? Check: `git log --oneline backend/app/services/checkout.py | head -5`
   - Was there a bulk cart deletion (e.g., inactive user cleanup job)? Check cron logs.

---

## Runbook Procedures

### Procedure: Emergency Disable Fraud Check (Allow-All Fallback)

**When to use:** Fraud-service is degraded or unavailable, and checkout success rate has dropped >50%.

**Time to remediate:** 2 minutes

**Procedure:**

1. Verify fraud-service status:
   ```bash
   kubectl get deployment fraud-service -n ecommerce -o wide
   kubectl logs deployment/fraud-service -n ecommerce --tail=50 | head -20
   # If pods are CrashLooping or all Pending, service is down
   ```

2. Enable fraud check bypass (feature flag):
   ```bash
   curl -X POST http://checkout-service.ecommerce:8000/admin/feature-flags \
     -H "Authorization: Bearer ${ADMIN_TOKEN}" \
     -d '{"flag": "fraud_check.allow_on_unavailable", "enabled": true}' \
     -H "Content-Type: application/json"
   # Flag enabled; checkout requests now skip fraud scoring
   ```

3. Monitor checkout recovery:
   ```bash
   watch -n 5 'curl -s http://prometheus.ecommerce:9090/api/v1/query --data-urlencode "query=rate(checkout_service_errors_total[1m])" | jq ".data.result"'
   # Error rate should drop from 50%+ to <1% within 1 minute
   ```

4. Once fraud-service is stable, disable bypass:
   ```bash
   curl -X POST http://checkout-service.ecommerce:8000/admin/feature-flags \
     -H "Authorization: Bearer ${ADMIN_TOKEN}" \
     -d '{"flag": "fraud_check.allow_on_unavailable", "enabled": false}' \
     -H "Content-Type: application/json"
   # Flag disabled; fraud checks resume
   ```

5. Review orders placed during bypass (optional, for compliance):
   ```bash
   psql $DATABASE_URL -c "
     SELECT COUNT(*), SUM(amount) as total_gmv
     FROM orders
     WHERE created_at BETWEEN '2025-02-10 14:15:00' AND '2025-02-10 14:25:00'
       AND fraud_check_bypassed = true;
   "
   # Useful for fraud team post-incident analysis
   ```

---

### Procedure: Rollback Payment Gateway Configuration

**When to use:** Recent payment gateway config change (API version, routing rules, auth credentials) is causing failures.

**Time to remediate:** 3 minutes

**Procedure:**

1. Identify recent config changes:
   ```bash
   git log --oneline backend/config/payment_gateway.yml | head -10
   # Find the commit that changed payment processor config
   ```

2. View the previous working config:
   ```bash
   git show HEAD~1:backend/config/payment_gateway.yml | head -50
   # Confirm the previous config looks correct
   ```

3. Rollback the config file:
   ```bash
   git revert HEAD --no-edit  # Creates a new commit that reverts the last change
   # Or:
   git checkout HEAD~1 -- backend/config/payment_gateway.yml
   git commit -m "rollback: payment gateway config (INC-2025-XXXX)"
   ```

4. Redeploy checkout-service with old config:
   ```bash
   kubectl rollout restart deployment/checkout-service -n ecommerce
   # 8 replicas rolling; restart ETA 30-45 seconds
   ```

5. Verify checkout success:
   ```bash
   watch -n 3 'curl -s http://prometheus.ecommerce:9090/api/v1/query --data-urlencode "query=rate(checkout_service_errors_total[1m])" | jq ".data.result[0].value[1]"'
   # Error rate should return to <0.5% baseline
   ```

6. Test a manual payment:
   ```bash
   curl -X POST http://localhost:8000/api/test/checkout \
     -H "Content-Type: application/json" \
     -d '{"user_id": "test_user_123", "items": [{"sku": "TEST-001", "qty": 1}]}' \
     -H "X-Admin-Token: ${ADMIN_TOKEN}"
   # Should complete successfully with status: "success"
   ```

7. Investigate root cause of config issue offline (after incident is resolved).

---

### Procedure: Drain and Replay Failed Payment Events from DLQ

**When to use:** Payment webhooks or async events were dropped due to a service outage. DLQ has accumulated unprocessed events that need to be replayed.

**Time to remediate:** 10-30 minutes (depending on queue size)

**Procedure:**

1. Check DLQ size:
   ```bash
   # RabbitMQ management API
   curl -u guest:guest http://rabbitmq.ecommerce:15672/api/queues/%2F/payment_events_dlq | jq '.messages'
   # Or via kubectl logs:
   kubectl logs deployment/celery-worker -n ecommerce --tail=100 | grep -i dlq
   ```

2. Review sample messages from DLQ:
   ```bash
   # Connect to RabbitMQ CLI
   kubectl exec -it deployment/rabbitmq -n ecommerce -- rabbitmqctl list_queues

   # Use management UI (if available)
   # Navigate to http://rabbitmq.ecommerce:15672 (guest:guest)
   # Select queue "payment_events_dlq"
   # Review message payload to understand failure reason
   ```

3. Determine if events are recoverable:
   - **Webhook events:** Check timestamp; if >24h old, may be stale (Stripe/Adyen webhook signature expires)
   - **Idempotency:** Check if order was already created (via idempotency key lookup)
   - **Payment status:** Verify actual payment status via payment provider API (Stripe: `stripe charges list --limit 100`)

4. Drain DLQ into replay queue:
   ```bash
   # Create a replay queue (temporary)
   kubectl exec -it deployment/celery-worker -n ecommerce -- \
     python -c "
       from app.workers.celery_app import app
       from kombu import Exchange, Queue

       # List all messages in DLQ
       with app.connection() as conn:
           with conn.channel() as channel:
               queue = Queue('payment_events_dlq', exchange=Exchange('payment_events', type='topic'))
               messages = queue(channel).get()  # Simple peek; production use a more robust drainer
               for msg in messages:
                   print(f'Event: {msg.body}')
     "
   ```

5. Replay events via admin API:
   ```bash
   # Option A: Bulk replay via admin endpoint
   curl -X POST http://checkout-service.ecommerce:8000/admin/replay-events \
     -H "Authorization: Bearer ${ADMIN_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{"queue": "payment_events_dlq", "limit": 1000}' \
   # Returns: { "replayed": 847, "failed": 12, "skipped": 141 }
   ```

6. Monitor replay progress:
   ```bash
   watch -n 5 'curl -u guest:guest http://rabbitmq.ecommerce:15672/api/queues/%2F/payment_events_dlq | jq ".messages"'
   # Message count should decrease as events are processed
   ```

7. Verify order creation from replayed events:
   ```bash
   psql $DATABASE_URL -c "
     SELECT DATE(created_at) as creation_date, COUNT(*) as order_count, SUM(amount) as gmv
     FROM orders
     WHERE created_at > NOW() - INTERVAL '6 hours'
     GROUP BY DATE(created_at)
     ORDER BY creation_date DESC;
   "
   # Confirm orders were created during replay window
   ```

8. Clean up DLQ (once verified):
   ```bash
   # Purge remaining messages (optional; only if they are unrecoverable)
   curl -u guest:guest -X DELETE http://rabbitmq.ecommerce:15672/api/queues/%2F/payment_events_dlq/contents
   # Warning: This is destructive; only do if reviewed and approved by on-call lead
   ```

---

## Monitoring & Alerts

### Key Metrics & Dashboard

**Dashboard:** Datadog → Payments Platform → Checkout & Payments (link: https://app.datadoghq.com/dashboard/list?query=payments)

| Metric Name | Query | Baseline | Alert Threshold | Severity |
|---|---|---|---|---|
| Checkout success rate | `100 * checkout_requests_success / checkout_requests_total` | >99.2% | <99.0% over 5 min | P1 |
| Checkout P99 latency | `histogram_quantile(0.99, checkout_latency_ms)` | <1.2s | >3s over 5 min | P1 |
| Payment error rate | `100 * payment_errors_total / payment_requests_total` | <0.08% | >0.15% over 2 min | P1 |
| Payment gateway P99 | `histogram_quantile(0.99, payment_gateway_latency_ms)` | <600ms | >2000ms over 5 min | P2 |
| Fraud service timeout rate | `100 * fraud_service_timeouts / fraud_service_requests` | <0.1% | >1% over 2 min | P2 |
| Redis cache hit rate | `100 * redis_hits / (redis_hits + redis_misses)` | >99% | <90% over 2 min | P2 |
| Redis memory usage | `redis_memory_used_percent` | <60% | >85% over 5 min | P2 |
| PostgreSQL connections used | `postgresql_connections_used / postgresql_max_connections` | <30% | >85% over 2 min | P2 |
| Order creation latency | `histogram_quantile(0.99, order_creation_latency_ms)` | <200ms | >500ms over 5 min | P2 |
| Idempotency key cache hit rate | `100 * idempotency_hits / (idempotency_hits + idempotency_misses)` | >99.8% | <95% over 5 min | P3 |
| Webhook ingestion rate | `rate(webhook_events_received_total[1m])` | 2,500/min (baseline) | >15,000/min | P1 |

### Alert Rules (Datadog/Prometheus)

```yaml
# Checkout success rate alert
alert:
  name: "Checkout success rate critical"
  query: "avg(last_5m): (100 * avg:checkout_requests_success{service:checkout-service} / avg:checkout_requests_total{service:checkout-service}) < 99"
  severity: "critical"
  on_missing: "resolve"
  no_data_timeframe: 5

# Checkout latency alert
alert:
  name: "Checkout P99 latency spike"
  query: "avg(last_5m): pct99(checkout_latency_ms{service:checkout-service}) > 3000"
  severity: "critical"

# Payment error rate alert
alert:
  name: "Payment error rate spike"
  query: "avg(last_2m): (100 * rate(payment_errors_total{service:checkout-service}[2m]) / rate(payment_requests_total{service:checkout-service}[2m])) > 0.15"
  severity: "critical"

# Redis memory alert
alert:
  name: "Checkout Redis memory pressure"
  query: "avg(last_5m): redis_memory_used_percent{redis:checkout-redis} > 85"
  severity: "warning"

# Fraud service timeout alert
alert:
  name: "Fraud service timeout spike"
  query: "avg(last_2m): (100 * rate(fraud_service_timeouts_total{service:fraud-service}[2m]) / rate(fraud_service_requests_total{service:fraud-service}[2m])) > 1"
  severity: "warning"

# PostgreSQL connection exhaustion alert
alert:
  name: "PostgreSQL connection pool near exhaustion"
  query: "avg(last_2m): (postgresql_connections_used{db:ecommerce} / 100) > 85"
  severity: "warning"
```

### Custom Metrics to Add

1. **Duplicate order detection rate:**
   ```
   duplicate_order_rate = COUNT(orders with duplicate user_id+amount within 10s) per minute
   Alert if > 5/min
   ```

2. **Fraud-service cold-start duration:**
   ```
   fraud_service_startup_duration_ms = Time from pod ready to /health/ready endpoint response
   Alert if > 5000ms (cold start should be <2s)
   ```

3. **Checkout-service goroutine count:**
   ```
   checkout_service_goroutine_count = /debug/pprof/goroutine count
   Alert if linearly increasing (indicates goroutine leak)
   ```

4. **Payment webhook duplicate rate:**
   ```
   webhook_duplicate_rate = Duplicate event.id count per minute
   Alert if > 100/min (baseline ~0)
   ```

---

## Escalation Policy

### Severity Definitions

| Severity | SLA | Description | Example |
|---|---|---|---|
| **P0** | <15 min | Critical, service down/severely degraded, >10% checkout failure | Black Friday latency spike (INC-2024-0112) |
| **P1** | <30 min | Major, >1% checkout failure or >0.5% payment error rate | Fraud-service timeout cascade (INC-2025-0044) |
| **P2** | <2 hours | Moderate, <1% checkout failure, no customer impact yet | High Redis memory usage (pre-incident) |
| **P3** | <24 hours | Low, monitoring only, no customer impact | Minor logging format issue |

### Escalation Tiers

**Tier 1: Payments Platform On-Call Engineer**
- **Activation:** Any P0/P1 incident
- **Response SLA:** <5 minutes
- **Actions:**
  - Page on-call (PagerDuty: `payments-platform-oncall`)
  - Join Slack war room: `#payments-incidents`
  - Begin incident investigation and communicate status every 5 minutes
- **Escalation criteria:**
  - Unable to identify root cause within 15 minutes (P0) or 30 minutes (P1)
  - Need external expertise (payment provider support, infrastructure, security)

**Tier 2: Payments Platform Tech Lead**
- **Activation:** P0 incident unresolved after 10 minutes, or on-call request
- **Response SLA:** <10 minutes
- **Actions:**
  - Review on-call's investigation, provide guidance
  - Make escalation decision (product, VP Eng, payment provider)
  - Ensure incident commander is driving towards resolution
- **Contact:** Slack `@payments-tech-lead` or PagerDuty

**Tier 3: VP Engineering**
- **Activation:** P0 incident >20 minutes unresolved, or potential customer-facing liability
- **Response SLA:** <15 minutes
- **Actions:**
  - Coordinate with finance, customer success, payment provider support teams
  - Make business decisions (feature flag kill-switches, allow-list overrides, provider failover)
  - Stakeholder communication (customer-facing incident notification if >1% impact)
- **Contact:** PagerDuty → VP Eng page

**Tier 4: External Escalation**
- **Payment provider support:** P0 incident, suspicion of Stripe/Adyen infrastructure issue
  - Slack: Contact payments-team lead to open support ticket
  - Provide: API error codes, webhook delivery logs, transaction IDs, affected geography
- **Security team:** If incident involves fraud, duplicate charges, or data exposure
  - Slack: `#security-incidents`
- **Finance/Accounting:** If incident results in duplicate charges, refunds, or revenue impact >$100k
  - Slack: `#finance`

### Communication Template

**Incident Announcement (Slack #payments-incidents, immediately upon P0/P1)**
```
🚨 P[0/1] INCIDENT: [Service Name]

Title: [Brief description]
Status: INVESTIGATING
Started: [UTC time]
Impact: [Checkout success: X%, Payment error rate: X%, Users affected: ~N]

Current Actions:
- [Action 1]
- [Action 2]

Next Update: [+5 min]
On-Call: @[name]
```

**Status Update (every 5 minutes during P0, every 10 min during P1)**
```
📊 Update @ [UTC time] (+[elapsed minutes])

Root Cause: [hypothesis or confirmed cause]
Status: [INVESTIGATING / MITIGATING / RECOVERING / RESOLVED]
ETA Resolution: [X minutes]

Actions Completed:
- [Rollback, config change, etc.]

Next Actions:
- [Next step]

Slack thread: [link]
Datadog dashboard: [link]
PagerDuty incident: [link]
```

**Resolution Summary (once incident is resolved)**
```
✅ RESOLVED @ [UTC time] (+[total duration])

Root Cause: [Final confirmed cause]
Impact: [Final customer impact numbers]
Resolution: [What fixed it]

Action Items for Follow-Up:
1. [Postmortem scheduled for YYYY-MM-DD]
2. [Monitoring improvements]
3. [Code/config changes to prevent recurrence]

Incident link: [PagerDuty]
```

### War Room Protocol

**For P0 Incidents:**
1. Declare P0 in Slack; page on-call via PagerDuty
2. Create Zoom link (Slack integration auto-creates) or jump on Slack Huddle
3. Designate **Incident Commander** (usually on-call); they drive conversation and decision-making
4. Incident Commander keeps attendees focused: diagnosis → mitigation → resolution
5. Log all actions in Slack thread; do not split communication across DMs
6. Tech Lead provides guidance; IC makes calls; do not debate for >2 minutes without action
7. Every 5 minutes: IC posts status update (root cause hypothesis, ETA, next action)
8. Once resolved, IC schedules postmortem for within 48 hours

**For P1 Incidents:**
1. Page on-call; optional Slack Huddle (can investigate in parallel)
2. Status updates every 10 minutes in Slack thread
3. IC ensures clear action plan and progress tracking

---

## Inter-Service Impact Map

When Checkout & Payments degrades, the cascade looks like:

| Stage | Service | Impact | Time to Detect |
|---|---|---|---|
| Immediate | checkout-service | checkout errors spike, P99 latency >3s | <1 min |
| +2 min | order-service | order creation backed up, pending orders accumulate | +2 min |
| +5 min | notification-service | order confirmation emails queued, delivery delay | +5 min |
| +10 min | webhook-service | merchant notifications delayed, order status updates stuck | +10 min |
| +15 min | analytics-service | order data pipeline backed up, reporting lag | +15 min |

**How to read this:** If checkout-service is down for N minutes, expect these downstream services to start failing or degrading at the indicated intervals.

**Isolation actions:** Enable circuit breaker on checkout-service (return "temporarily unavailable" instead of 500 errors). Trigger fallback: guest checkout without fraud checks for orders <$500. Scale order-service DB connections if backup occurs.

---

## Rollback Decision Tree

**When to rollback vs. hotfix:**

1. Error rate >5% for >3 minutes?
   - YES → If error is from a checkout-service deploy within last 1 hour, rollback immediately
   - NO → Proceed to step 2

2. Impact quantified (>$50k GMV loss or >1,000 failed checkouts)?
   - YES → Rollback if it's an application code issue. Hotfix if it's config/fraud rules.
   - NO → Wait 5 minutes for pattern to stabilize; don't panic-rollback

3. Root cause identified with high confidence?
   - HIGH (e.g., null pointer, obvious deploy issue) → Rollback if recent deploy
   - LOW (intermittent, unclear) → Wait and gather more data

**Quick rollback command:**
```bash
kubectl rollout undo deployment/checkout-service -n ecommerce
kubectl rollout status deployment/checkout-service -n ecommerce --timeout=3m
```

**Verification after rollback:**
- Error rate drops to <0.1% within 2 minutes
- P99 checkout latency recovers to <3s
- Fraud check latency returns to baseline (<200ms)
- No spike in manual refunds or customer complaints

---

## Additional Resources

- **Runbook source repo:** `git clone https://github.com/company/payments-platform-runbooks.git`
- **Database schema:** `/Users/felix/incident-triage/backend/app/models/database.py`
- **Configuration:** `/Users/felix/incident-triage/backend/config/payment_gateway.yml`
- **Datadog dashboard:** https://app.datadoghq.com/dashboard/list?query=payments
- **PagerDuty on-call schedule:** https://company.pagerduty.com/schedules#/teams/payments-platform-oncall
- **Slack channels:** `#payments-incidents`, `#payments-platform`, `#payments-eng`
- **Payment provider docs:**
  - Stripe: https://stripe.com/docs
  - Adyen: https://docs.adyen.com
  - Stripe webhook signatures: https://stripe.com/docs/webhooks/signatures
  - Adyen idempotency: https://docs.adyen.com/development-resources/api-idempotency
- **Internal wiki:** https://wiki.company.com/payments (Runbook deep-dives, architecture diagrams, FAQ)

---

*Last updated: 2025-02-03*
*Maintained by: Payments Platform Team*
*Next review: 2025-05-03*
