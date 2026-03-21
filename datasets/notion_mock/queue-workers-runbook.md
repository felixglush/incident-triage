# Queue & Workers Runbook

## Service Overview

**Service:** Queue & Workers (RabbitMQ + Celery workers)
**Owners:** Platform Engineering team
**PagerDuty:** platform-engineering-oncall
**Severity:** P0–P3

### Architecture

- **Message Broker:** RabbitMQ 3.12 (3-node HA cluster, quorum queues enabled)
- **RabbitMQ Cluster Nodes:** rabbitmq-0, rabbitmq-1, rabbitmq-2 in Kubernetes namespace `ecommerce`
- **Management UI:** http://rabbitmq:15672 (credentials in vault: `rabbitmq_admin_user`, `rabbitmq_admin_password`)
- **Worker Types & Replicas:**
  - `order-worker` (12 replicas, HPA 2–50) — inventory reserve → payment capture → 3PL submission
  - `notification-worker` (6 replicas, HPA 1–30) — email/SMS/push via SendGrid/Twilio
  - `webhook-worker` (4 replicas, HPA 1–20) — outbound merchant webhooks with exponential backoff
  - `fulfillment-worker` (2 replicas, HPA 1–10) — 3PL shipping status polling
- **Dead Letter Queues (DLQs):** Each worker type has a corresponding DLQ for failed messages (e.g., `order_dlq`, `notification_dlq`, `webhook_delivery_dlq`, `fulfillment_dlq`)

### Key Dependencies

- PostgreSQL (order state, merchant config, webhook logs)
- SendGrid API (email delivery)
- Twilio API (SMS delivery)
- Third-party 3PL APIs (ShipBob, Shopify Fulfillment Network)
- External merchant webhook endpoints

### SLOs

| Metric | SLO | Alert Threshold |
|--------|-----|-----------------|
| Order processing (end-to-end) | P99 <30s | >45s |
| Notification delivery | <2 min | >3 min |
| Webhook delivery (with 3 retries) | <5 min | >10 min |
| DLQ depth | 0 messages | >10 messages |
| RabbitMQ memory usage | <70% | >75% |
| Worker pod restart count (1h) | 0 | >1 restart |

---

## Recorded Incidents

### INC-2024-0118 — Order Queue Backlog During Black Friday

**Date:** 2024-11-29 (Black Friday)
**Severity:** P0 (Critical)
**Duration:** 180 minutes (12:00 UTC to 13:30 UTC)
**Affected Services:** Order processing, order confirmations
**Customer Impact:** ~12,000 support contacts, $45k support cost, orders delayed up to 11 hours

**Description:**

Black Friday order volume spiked to 1,400 orders/minute (11.7× normal baseline of ~120 orders/min). The `order-worker` HPA had `maxReplicas=4` hardcoded in a legacy config. With only 4 pods processing ~480 orders/min, the order queue backlog grew at 920 messages/minute.

By 12:00 UTC, the `order_processing` queue had accumulated 87,200 messages. Order confirmation emails queued behind the processing delay, resulting in customers not receiving confirmations for up to 11 hours. Support team was overwhelmed with "where's my order?" inquiries.

**Root Cause:**

- HPA maxReplicas cap of 4 was insufficient for peak volume.
- No pre-event capacity planning or scaling trigger.
- Order processing is the critical path for fulfillment; queue depth was not monitored with aggressive alerting.

**Resolution Steps:**

1. **Increase HPA maxReplicas:**
   ```bash
   kubectl patch hpa order-worker -n ecommerce \
     -p '{"spec":{"maxReplicas":50}}'
   ```

2. **Manually scale to handle backlog:**
   ```bash
   kubectl scale deployment/order-worker --replicas=24 -n ecommerce
   ```

3. **Monitor queue drain rate (should drop ~800 msgs/min):**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/order_processing | jq '.messages'
   ```
   Repeat every 30 seconds. Queue drained from 87,200 to <1,000 in 90 minutes.

4. **Verify all order-worker pods are ready:**
   ```bash
   kubectl get pods -n ecommerce -l app=order-worker -w
   ```

5. **Check for any messages in DLQ (should be 0):**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/order_dlq | jq '.messages'
   ```

6. **Post-drain, gradually scale down to normal (12 replicas):**
   ```bash
   kubectl scale deployment/order-worker --replicas=12 -n ecommerce
   ```

**Follow-up Actions:**

- Updated HPA maxReplicas from 4 to 50 (committed to config repo).
- Implemented pre-sale capacity checklist: load test 48 hours before major events; confirm HPA limits sufficient.
- Reduced queue depth alert threshold from 10,000 to 1,000 messages (fires sooner).
- Added queue depth graph to on-call dashboard.
- Implemented automatic scale-up trigger when queue depth >500 for >5 min.

---

### INC-2024-0377 — Notification Worker Crash Loop

**Date:** 2024-12-03
**Severity:** P1 (High)
**Duration:** 120 minutes (13:20 UTC to 15:20 UTC)
**Affected Services:** Email/SMS/push notifications
**Customer Impact:** 34,000 emails delayed or undelivered; customers did not receive order confirmations or status updates

**Description:**

A code deploy added a new email template that referenced an `order.gift_message` field. The field was nullable in the schema, but the template called `.upper()` on it without a null check. When the first notification message was processed, an `AttributeError: 'NoneType' has no attribute 'upper'` exception occurred, crashing the worker. Kubernetes automatically restarted the pod, which immediately picked up the next message in the queue and crashed again—a crash loop.

All 3 `notification-worker` replicas entered `CrashLoopBackOff` state within 2 minutes. The `notification_queue` accumulated 34,000 pending messages over 2 hours with no progress.

**Root Cause:**

- Template development did not include null checks for optional fields.
- Missing integration test coverage for null/optional fields in templates.
- No pre-deploy validation that templates match actual schema.
- Worker process crashed instead of dead-lettering failed messages.

**Resolution Steps:**

1. **Immediately rollback the deployment:**
   ```bash
   kubectl rollout undo deployment/notification-worker -n ecommerce
   ```
   Workers recover within 30 seconds as they are restarted with the previous known-good image.

2. **Verify pods are running:**
   ```bash
   kubectl get pods -n ecommerce -l app=notification-worker
   ```
   All replicas should be in `Running` status.

3. **Check queue depth (should be 34,000+):**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/notification_queue | jq '.messages'
   ```

4. **Replay the DLQ back to the main queue using RabbitMQ Shovel:**
   ```bash
   # Check if shovel already exists
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/shovels | jq '.[] | select(.name == "notification_replay")'

   # Define shovel (one-time or persistent)
   curl -X PUT -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/shovels/%2F/notification_replay \
     -H "Content-Type: application/json" \
     -d '{
       "source-protocol": "amqp091",
       "source": {
         "brokers": ["amqp://rabbitmq-0,rabbitmq-1,rabbitmq-2"],
         "queue": "notification_dlq"
       },
       "destination-protocol": "amqp091",
       "destination": {
         "brokers": ["amqp://rabbitmq-0,rabbitmq-1,rabbitmq-2"],
         "queue": "notification_queue"
       },
       "ack-mode": "on-confirm"
     }'
   ```

5. **Monitor message drain from DLQ:**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/notification_dlq | jq '.messages'
   ```
   Should decrease as messages are replayed.

6. **Verify workers are processing (check logs for successful message count):**
   ```bash
   kubectl logs deployment/notification-worker -n ecommerce --since=5m \
     | grep -c "processed"
   ```

7. **Once queue is drained, delete the shovel:**
   ```bash
   curl -X DELETE -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/shovels/%2F/notification_replay
   ```

**Follow-up Actions:**

- Added null guards on all email/SMS/push template fields; made template rendering fail-safe with `.upper() if field else ''`.
- Implemented integration tests for each template with null/optional field combinations.
- Modified worker exception handler to dead-letter after 3 automatic retries instead of crashing immediately.
- Pre-deploy validation script added to CI that checks template field references against schema.

---

### INC-2025-0058 — Webhook Delivery Retry Storm

**Date:** 2025-03-01
**Severity:** P1 (High)
**Duration:** 240 minutes (14:00 UTC to 18:00 UTC)
**Affected Services:** Webhook delivery, order processing (degraded), notification processing (degraded)
**Customer Impact:** Merchant webhooks not delivered for 4+ hours; merchant integrations stalled; downstream order processing impacted

**Description:**

Merchant ID 4892 deployed a buggy webhook endpoint that returned HTTP 500 for all requests. The `webhook-worker` implemented exponential backoff (1s, 2s, 4s, 8s, 16s, …) and retried indefinitely. Over 4 hours, 1.2 million retry attempts were queued specifically for this merchant.

The `webhook_delivery_merchant_4892` queue consumed ~2 GB of RabbitMQ memory. Overall broker memory hit 78%, triggering kernel memory pressure. All other merchant webhook delivery was degraded (60% slower) due to broker contention. Order-worker latency spiked: P99 increased from 25s to 45s because the broker was spending CPU/memory on webhook retry storms instead of order processing.

**Root Cause:**

- No per-merchant circuit breaker (should pause after N consecutive failures).
- No per-merchant queue depth cap (unlimited retries queued).
- Webhook endpoint health not monitored before accepting retries.
- Exponential backoff had no maximum ceiling; retries grew unbounded.

**Resolution Steps:**

1. **Immediately pause retries for merchant 4892:**
   ```bash
   psql ${DATABASE_URL} <<EOF
   UPDATE merchant_webhook_configs
   SET active=false, paused_reason='INC-2025-0058 - Webhook endpoint returning 500'
   WHERE merchant_id=4892;
   EOF
   ```

2. **Purge queued messages for this merchant (use celery to purge just that queue):**
   ```bash
   kubectl exec deployment/webhook-worker -n ecommerce -- \
     python -c "
   from app.workers.celery_app import celery_app
   celery_app.control.purge()  # General purge if needed, OR:
   from kombu import Queue
   from app.workers.celery_app import celery_app
   celery_app.connection_or_acquire().default_channel.queue_purge('webhook_delivery_merchant_4892')
   "
   ```

3. **Monitor broker memory recovery (should drop from 78% to <50% in 5 min):**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/overview | jq '.node | {memory_used, memory_limit}'
   ```

4. **Verify order-worker latency recovers:**
   ```bash
   kubectl logs deployment/order-worker -n ecommerce --tail=100 \
     | grep "latency_p99_ms"
   ```
   Should drop back toward 25–30s.

5. **Notify merchant 4892 (via support):**
   - Their webhook endpoint is returning 500; ask them to fix and re-enable.
   - Provide link to webhook logs in dashboard.

6. **Re-enable merchant once they confirm the fix:**
   ```bash
   psql ${DATABASE_URL} <<EOF
   UPDATE merchant_webhook_configs
   SET active=true, paused_reason=NULL
   WHERE merchant_id=4892;
   EOF
   ```

**Follow-up Actions:**

- Implemented per-merchant circuit breaker in webhook-worker: pause after 10 consecutive 5xx failures; auto-resume after 1 hour.
- Added per-merchant queue depth cap at 10,000 messages; oldest messages dropped if exceeded (instead of unbounded growth).
- Increased webhook delivery alert threshold from >100,000 to >10,000 queued messages.
- Added per-merchant queue depth metric to dashboard (top 10 merchants by queue depth).
- Implemented exponential backoff ceiling: max 5-minute delay between retries.
- Webhook endpoint health check endpoint: before accepting retry for a merchant, check a `/health` endpoint first.

---

### INC-2024-0298 — Message Encoding Mismatch Breaking Webhook Worker

**Date:** 2024-09-18
**Severity:** P1 (High)
**Duration:** 45 minutes (11:15 UTC to 12:00 UTC)
**Affected Services:** Webhook delivery
**Customer Impact:** 12,000 webhooks queued for 1 hour; merchant integrations stalled; incomplete webhook delivery

**Description:**

A deploy changed the message encoding from UTF-8 to UTF-16 in the message serializer. The `webhook-worker` code was hardcoded to expect UTF-8 and attempted to decode all payloads as UTF-8. When the first UTF-16 message arrived, the decoder threw `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0`, causing the worker to crash.

All 4 `webhook-worker` replicas crashed within 30 seconds. Over 60 minutes, 12,000 webhook delivery messages accumulated in the `webhook_delivery` queue with no workers consuming them.

**Root Cause:**

- Deploy changed message encoding globally without coordination with worker code.
- No pre-deploy validation that encoding matches what workers expect.
- Worker used hardcoded encoding instead of reading from message headers.
- No integration test covering encoding/decoding round-trip.

**Resolution Steps:**

1. **Immediately rollback the encoding change deploy:**
   ```bash
   kubectl rollout undo deployment/webhook-worker -n ecommerce
   kubectl rollout status deployment/webhook-worker -n ecommerce --timeout=3m
   ```
   Workers recover within 30 seconds as they restart with the previous encoding.

2. **Verify pods are running:**
   ```bash
   kubectl get pods -n ecommerce -l app=webhook-worker
   ```

3. **Check queue depth (should be 12,000+):**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/webhook_delivery | jq '.messages'
   ```

4. **Monitor queue drain (messages should decrease):**
   ```bash
   watch -n 30 "curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/webhook_delivery | jq '.messages'"
   ```
   Queue should drain at ~400 msgs/min with 4 replicas; complete in ~30 min.

5. **Verify DLQ is empty (no webhook delivery failures):**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/webhook_delivery_dlq | jq '.messages'
   ```

**Follow-up Actions:**

- Modified message serializer to include encoding in message headers; worker reads header instead of assuming.
- Added integration test for UTF-8 and UTF-16 message serialization/deserialization round-trip.
- Updated CI to validate message encoding consistency across all worker types before merge.

---

### INC-2025-0073 — Celery Task Timeout Too Short for Large Orders

**Date:** 2025-03-03
**Severity:** P1 (High)
**Duration:** 120 minutes (09:30 UTC to 11:30 UTC)
**Affected Services:** Order processing
**Customer Impact:** ~850 large orders (>100 line items) processed twice; duplicate payments, duplicate inventory holds; customer complaints

**Description:**

The `order-worker` had a Celery task timeout of 60 seconds. A code change added comprehensive inventory checks and fraud detection logic, increasing task execution time for large orders (>100 line items). Orders with 100–200 line items now took 75–95 seconds to process. When the 60-second timeout fired, the task was marked as failed and automatically retried. Some orders were processed and paid twice before being noticed.

Monitoring showed 850 task retries over 2 hours for the same order IDs, indicating a systematic timeout issue.

**Root Cause:**

- Task timeout was not updated when logic was added.
- No pre-deploy load test simulating large orders (>100 line items).
- Celery auto-retry was triggering false failures on slow but successful tasks.
- No per-task idempotency key to prevent duplicate processing.

**Resolution Steps:**

1. **Immediately increase the Celery task timeout:**
   ```bash
   kubectl set env deployment/order-worker -n ecommerce CELERY_TASK_TIME_LIMIT=180
   kubectl rollout restart deployment/order-worker -n ecommerce
   ```
   Increase timeout from 60s to 180s to accommodate large order processing.

2. **Verify deployment is rolling out:**
   ```bash
   kubectl rollout status deployment/order-worker -n ecommerce --timeout=5m
   ```

3. **Monitor task error rate (should drop to near 0%):**
   ```bash
   kubectl logs deployment/order-worker -n ecommerce --tail=50 \
     | grep -c "task timeout"
   ```

4. **Check for duplicate orders in database:**
   ```bash
   psql ${DATABASE_URL} <<EOF
   SELECT order_id, COUNT(*) as count FROM orders
   WHERE created_at > now() - interval '3 hours'
   GROUP BY order_id HAVING COUNT(*) > 1;
   EOF
   ```

5. **If duplicates found, escalate to Payments team for refund reconciliation:**
   - Identify duplicate payment charges and issue refunds.
   - Consolidate inventory holds to single order.

**Follow-up Actions:**

- Increased base Celery task timeout from 60s to 180s in config.
- Added per-order idempotency key; worker checks if order was already processed before executing (upsert logic).
- Implemented pre-deploy load test with orders >100 line items; measure actual execution time and set timeout to 1.5x max observed.
- Added task execution time metrics/histogram to monitor slow tasks (P99 latency).

---

### INC-2024-0412 — Notification Queue Memory Leak from Unserialized Attachments

**Date:** 2024-11-25
**Severity:** P1 (High)
**Duration:** 480 minutes (08:00 UTC to 16:00 UTC)
**Affected Services:** Notification delivery (email, SMS, push)
**Customer Impact:** 300,000+ notifications queued or undelivered; customers did not receive order status updates, shipping confirmations

**Description:**

The `notification-worker` code cached email attachment objects (file handles, binary data) in memory without clearing them after processing. As the worker processed messages sequentially, attachment objects accumulated in the Python process memory. Over 8 hours of continuous processing, memory usage grew from 100 MB to 2.0 GB, eventually hitting the pod memory limit (2 GB) and triggering an OOM (Out-of-Memory) kill.

The pod would restart, process more messages, and memory would grow again—creating a cycle of crashes and restarts. All 6 replicas were cycling in and out of `OOMKilled` state. No notifications were being delivered reliably.

**Root Cause:**

- Attachment objects cached in worker process memory without cleanup.
- No periodic garbage collection or cache eviction.
- Worker did not implement `del` or clear() after processing each message.
- No memory monitoring or alert for worker memory growth.

**Resolution Steps:**

1. **Immediately patch the worker to clear attachment cache after each message:**
   ```bash
   # Push hot-fix patch:
   # In notification-worker code, after processing each message, add:
   #   attachment_cache.clear()
   #   gc.collect()  # Force garbage collection

   kubectl set image deployment/notification-worker -n ecommerce \
     notification-worker=your-registry/notification-worker:fix-mem-leak
   kubectl rollout restart deployment/notification-worker -n ecommerce
   ```

2. **Verify deployment is healthy (pods should stay running, not restart):**
   ```bash
   kubectl get pods -n ecommerce -l app=notification-worker -w
   # Wait 5 min; pods should stay Running without restarts.
   ```

3. **Monitor memory usage (should stabilize ~150–200 MB per pod):**
   ```bash
   kubectl top pods -n ecommerce -l app=notification-worker
   ```

4. **Monitor queue drain (notifications should start being delivered):**
   ```bash
   watch -n 30 "curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/notification_queue | jq '.messages'"
   ```

5. **Verify no messages in DLQ (should be 0):**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/notification_dlq | jq '.messages'
   ```

**Follow-up Actions:**

- Modified worker to call `attachment_cache.clear()` after every 100 processed messages (batched cleanup).
- Implemented memory monitoring alert: alert if worker pod memory >75% of limit for >5 min.
- Added explicit `del attachment_object` and `gc.collect()` in worker message handler.
- Unit tests added to verify memory usage stays stable after processing 1000+ messages.
- Reduced pod memory limit alert threshold from 80% to 70% for faster detection.

---

### INC-2024-0156 — RabbitMQ Cluster Majority Loss During Node Failure

**Date:** 2024-07-08
**Severity:** P0 (Critical)
**Duration:** 12 minutes (10:08 UTC to 10:20 UTC)
**Affected Services:** All queue workers, order processing, notifications, webhooks
**Customer Impact:** Complete service outage; all queues unavailable; 8,500 pending orders; estimated $150k revenue impact

**Description:**

The RabbitMQ cluster ran with 3 nodes (`rabbitmq-0`, `rabbitmq-1`, `rabbitmq-2`). A Kubernetes node hosting `rabbitmq-1` failed due to disk corruption. The node was automatically evicted by Kubernetes. However, quorum queues require a quorum (>50%) to be available. With 3 nodes, a quorum is 2/3 (need at least 2 nodes).

When `rabbitmq-1` went down, only `rabbitmq-0` and `rabbitmq-2` remained. A 2-node quorum in a 3-node cluster is still a quorum (2/3 ≈ 67%), so theoretically queues should remain available. However, RabbitMQ's quorum algorithm was conservative: it waited 30 seconds for the failed node to rejoin before declaring it permanently lost. During those 30 seconds, all quorum queues became unavailable to prevent split-brain scenarios.

For 12 minutes (while waiting for automation to scale down and replace the failed node), the broker was unavailable. All workers stalled. Order processing halted completely.

**Root Cause:**

- 3-node RabbitMQ cluster can tolerate only 1 node failure; 2 simultaneous failures cause loss of quorum.
- No automated node replacement in infrastructure-as-code.
- No monitoring or alerting for broker cluster quorum loss.
- Broker quorum timeout (30s) meant a brief node failure caused 12 min of complete unavailability due to slow Kubernetes node recovery automation.

**Resolution Steps:**

1. **Declare emergency and page on-call VP (P0 incident):**
   ```bash
   # Alert fires automatically on broker unavailability
   # Human responder joins war room
   ```

2. **Check RabbitMQ cluster status (should show 2 nodes, 1 down):**
   ```bash
   kubectl get pods -n ecommerce -l app=rabbitmq
   # One pod should be Missing or Pending
   ```

3. **Option A (preferred): Wait for Kubernetes to auto-replace the failed node (faster than manual intervention):**
   - Kubernetes should automatically spawn a replacement pod on a healthy node.
   - Monitor: `kubectl get pods -n ecommerce -l app=rabbitmq -w`
   - Wait ~3 minutes for new pod to start and rejoin cluster.
   - Once 3 nodes are Back Online, quorum is restored immediately.

4. **Option B (if auto-replacement fails): Manually force removal of the failed node from cluster:**
   ```bash
   # Connect to a live node (e.g., rabbitmq-0)
   kubectl exec rabbitmq-0 -n ecommerce -- \
     rabbitmqctl forget_cluster_node rabbit@rabbitmq-1
   ```
   WARNING: Only do this if the node is definitely dead and won't rejoin.

5. **Verify broker is responsive:**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/overview | jq '.node.running'
   # Should return: true
   ```

6. **Verify all queues are available:**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues | jq 'length'
   # Should list all queues with message counts
   ```

7. **Resume workers and monitor recovery:**
   ```bash
   kubectl get pods -n ecommerce -l app=order-worker
   # Workers should automatically reconnect and resume processing
   ```

**Follow-up Actions:**

- Scaled RabbitMQ cluster from 3 to 5 nodes. A 5-node cluster can tolerate 2 simultaneous node failures (requires 3/5 quorum). Significantly improves availability.
- Updated Kubernetes StatefulSet with `podDisruptionBudget` to ensure at least 3 RabbitMQ nodes are always up (prevents accidental evictions).
- Implemented automated node replacement: failed nodes are detected and replaced within 1 minute (faster than manual intervention).
- Added monitoring for cluster quorum status: alert if fewer than 3 nodes healthy.
- Documented disaster recovery runbook: procedures for 2-node cluster recovery and cluster rebuild from scratch.

---

## Failure Mode Catalog

### 1. DLQ Overflow / Messages Lost

**Symptom:** DLQ depth does not decrease; monitoring shows messages older than 24 hours in DLQ.

**Cause:** Replay shovel is not running, or messages are being dropped due to `x-max-length` policy on DLQ exceeding capacity.

**Detection:** Alert fires if DLQ depth >10 messages for >30 min.

**Mitigation:**
- Check DLQ depth: `curl -s -u admin:${RABBITMQ_PASSWORD} http://rabbitmq:15672/api/queues/%2F/order_dlq | jq '.messages'`
- Start a shovel to replay DLQ to main queue (see INC-2024-0377 Resolution steps).
- Verify `x-max-length` policy is not dropping messages: `curl -s -u admin:${RABBITMQ_PASSWORD} http://rabbitmq:15672/api/queues/%2F/order_dlq | jq '.arguments'` should not have `x-max-length`.

---

### 2. Worker OOM on Oversized Payload

**Symptom:** Worker pod crashes with `Killed` exit code 137 (OOM); memory limit exceeded logs in Kubernetes.

**Cause:** A message payload exceeds available worker memory (e.g., large order JSON with full customer history, or image attachment binary in message).

**Detection:** Alert fires if worker pod is OOM-killed; Kubernetes shows `OOMKilled` in pod status.

**Mitigation:**
- Increase worker memory limit: `kubectl set resources deployment/order-worker -n ecommerce --limits=memory=2Gi` (was 1Gi).
- Investigate payload source: check what triggered the large message. If customer-initiated (e.g., bulk upload), implement max size validation on API.
- Monitor message size histogram in RabbitMQ: oversized messages should be rejected at ingestion, not queued.

---

### 3. Duplicate Message Processing

**Symptom:** Order processed twice (payment charged twice, inventory reserved twice); seen in database as duplicate IncidentAction rows.

**Cause:** RabbitMQ broker restarts trigger message re-delivery. If worker is processing message but crashes before ACK, message is returned to queue and picked up again.

**Detection:** Database constraint checks or business logic audit. Alert if duplicate orders detected (amount charged twice to same merchant).

**Mitigation:**
- Ensure worker implements idempotent processing: upsert order state by `(idempotency_key, merchant_id)`, not insert.
- Use RabbitMQ Publisher Confirms and Consumer Acks: `ack_mode: on_confirm` in shovel definitions.
- Implement message deduplication at ingestion: track `message_id` in database; skip if already processed.

---

### 4. Broker Connection Pool Exhaustion

**Symptom:** All worker pods report `AMQPConnectionError: Connection refused` or `ChannelError: CONNECTION_FORCED`. New connections to RabbitMQ fail. Queue depth stops decreasing.

**Cause:** Worker connection leak (connections not properly closed) or broker connection limit reached. Typically happens after thousands of worker task executions without connection pooling.

**Detection:** Alert fires if worker error rate >5% for >1 min. RabbitMQ logs show `connection exceeded max_connections`.

**Mitigation:**
- Restart all workers to reset connections: `kubectl rollout restart deployment/order-worker -n ecommerce`.
- Check RabbitMQ connection limit: `curl -s -u admin:${RABBITMQ_PASSWORD} http://rabbitmq:15672/api/nodes | jq '.[] | {name, limit_of_connections}'`.
- Increase connection limit if needed: Update RabbitMQ ConfigMap `channel_max=2048`, `connection_max=100000`; restart broker.
- Verify worker connection pooling is configured correctly (should reuse connections, not create new ones per task).

---

## Runbook Procedures

### Procedure: Pause a Specific Worker Type

**Use when:** Worker has a bug, critical dependency is down, or manual intervention is needed. Messages stay safely in queue while workers are paused.

**Steps:**

1. **Scale deployment to 0 replicas:**
   ```bash
   kubectl scale deployment/ORDER_WORKER_NAME --replicas=0 -n ecommerce
   ```
   Replace `ORDER_WORKER_NAME` with `order-worker`, `notification-worker`, `webhook-worker`, or `fulfillment-worker`.

2. **Verify pod is gone:**
   ```bash
   kubectl get pods -n ecommerce -l app=ORDER_WORKER_NAME
   ```

3. **Messages remain in queue (safe hold):**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/QUEUE_NAME | jq '.messages, .consumers'
   ```
   `.consumers` should be 0 (no workers consuming).

4. **Fix the issue** (deploy fix, wait for dependency to recover, etc.).

5. **Resume workers:**
   ```bash
   kubectl scale deployment/ORDER_WORKER_NAME --replicas=DESIRED_COUNT -n ecommerce
   ```

---

### Procedure: Drain and Replay DLQ

**Use when:** Messages failed processing and are in DLQ. Replay them to main queue after root cause is fixed.

**Steps:**

1. **Verify DLQ has messages:**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/QUEUE_DLQ | jq '.messages'
   ```

2. **Create RabbitMQ Shovel to replay DLQ → main queue:**
   ```bash
   curl -X PUT -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/shovels/%2F/QUEUE_replay \
     -H "Content-Type: application/json" \
     -d '{
       "source-protocol": "amqp091",
       "source": {
         "brokers": ["amqp://rabbitmq-0,rabbitmq-1,rabbitmq-2"],
         "queue": "QUEUE_DLQ"
       },
       "destination-protocol": "amqp091",
       "destination": {
         "brokers": ["amqp://rabbitmq-0,rabbitmq-1,rabbitmq-2"],
         "queue": "QUEUE_NAME"
       },
       "ack-mode": "on-confirm",
       "reconnect-delay": 5
     }'
   ```

3. **Monitor replay progress (every 30 sec):**
   ```bash
   watch -n 30 "curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/QUEUE_DLQ | jq '.messages'"
   ```

4. **Once DLQ is empty, delete shovel:**
   ```bash
   curl -X DELETE -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/shovels/%2F/QUEUE_replay
   ```

---

### Procedure: Emergency Scale Workers

**Use when:** Queue depth is growing and P99 latency is degrading. Rapidly increase capacity to drain backlog.

**Steps:**

1. **Increase HPA maxReplicas (temporary):**
   ```bash
   kubectl patch hpa ORDER_WORKER_HPA -n ecommerce \
     -p '{"spec":{"maxReplicas":DESIRED_MAX}}'
   ```
   Example: `DESIRED_MAX=50` for `order-worker`.

2. **Manually scale to intermediate level (to force scale-up faster than HPA ramp):**
   ```bash
   kubectl scale deployment/ORDER_WORKER_NAME --replicas=DESIRED_REPLICAS -n ecommerce
   ```
   Example: scale to 20 replicas if current is 8.

3. **Monitor queue drain rate (should drop steeply):**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/queues/%2F/QUEUE_NAME | jq '.messages'
   ```

4. **Monitor RabbitMQ broker memory (should stay <75%):**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/overview | jq '.node.memory_used / .node.memory_limit * 100'
   ```

5. **Once queue depth is <1,000, gradually scale down:**
   ```bash
   # Wait 5 min, then:
   kubectl scale deployment/ORDER_WORKER_NAME --replicas=12 -n ecommerce
   ```

6. **Revert HPA maxReplicas to normal after incident:**
   ```bash
   kubectl patch hpa ORDER_WORKER_HPA -n ecommerce \
     -p '{"spec":{"maxReplicas":NORMAL_MAX}}'
   ```

---

### Procedure: Disable Non-Critical Queues During Broker Pressure

**Use when:** Broker memory >75% and order processing (critical path) is degraded. Pause notification and webhook workers to free resources.

**Steps:**

1. **Check broker memory:**
   ```bash
   curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/overview | jq '.node | {memory_used, memory_limit}'
   ```

2. **If memory >75%, pause notification-worker (non-critical for immediate fulfillment):**
   ```bash
   kubectl scale deployment/notification-worker --replicas=0 -n ecommerce
   ```

3. **If still >75%, pause webhook-worker:**
   ```bash
   kubectl scale deployment/webhook-worker --replicas=0 -n ecommerce
   ```

4. **Monitor memory recovery:**
   ```bash
   watch -n 10 "curl -s -u admin:${RABBITMQ_PASSWORD} \
     http://rabbitmq:15672/api/overview | jq '.node.memory_used / .node.memory_limit * 100 | .'%''"
   ```

5. **Once memory <60%, resume workers in reverse order:**
   ```bash
   kubectl scale deployment/webhook-worker --replicas=4 -n ecommerce
   kubectl scale deployment/notification-worker --replicas=6 -n ecommerce
   ```

---

## Monitoring & Alerts

### Key Metrics Dashboard

**URL:** Grafana → Incident Triage → Queue & Workers

| Metric | Query | Alert Condition | Severity |
|--------|-------|-----------------|----------|
| Order Queue Depth | `rabbitmq_queue_messages_ready{queue="order_processing"}` | >1,000 | P1 |
| Order Queue DLQ Depth | `rabbitmq_queue_messages_ready{queue="order_dlq"}` | >10 | P2 |
| Notification Queue Depth | `rabbitmq_queue_messages_ready{queue="notification_queue"}` | >5,000 | P2 |
| Webhook Queue Depth | `rabbitmq_queue_messages_ready{queue="webhook_delivery"}` | >10,000 | P2 |
| Order P99 Latency | `histogram_quantile(0.99, rate(order_processing_duration_ms[5m]))` | >45s | P1 |
| Notification Delivery Latency | `histogram_quantile(0.99, rate(notification_delivery_duration_ms[5m]))` | >3min | P2 |
| RabbitMQ Memory % | `rabbitmq_node_memory_used_bytes / rabbitmq_node_memory_limit_bytes * 100` | >75% | P1 |
| Worker Pod Restarts (1h) | `increase(kube_pod_container_status_restarts_total{namespace="ecommerce"}[1h])` | >1 | P1 |
| Worker Pod Errors (5min) | `rate(celery_task_error_total[5m])` | >5% | P1 |
| RabbitMQ Connection Count | `rabbitmq_connections` | >5000 | P2 |

### Alert Rules (Prometheus)

```yaml
- alert: OrderQueueBacklog
  expr: rabbitmq_queue_messages_ready{queue="order_processing"} > 1000
  for: 5m
  annotations:
    severity: P1
    summary: "Order queue backlog detected ({{ $value }} messages)"
    runbook_url: "/runbooks/queue-workers#inc-2024-0118"

- alert: WorkerCrashLoop
  expr: increase(kube_pod_container_status_restarts_total{namespace="ecommerce", label_app=~"order-worker|notification-worker"}[1h]) > 1
  for: 2m
  annotations:
    severity: P1
    summary: "Worker pod crash loop detected"
    runbook_url: "/runbooks/queue-workers#inc-2024-0377"

- alert: WebhookRetryStorm
  expr: rabbitmq_queue_messages_ready{queue=~"webhook_delivery.*"} > 10000
  for: 10m
  annotations:
    severity: P1
    summary: "Webhook delivery queue backlog (possible retry storm)"
    runbook_url: "/runbooks/queue-workers#inc-2025-0058"

- alert: RabbitMQMemoryPressure
  expr: (rabbitmq_node_memory_used_bytes / rabbitmq_node_memory_limit_bytes) > 0.75
  for: 5m
  annotations:
    severity: P1
    summary: "RabbitMQ broker memory >75%"
    runbook_url: "/runbooks/queue-workers#broker-connection-pool-exhaustion"
```

---

## Escalation Policy

### Severity Definitions

| Level | Response Time | Who | Escalation |
|-------|--------------|-----|------------|
| P0 | <5 min | Platform Engineering on-call | VP Engineering (15 min) |
| P1 | <15 min | Platform Engineering on-call | Payments team if order processing blocked (30 min) |
| P2 | <1 hour | Platform Engineering on-call | — |
| P3 | <24 hours | Platform Engineering team (ticket) | — |

### Incident Communication Template

**When:** Alert fires or incident is detected.

**1. Initial Notification (to Slack #oncall):**
```
🚨 [P1] Queue & Workers Incident
Service: <service name>
Alert: <metric / symptom>
Status: INVESTIGATING
Runbook: <link>
```

**2. Initial Mitigation (5–10 min in):**
```
📋 Mitigation started:
- Action 1: <kubectl command>
- Action 2: <curl command>
ETA for resolution: <time>
```

**3. Resolved (post-action):**
```
✅ Incident resolved
Root cause: <brief explanation>
Resolution time: <duration>
Follow-up: <ticket link>
```

### Escalation to Payments Team

**Trigger:** Order processing P99 latency >60s, OR order queue depth >50,000 for >30 min.

**Contact:** Payments team lead (PagerDuty: payments-engineering-oncall)

**Message:** "Order processing is blocked due to [queue saturation | worker crash | broker issue]. Payment capture may be delayed. ETA for recovery: [time]. Will update every 10 min."

### War Room / Bridge Call

**Join if:** P0 incident, OR incident unresolved after 30 min, OR escalation to another team.

**Bridge:** Zoom (incident details → on-call runbook → Zoom link auto-generated)

**Participants:** On-call engineer, on-call manager, affected team lead.

---

## Quick Reference

### Critical Commands (copy-paste ready)

**Check order queue:**
```bash
curl -s -u admin:${RABBITMQ_PASSWORD} http://rabbitmq:15672/api/queues/%2F/order_processing | jq '.messages'
```

**Scale order-worker:**
```bash
kubectl scale deployment/order-worker --replicas=24 -n ecommerce
```

**Check broker memory:**
```bash
curl -s -u admin:${RABBITMQ_PASSWORD} http://rabbitmq:15672/api/overview | jq '.node | {memory_used, memory_limit}'
```

**View worker logs:**
```bash
kubectl logs deployment/order-worker -n ecommerce --tail=50 -f
```

**Pause a worker type:**
```bash
kubectl scale deployment/notification-worker --replicas=0 -n ecommerce
```

**Check DLQ:**
```bash
curl -s -u admin:${RABBITMQ_PASSWORD} http://rabbitmq:15672/api/queues/%2F/order_dlq | jq '.messages'
```

### Contact Info

- **Platform Engineering on-call:** PagerDuty `platform-engineering-oncall`
- **Payments team:** PagerDuty `payments-engineering-oncall`
- **RabbitMQ admin:** vault → `rabbitmq_admin_user`, `rabbitmq_admin_password`
- **Slack channel:** #incident-triage
- **Status page:** status.company.com

---

## Inter-Service Impact Map

When Queue & Workers degrades, the cascade looks like:

| Stage | Service | Impact | Time to Detect |
|---|---|---|---|
| Immediate | broker (RabbitMQ) | all workers stalled, queues back up | <1 min |
| +2 min | order-service | can't enqueue orders for processing, orders sit pending | +2 min |
| +5 min | checkout-service | order creation RPC times out, checkout fails | +5 min |
| +10 min | notification-service | customer emails don't send, angry support tickets | +10 min |

**How to read this:** If broker is down, every downstream service fails in rapid succession.

**Isolation actions:** Circuit breaker on checkout-service: if order-service queue times out, fail fast instead of hanging. Scale workers aggressively to drain backlog.

---

## Rollback Decision Tree

**When to rollback vs. hotfix:**

1. Order queue depth >50k for >5 minutes?
   - YES → Scale workers first (faster relief). Rollback only if worker crash loop.
   - NO → Proceed to step 2

2. DLQ receiving order messages (failures, not just backlog)?
   - YES → If from recent worker deploy, rollback. If message format issue, hotfix.
   - NO → Proceed to step 3

3. Broker health OK (RabbitMQ cluster GREEN)?
   - YES → Wait; queue will drain as workers process. Monitor drain rate.
   - NO → Page on-call immediately. Broker down = P0.

**Quick rollback command:**
```bash
kubectl rollout undo deployment/order-worker -n ecommerce
kubectl rollout status deployment/order-worker -n ecommerce --timeout=3m
```

**Verification after rollback:**
- Order queue drain rate positive (depth decreasing)
- DLQ empty (no order failures)
- Worker CPU and memory normal
- No new orders stuck pending
