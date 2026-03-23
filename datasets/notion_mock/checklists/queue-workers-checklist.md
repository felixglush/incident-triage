# Queue & Workers Pre-Action Checklist

Use this checklist before any risky operation: deployments, config changes, major traffic events, maintenance windows. Queue and worker systems drive async processing; delays or failures cascade to order fulfillment, notifications, and reconciliation.

## Pre-Deploy Checklist

- [ ] All tests passing locally and in CI
- [ ] Code review approved by 2+ team members
- [ ] CHANGELOG.md updated
- [ ] Environment variables defined in `.env.example` and production
- [ ] Database migrations (if any) tested and have rollback plan
- [ ] Feature flags configured for gradual rollout
- [ ] Message format changes backward-compatible (versioning/schemas)
- [ ] Dead Letter Queue (DLQ) handling tested
- [ ] Retry logic and exponential backoff configured correctly
- [ ] Worker graceful shutdown tested (drain inflight messages)
- [ ] Queue consumer offset/checkpoint logic verified
- [ ] Alert thresholds reviewed; no suppression
- [ ] Runbook updated if behavior changed
- [ ] On-call engineer notified
- [ ] Deployment scheduled with team
- [ ] Queue depth monitored during deploy (no spike)

**Deploy command:**
```bash
# Rolling update to drain existing messages
kubectl set image deployment/workers <container>=<image:tag> -n ecommerce
kubectl rollout status deployment/workers -n ecommerce --timeout=10m

# Verify queue depth and consumer lag
kubectl exec -it deployment/workers -- python -m tools.queue_status
```

**Verify after deploy:**
- [ ] Error rate <0.1%
- [ ] P99 latency within 10% of baseline
- [ ] Queue depth stable (not accumulating)
- [ ] Consumer lag <30s (healthy processing)
- [ ] DLQ size stable (no spike)
- [ ] Memory usage normal
- [ ] No DLQ increase
- [ ] Worker CPU usage <70%

## Pre-Sale Checklist (Black Friday, Flash Sale, etc.)

- [ ] Load test completed (expected peak + 1.5x safety margin)
  - Simulate realistic queue volume (orders, notifications, webhooks)
  - Test with expected message size and frequency
- [ ] Autoscaling policies reviewed and tested
  - Worker autoscaling rules set (target CPU, queue depth)
- [ ] Resource limits adequate (CPU, memory, network)
- [ ] Queue broker capacity verified (Kafka partition count, Redis memory)
- [ ] DLQ monitoring and alerting enabled
- [ ] Retry policies tuned (don't retry toxic messages forever)
- [ ] Consumer group rebalancing tested under scale-up
- [ ] Circuit breakers configured for dependent services
- [ ] Rate limiters configured (prevent downstream overload)
- [ ] On-call coverage confirmed (2+ queue engineers)
- [ ] Message broker nodes healthy and replicated
- [ ] War room Slack channel created
- [ ] Synthetic monitoring enabled (test message injected)
- [ ] Graceful degradation plan ready (if queue lags, queue messages, don't drop)
- [ ] Webhook retry logic tested (exponential backoff)

**Scale-up commands ready:**
```bash
# Scale workers
kubectl scale deployment/workers --replicas=N -n ecommerce

# Scale queue broker (if using Kafka)
kubectl scale statefulset/kafka --replicas=3 -n ecommerce

# Monitor queue depth and consumer lag
watch 'kubectl exec -it deployment/workers -- python -m tools.queue_status'
```

**Pre-sale verification (24h before):**
- [ ] Load test passed without errors
- [ ] Consumer lag <30s at peak load
- [ ] Worker CPU stable <70%
- [ ] DLQ empty or stable size
- [ ] On-call rotation confirmed
- [ ] War room comms tested
- [ ] Graceful degradation tested

## Pre-Maintenance Checklist

- [ ] Maintenance window scheduled (1 week notice)
- [ ] Stakeholders notified (ops, product, support)
- [ ] Message backup completed (full queue snapshot if needed)
- [ ] Rollback plan documented (consumer group offset reset procedure)
- [ ] Staging mirrors production (queue broker config, message schema)
- [ ] Tested on staging 2+ times (scale-up, message processing, DLQ handling)
- [ ] On-call team briefed
- [ ] Synthetic monitoring disabled
- [ ] Status page ready; comms plan in place
- [ ] Consumer group paused before maintenance (don't lose messages)
- [ ] Queue depth drained to acceptable level before shutdown

**Post-maintenance verification:**
- [ ] Queue broker responding
- [ ] Consumer groups rebalanced
- [ ] Consumer lag <30s
- [ ] DLQ empty or stable
- [ ] Message processing latency normal
- [ ] No message loss
- [ ] Alerts firing
- [ ] Worker CPU usage normal

## Ongoing Monitoring (Daily/Weekly)

- [ ] Queue depth stable; flag sustained growth (consumer lag)
- [ ] Consumer lag <30s; investigate spikes
- [ ] DLQ size stable; investigate growth (bad messages or bugs)
- [ ] Message processing latency <1s p99; flag outliers
- [ ] Worker memory usage <80%; forecast growth
- [ ] Worker CPU usage <70%; flag sustained high load
- [ ] Message broker replication healthy (all replicas in sync)
- [ ] Consumer group rebalancing frequency normal (flag excessive rebalances)
- [ ] Webhook retry queue depth; flag stuck retries
- [ ] SLO compliance tracked (message latency, throughput)
- [ ] Slow query log reviewed (any DB I/O from workers)
- [ ] Capacity trending; forecast peak load
- [ ] Recent production issues documented in runbook
- [ ] Message schema versioning; flag backward-incompatible changes
- [ ] Dead letter queue remediation SLA tracked (e.g., resolve within 24h)
