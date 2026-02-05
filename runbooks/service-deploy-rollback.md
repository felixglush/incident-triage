# Service Deploy Rollback

## Symptoms
- Error rate spikes immediately after deploy
- New alerts across the same service version
- Rollout guardrails triggered

## Immediate Actions
1. Stop the rollout and freeze new deployments.
2. Compare metrics between new and previous versions.
3. Notify on-call and declare incident if needed.

## Rollback Steps
1. Roll back to the last known good version.
2. Confirm config flags and migrations are compatible.
3. Re-run health checks and synthetic tests.

## Verification
- Error rate returns to baseline.
- Latency improves to expected range.
- Alerts resolve or downgrade.
