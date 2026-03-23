# Checkout & Payments Pre-Action Checklist

Use this checklist before any risky operation: deployments, config changes, major traffic events, maintenance windows. Payment systems are mission-critical; fraud detection and PCI compliance are non-negotiable.

## Pre-Deploy Checklist

- [ ] All tests passing locally and in CI
- [ ] Code review approved by 2+ team members
- [ ] CHANGELOG.md updated
- [ ] Environment variables defined in `.env.example` and production
- [ ] Database migrations (if any) tested and have rollback plan
- [ ] Feature flags configured for gradual rollout
- [ ] Payment gateway credentials rotated and verified in staging
- [ ] Fraud detection model up-to-date; no regressions in test suite
- [ ] PCI compliance audit passed (if applicable)
- [ ] Alert thresholds reviewed; no suppression
- [ ] Runbook updated if behavior changed
- [ ] On-call engineer notified
- [ ] Deployment scheduled with team
- [ ] Reconciliation hooks tested (idempotent)
- [ ] Webhook signature validation verified

**Deploy command:**
```bash
kubectl set image deployment/checkout-payments <container>=<image:tag> -n ecommerce
kubectl rollout status deployment/checkout-payments -n ecommerce --timeout=5m
```

**Verify after deploy:**
- [ ] Error rate <0.1%
- [ ] P99 latency within 10% of baseline
- [ ] Payment success rate ≥99.5%
- [ ] Fraud rejection rate within normal bounds
- [ ] No increase in failed payment reversals
- [ ] Memory usage normal
- [ ] No DLQ increase
- [ ] Payment gateway latency <500ms p99

## Pre-Sale Checklist (Black Friday, Prime Day, etc.)

- [ ] Load test completed (expected peak + 1.5x safety margin)
  - Simulate checkout flow with realistic payment volumes
  - Test with multiple payment gateways simultaneously
- [ ] Autoscaling policies reviewed and tested
- [ ] Resource limits adequate (CPU, memory, network)
- [ ] Payment gateway rate limits reviewed with provider
- [ ] Cache pre-warmed (promotion details, product prices)
- [ ] Payment processor quotas increased (Stripe, PayPal, etc.)
- [ ] Fraud detection thresholds tuned (reduce false positives during surge)
- [ ] Circuit breakers configured for payment gateway fallbacks
- [ ] Rate limiters configured per customer/IP
- [ ] On-call coverage confirmed (2+ payment engineers on rotation)
- [ ] Third-party payment providers notified of expected surge
- [ ] War room Slack channel created; escalation contacts shared
- [ ] Synthetic monitoring enabled (test credit cards provisioned)
- [ ] Reconciliation job scheduled to run hourly (not just daily)
- [ ] Webhook retry logic tested under heavy load

**Scale-up commands ready:**
```bash
# Scale checkout service
kubectl scale deployment/checkout-payments --replicas=N -n ecommerce

# Verify payment gateway connection pool
kubectl exec -it deployment/checkout-payments -- curl http://localhost:8000/health/payment-gateway
```

**Pre-sale verification (24h before):**
- [ ] Load test passed without errors
- [ ] Payment gateway confirms capacity
- [ ] Fraud thresholds tuned
- [ ] On-call rotation confirmed
- [ ] War room comms tested

## Pre-Maintenance Checklist

- [ ] Maintenance window scheduled (1 week notice to payment processors)
- [ ] Stakeholders notified (including payment gateway team)
- [ ] Data backup completed and tested (customer payment data encrypted)
- [ ] Rollback plan documented (payment state machine reversible)
- [ ] Staging mirrors production payment config
- [ ] Tested on staging 2+ times with real payment processor sandbox
- [ ] On-call team briefed on payment-specific concerns
- [ ] Synthetic monitoring disabled (only after maintenance)
- [ ] Status page ready; comms plan in place
- [ ] Payment reconciliation job paused during maintenance
- [ ] Customer notification sent (if checkout will be down)

**Post-maintenance verification:**
- [ ] Service responds to requests
- [ ] Payment gateway connectivity confirmed
- [ ] Test payment flows succeed (both credit card and alternative methods)
- [ ] Webhook signatures valid
- [ ] Fraud detection model loaded correctly
- [ ] Reconciliation job resumes and catches up
- [ ] No orphaned transactions

## Ongoing Monitoring (Daily/Weekly)

- [ ] Payment success rate ≥99.5%; flag any decline
- [ ] Fraud detection model accuracy (precision/recall)
- [ ] Payment gateway latency <500ms p99; flag spikes
- [ ] Reconciliation drift <0.1%; investigate failures
- [ ] Chargebacks and disputes trending down
- [ ] Failed webhook deliveries <1%; retry queue healthy
- [ ] SLO compliance tracked (checkout latency, uptime)
- [ ] Slow query log reviewed
- [ ] Capacity trending; forecast peak load
- [ ] Recent production issues documented in runbook
- [ ] PCI compliance checklist reviewed monthly
