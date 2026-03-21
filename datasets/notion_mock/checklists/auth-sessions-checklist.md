# Authentication & Sessions Pre-Action Checklist

Use this checklist before any risky operation: deployments, config changes, major traffic events, maintenance windows. Auth is a critical security boundary; session corruption or auth failures block all users.

## Pre-Deploy Checklist

- [ ] All tests passing locally and in CI
- [ ] Code review approved by 2+ team members
- [ ] CHANGELOG.md updated
- [ ] Environment variables defined in `.env.example` and production
- [ ] Database migrations (if any) tested and have rollback plan
- [ ] Feature flags configured for gradual rollout
- [ ] Cryptographic keys rotated and verified in staging
- [ ] Session token generation/validation tested
- [ ] JWT signing/verification logic unchanged (or backward-compatible)
- [ ] OAuth provider integrations verified (Google, GitHub, etc.)
- [ ] MFA/2FA logic unchanged (or upgrades tested thoroughly)
- [ ] Password reset flow tested
- [ ] Alert thresholds reviewed; no suppression
- [ ] Runbook updated if behavior changed
- [ ] On-call engineer notified
- [ ] Deployment scheduled with team
- [ ] Session invalidation logic tested (logout, timeout)

**Deploy command:**
```bash
kubectl set image deployment/auth-sessions <container>=<image:tag> -n ecommerce
kubectl rollout status deployment/auth-sessions -n ecommerce --timeout=5m
```

**Verify after deploy:**
- [ ] Error rate <0.1%
- [ ] P99 latency within 10% of baseline
- [ ] Login success rate ≥99%
- [ ] Session creation latency <100ms p99
- [ ] Token validation latency <50ms p99
- [ ] Memory usage normal
- [ ] No DLQ increase
- [ ] No spike in auth failures

## Pre-Sale Checklist (High Traffic Event)

- [ ] Load test completed (expected peak + 1.5x safety margin)
  - Simulate login and session validation under peak load
  - Test with realistic MFA failure rates
- [ ] Autoscaling policies reviewed and tested
- [ ] Resource limits adequate (CPU, memory, network)
- [ ] Session store (Redis) capacity and replication verified
- [ ] Cache pre-warmed (OAuth provider certs, session metadata)
- [ ] OAuth provider rate limits reviewed and increased if needed
- [ ] Token refresh logic stress-tested
- [ ] Rate limiters configured per customer/IP (prevent brute force)
- [ ] Login attempt throttling tested (5 failures -> 15min lockout)
- [ ] On-call coverage confirmed (2+ auth engineers)
- [ ] Third-party auth providers notified
- [ ] War room Slack channel created
- [ ] Synthetic monitoring enabled (test accounts provisioned)
- [ ] Circuit breakers configured for OAuth fallback
- [ ] Session timeout policies reviewed (don't timeout during sale)

**Scale-up commands ready:**
```bash
# Scale auth service
kubectl scale deployment/auth-sessions --replicas=N -n ecommerce

# Scale Redis session store
kubectl scale statefulset/redis-sessions --replicas=3 -n ecommerce

# Verify OAuth provider connectivity
kubectl exec -it deployment/auth-sessions -- curl https://oauth.provider.com/health
```

**Pre-sale verification (24h before):**
- [ ] Load test passed without errors
- [ ] Login latency <100ms p99
- [ ] Session store replication healthy
- [ ] OAuth provider confirms capacity
- [ ] On-call rotation confirmed
- [ ] War room comms tested
- [ ] Rate limiter thresholds tuned

## Pre-Maintenance Checklist

- [ ] Maintenance window scheduled (1 week notice to support team)
- [ ] Stakeholders notified (customer success, support, marketing)
- [ ] Data backup completed (session store, user credentials encrypted)
- [ ] Rollback plan documented (keys and token format revert)
- [ ] Staging mirrors production (OAuth providers configured)
- [ ] Tested on staging 2+ times (full auth flow, MFA, password reset)
- [ ] On-call team briefed
- [ ] Synthetic monitoring disabled
- [ ] Status page ready; comms plan in place
- [ ] Session migration script tested (if needed)
- [ ] User notification ready (if session timeout will change)

**Post-maintenance verification:**
- [ ] Service responds to requests
- [ ] Login flows succeed (password, OAuth, MFA)
- [ ] Session creation/validation working
- [ ] Token signatures valid
- [ ] Session store connectivity confirmed
- [ ] MFA providers reachable
- [ ] No spike in auth errors
- [ ] Alerts firing

## Ongoing Monitoring (Daily/Weekly)

- [ ] Login success rate ≥99%; flag any decline
- [ ] Session creation latency <100ms p99; flag spikes
- [ ] Token validation latency <50ms p99
- [ ] Failed auth attempts trending (flag suspicious patterns)
- [ ] MFA success rate ≥95%
- [ ] Session store replication lag <100ms; investigate delays
- [ ] OAuth provider latency <500ms p99; flag unavailability
- [ ] Password reset flow success rate ≥98%
- [ ] Token expiration/refresh logic working
- [ ] SLO compliance tracked (login availability, latency)
- [ ] Slow query log reviewed (user lookup queries)
- [ ] Capacity trending; forecast peak load
- [ ] Recent production issues documented in runbook
- [ ] Cryptographic key rotation schedule reviewed (annual or less)
- [ ] Session invalidation lag <5s (logout propagation)
