# CDN & Storefront Pre-Action Checklist

Use this checklist before any risky operation: deployments, config changes, major traffic events, maintenance windows. The storefront is the customer-facing entry point; performance and availability directly impact revenue and brand perception.

## Pre-Deploy Checklist

- [ ] All tests passing locally and in CI
- [ ] Code review approved by 2+ team members
- [ ] CHANGELOG.md updated
- [ ] Environment variables defined in `.env.example` and production
- [ ] Database migrations (if any) tested and have rollback plan
- [ ] Feature flags configured for gradual rollout
- [ ] Frontend bundle size checked (no regressions)
- [ ] CSS and JS assets minified and gzipped
- [ ] CDN cache headers configured correctly (TTLs by content type)
- [ ] Alert thresholds reviewed; no suppression
- [ ] Runbook updated if behavior changed
- [ ] On-call engineer notified
- [ ] Deployment scheduled with team
- [ ] Static assets validated (no broken image/script references)
- [ ] PWA service worker cache strategy tested

**Deploy command:**
```bash
kubectl set image deployment/storefront <container>=<image:tag> -n ecommerce
kubectl rollout status deployment/storefront -n ecommerce --timeout=5m

# Purge CDN cache (selective or full)
curl -X POST https://cdn.example.com/api/purge-cache \
  -H "Authorization: Bearer $CDN_API_KEY" \
  -d '{"paths": ["/index.html", "/*.js", "/*.css"]}'
```

**Verify after deploy:**
- [ ] Error rate <0.1%
- [ ] P99 latency within 10% of baseline
- [ ] First Contentful Paint <2s on 4G
- [ ] Largest Contentful Paint <3s on 4G
- [ ] Core Web Vitals scores unchanged
- [ ] No broken links or 404s
- [ ] Memory usage normal
- [ ] No DLQ increase

## Pre-Sale Checklist (Black Friday, Flash Sale, etc.)

- [ ] Load test completed (expected peak + 1.5x safety margin)
  - Simulate realistic user behavior (browse, add to cart, checkout)
  - Test on 4G network conditions
- [ ] Autoscaling policies reviewed and tested
- [ ] Resource limits adequate (CPU, memory, network)
- [ ] CDN edge nodes warmed with static assets
- [ ] JavaScript bundle optimization reviewed (code splitting, lazy loading)
- [ ] Image optimization verified (responsive images, WebP support)
- [ ] API response caching optimized
- [ ] Rate limiters configured per customer/IP
- [ ] DDoS protection enabled (WAF rules updated)
- [ ] On-call coverage confirmed
- [ ] Third-party CDN/analytics providers notified
- [ ] War room Slack channel created
- [ ] Synthetic monitoring enabled (real device testing)
- [ ] Circuit breakers configured for backend APIs
- [ ] Fallback UI ready (service worker offline mode)
- [ ] Analytics events sampled appropriately (don't overwhelm data pipeline)

**Scale-up commands ready:**
```bash
# Scale storefront service
kubectl scale deployment/storefront --replicas=N -n ecommerce

# Preload CDN cache
kubectl exec -it deployment/storefront -- curl https://cdn.example.com/api/preload \
  -d '{"paths": ["/", "/products", "/checkout"]}'
```

**Pre-sale verification (24h before):**
- [ ] Load test passed without errors
- [ ] Core Web Vitals scores acceptable
- [ ] CDN latency <100ms p99 globally
- [ ] On-call rotation confirmed
- [ ] War room comms tested
- [ ] Fallback UI tested
- [ ] DDoS rules validated

## Pre-Maintenance Checklist

- [ ] Maintenance window scheduled (1 week notice)
- [ ] Stakeholders notified (marketing, customer success, support)
- [ ] Data backup completed (analytics snapshots, user sessions)
- [ ] Rollback plan documented (previous version pinned in CDN)
- [ ] Staging mirrors production
- [ ] Tested on staging 2+ times (cross-browser, mobile, offline)
- [ ] On-call team briefed
- [ ] Synthetic monitoring disabled (only during maintenance)
- [ ] Status page ready; customer-facing message prepared
- [ ] Communication plan (email, SMS, in-app banner)
- [ ] CDN cache invalidation tested (full or selective)

**Post-maintenance verification:**
- [ ] Service responds to requests
- [ ] Pages load within SLO (First Contentful Paint <2s)
- [ ] All assets accessible (no 404s)
- [ ] Analytics events firing
- [ ] Service worker updated (no stale cache)
- [ ] Alerts firing
- [ ] No increase in error rates or latency

## Ongoing Monitoring (Daily/Weekly)

- [ ] Core Web Vitals (LCP, FID, CLS) within targets
- [ ] CDN cache hit ratio >95%; investigate drops
- [ ] Global latency distribution; flag region outliers
- [ ] JavaScript error rates <0.1%
- [ ] API latency <200ms p99; flag spikes
- [ ] SLO compliance tracked (availability, latency)
- [ ] Bundle size trend; flag regressions
- [ ] Image optimization effectiveness (avg size per image)
- [ ] Service worker update frequency; flag excessive revalidation
- [ ] DDoS attack patterns; adjust WAF rules as needed
- [ ] Capacity trending; forecast peak load
- [ ] Recent production issues documented in runbook
- [ ] Mobile performance metrics tracked separately (4G baseline)
