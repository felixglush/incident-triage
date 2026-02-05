# Memory Leak Incident

## Symptoms
- Memory usage steadily climbs after deploy
- Frequent OOM restarts
- Latency increases as GC churn grows

## Immediate Actions
1. Scale out to reduce per-instance load.
2. Capture heap/pprof snapshots if available.
3. Roll back the suspected deploy if trend worsens.

## Investigation
- Compare memory profiles pre/post deploy.
- Check long-lived caches and unbounded queues.
- Inspect background jobs for retention of large objects.

## Resolution
- Fix leak source and validate via canary.
- Add memory guardrails and alerts.

## Verification
- Memory stabilizes below threshold.
- Restart rate returns to baseline.
