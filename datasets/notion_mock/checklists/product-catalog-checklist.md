# Product Catalog Pre-Action Checklist

Use this checklist before any risky operation: deployments, config changes, major traffic events, maintenance windows. The catalog is the source of truth for product data; inaccuracies cascade to search, pricing, and inventory systems.

## Pre-Deploy Checklist

- [ ] All tests passing locally and in CI
- [ ] Code review approved by 2+ team members
- [ ] CHANGELOG.md updated
- [ ] Environment variables defined in `.env.example` and production
- [ ] Database migrations (if any) tested and have rollback plan
- [ ] Feature flags configured for gradual rollout
- [ ] Catalog data validation logic tested (SKU uniqueness, pricing rules, etc.)
- [ ] Search index reindex script tested (no data loss)
- [ ] Product image CDN cache invalidation script ready
- [ ] Alert thresholds reviewed; no suppression
- [ ] Runbook updated if behavior changed
- [ ] On-call engineer notified
- [ ] Deployment scheduled with team
- [ ] Dependent services (search, recommendation engine) validated in staging

**Deploy command:**
```bash
kubectl set image deployment/product-catalog <container>=<image:tag> -n ecommerce
kubectl rollout status deployment/product-catalog -n ecommerce --timeout=5m
```

**Verify after deploy:**
- [ ] Error rate <0.1%
- [ ] P99 latency within 10% of baseline
- [ ] Product count unchanged (no data loss)
- [ ] Search index consistency verified
- [ ] No increase in 404s for product pages
- [ ] Memory usage normal
- [ ] No DLQ increase

## Pre-Sale Checklist (Black Friday, New Collection Launch, etc.)

- [ ] Load test completed (expected peak + 1.5x safety margin)
  - Simulate browse, search, and detail page requests
  - Test with realistic product catalog size
- [ ] Autoscaling policies reviewed and tested
- [ ] Resource limits adequate (CPU, memory, network)
- [ ] Cache pre-warmed (bestsellers, featured products, category pages)
- [ ] Search index optimized; query latency <100ms p99
- [ ] Product images and metadata cached at CDN edge
- [ ] Rating/review cache refreshed
- [ ] Inventory sync with fulfillment system verified
- [ ] Related products algorithm tested with peak load
- [ ] Rate limiters configured per customer/IP
- [ ] On-call coverage confirmed
- [ ] Third-party services notified (recommendation engine, analytics)
- [ ] War room Slack channel created
- [ ] Synthetic monitoring enabled
- [ ] Circuit breakers configured for dependent services (search, inventory)
- [ ] Fallback UI ready if real-time data unavailable

**Scale-up commands ready:**
```bash
# Scale catalog service
kubectl scale deployment/product-catalog --replicas=N -n ecommerce

# Reindex search (if needed)
kubectl exec -it deployment/product-catalog -- python scripts/reindex_search.py
```

**Pre-sale verification (24h before):**
- [ ] Load test passed without errors
- [ ] Search latency acceptable
- [ ] Cache hit ratio >90%
- [ ] On-call rotation confirmed
- [ ] War room comms tested
- [ ] Fallback UI ready and tested

## Pre-Maintenance Checklist

- [ ] Maintenance window scheduled (1 week notice)
- [ ] Stakeholders notified (merchandising, operations, support)
- [ ] Data backup completed and tested (full catalog export)
- [ ] Rollback plan documented (schema and data revert)
- [ ] Staging mirrors production (latest catalog snapshot)
- [ ] Tested on staging 2+ times (data validation, search consistency)
- [ ] On-call team briefed
- [ ] Synthetic monitoring disabled
- [ ] Status page ready; comms plan in place
- [ ] Dependent services (search, inventory) notified
- [ ] Product image cache invalidation tested

**Post-maintenance verification:**
- [ ] Service responds to requests
- [ ] Product count and schema intact
- [ ] Search index reindexed and consistent
- [ ] Product images accessible
- [ ] Pricing data correct
- [ ] Category and tag associations intact
- [ ] Alerts firing

## Ongoing Monitoring (Daily/Weekly)

- [ ] Product catalog consistency (SKU uniqueness, no orphaned records)
- [ ] Search index drift (product count vs. index size)
- [ ] Query latency <100ms p99; flag outliers
- [ ] Cache hit ratio >90%; investigate drops
- [ ] Image CDN latency <200ms p99
- [ ] Rating/review freshness (update lag <1h)
- [ ] Inventory sync errors <0.1%; investigate failures
- [ ] SLO compliance tracked
- [ ] Slow query log reviewed
- [ ] Capacity trending; forecast peak load
- [ ] Recent production issues documented in runbook
- [ ] Schema changes validated (no breaking changes to dependent services)
