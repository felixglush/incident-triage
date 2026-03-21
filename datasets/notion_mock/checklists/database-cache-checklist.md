# Database & Cache Pre-Action Checklist

Use this checklist before any risky operation: deployments, config changes, major traffic events, maintenance windows. Database and cache are the foundation of all services; failures or data corruption cascade system-wide.

## Pre-Deploy Checklist

- [ ] All tests passing locally and in CI
- [ ] Code review approved by 2+ team members
- [ ] CHANGELOG.md updated
- [ ] Environment variables defined in `.env.example` and production
- [ ] Database migrations tested and have rollback plan
  - [ ] Migration forward-backward compatible
  - [ ] Test on staging with production data size
  - [ ] Rollback procedure documented and tested
- [ ] Feature flags configured for gradual rollout
- [ ] Schema changes reviewed (no breaking changes for current queries)
- [ ] Index changes tested for query impact
- [ ] Replication lag checked (replica latency <1s)
- [ ] Backup before deploy (full backup completed and tested)
- [ ] Cache invalidation strategy for any schema changes
- [ ] Alert thresholds reviewed; no suppression
- [ ] Runbook updated if behavior changed
- [ ] On-call engineer notified
- [ ] Deployment scheduled with team
- [ ] Connection pool settings verified

**Deploy command:**
```bash
# Run migrations (if any)
kubectl exec -it deployment/backend -- python -m alembic upgrade head

# Verify replication lag
kubectl exec -it pod/postgres-primary -- psql -c "SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;"
```

**Verify after deploy:**
- [ ] Error rate <0.1%
- [ ] P99 latency within 10% of baseline
- [ ] Replication lag <1s
- [ ] Table lock time <5min per table
- [ ] Connection pool healthy
- [ ] Cache hit ratio >90%
- [ ] Memory usage normal
- [ ] No DLQ increase
- [ ] Data integrity verified (row counts, checksums)

## Pre-Sale Checklist (Black Friday, Flash Sale, etc.)

- [ ] Load test completed (expected peak + 1.5x safety margin)
  - Simulate realistic query patterns and volume
  - Test with peak concurrent connection count
- [ ] Autoscaling policies reviewed and tested
- [ ] Resource limits adequate (CPU, memory, disk I/O)
- [ ] Read replica capacity reviewed and tested
- [ ] Cache capacity and eviction policy verified
- [ ] Connection pooling configured (PgBouncer, ProxySQL)
- [ ] Slow query logging enabled (log queries >1s)
- [ ] Database statistics updated (`ANALYZE` run on large tables)
- [ ] Index fragmentation checked (VACUUM, REINDEX if needed)
- [ ] Backup schedule verified (no gaps during sale)
- [ ] Replication monitored (replicas stay in sync)
- [ ] On-call coverage confirmed (2+ database engineers)
- [ ] Third-party backup services verified
- [ ] War room Slack channel created
- [ ] Synthetic monitoring enabled (read/write test queries)
- [ ] Circuit breakers configured for read/write failures
- [ ] Cache warming strategy ready (pre-load hot data)

**Scale-up commands ready:**
```bash
# Scale read replicas
kubectl scale statefulset/postgres-replica --replicas=N -n ecommerce

# Scale cache cluster
kubectl scale statefulset/redis --replicas=3 -n ecommerce

# Monitor replication lag
watch 'kubectl exec -it pod/postgres-primary -- psql -c "SELECT now() - pg_last_xact_replay_timestamp();"'

# Check cache memory usage
kubectl exec -it pod/redis-0 -- redis-cli INFO memory
```

**Pre-sale verification (24h before):**
- [ ] Load test passed without errors
- [ ] Query latency <100ms p99 at peak load
- [ ] Replication lag <1s
- [ ] Cache hit ratio >90%
- [ ] Read replicas healthy and in sync
- [ ] Backup completed successfully
- [ ] On-call rotation confirmed
- [ ] War room comms tested

## Pre-Maintenance Checklist

- [ ] Maintenance window scheduled (1 week notice)
- [ ] Stakeholders notified (all engineering teams)
- [ ] Full backup completed and tested (verify restoration works)
- [ ] Rollback plan documented
  - [ ] Data restore procedure
  - [ ] Replication recovery procedure
  - [ ] Cache invalidation if needed
- [ ] Staging mirrors production data (backup from prod)
- [ ] Tested on staging 2+ times
  - [ ] Schema changes on large tables
  - [ ] Replication recovery
  - [ ] Data integrity checks
- [ ] On-call team briefed (database-specific concerns)
- [ ] Synthetic monitoring disabled
- [ ] Status page ready; comms plan in place
- [ ] Application connection draining planned (gracefully close connections)
- [ ] Cache warming script ready (if needed post-maintenance)

**Post-maintenance verification:**
- [ ] Primary database responds
- [ ] Replication healthy (replicas in sync)
- [ ] Replication lag <1s
- [ ] Data integrity verified (row counts, checksums)
- [ ] Indexes healthy (no anomalies)
- [ ] Cache populated (or warming in progress)
- [ ] Query latency normal
- [ ] No spike in connection errors
- [ ] Alerts firing
- [ ] Backup completed post-maintenance

## Ongoing Monitoring (Daily/Weekly)

**Database Health:**
- [ ] Replication lag <1s; investigate delays
- [ ] Connection pool usage <80% of max
- [ ] Disk usage <80%; forecast when full
- [ ] Table bloat (dead rows) <20%; VACUUM if needed
- [ ] Index fragmentation <10%; REINDEX if needed

**Query Performance:**
- [ ] Query latency <100ms p99; flag spikes
- [ ] Slow query log reviewed (queries >1s)
- [ ] Query plan analyzed for table scans (missing indexes)
- [ ] Lock wait time <100ms; flag contention

**Backup & Recovery:**
- [ ] Backup completion time normal (no degradation)
- [ ] Backup size trending; forecast storage growth
- [ ] Backup restoration tested weekly (verify recoverability)
- [ ] Backup retention policy reviewed (comply with data governance)

**Replication & High Availability:**
- [ ] Replica lag <1s; investigate spikes
- [ ] All replicas healthy and in sync
- [ ] Replica memory usage <80%; forecast growth
- [ ] Replica CPU usage <70%

**Cache Performance:**
- [ ] Cache hit ratio >90%; investigate drops
- [ ] Cache memory usage <80% of allocated
- [ ] Eviction rate low (flag excessive evictions)
- [ ] Cache key expiration working correctly

**SLO & Capacity:**
- [ ] SLO compliance tracked (availability, latency)
- [ ] Capacity trending; forecast peak load
- [ ] Recent production issues documented in runbook
- [ ] Schema changes validated (no breaking changes)
- [ ] Connection pool health checked
