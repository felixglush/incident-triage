# HTTP 5xx Spike

## Symptoms
- 5xx error rate spikes above SLO
- Customer requests fail intermittently
- Error budget burn accelerates

## Immediate Actions
1. Identify the affected endpoint/service.
2. Roll back recent deploys if correlated.
3. Enable circuit breakers or rate limits.

## Investigation
- Check error logs and exception traces.
- Look for upstream dependency failures.
- Correlate with traffic or config changes.

## Resolution
- Fix root cause and deploy patch.
- Add canary + alerts for early detection.

## Verification
- 5xx rate returns to baseline.
- Latency stabilizes.
