# Cache Miss Storm

## Symptoms
- Cache hit rate drops below 60%
- Increased latency across read-heavy endpoints
- Database CPU climbs rapidly

## Immediate Actions
1. Confirm cache cluster health and memory pressure.
2. Identify top keys or endpoints causing misses.
3. Enable request coalescing or tighten cache TTL temporarily.

## Investigation
- Check cache eviction metrics and max memory settings.
- Review recent deploys that changed cache key patterns.
- Inspect upstream dependency latency (slow cache fill).

## Resolution Steps
1. Restore cache key normalization if regression found.
2. Increase cache capacity or shard count.
3. Roll back offending deploy if miss rate persists.

## Verification
- Cache hit rate returns above 90%.
- P95 latency returns to baseline.
- Database CPU stabilizes.
