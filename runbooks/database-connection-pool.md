# Database Connection Pool Saturation

## Symptoms
- Connection pool exhausted errors
- Timeout spikes on DB-backed endpoints

## Immediate Actions
1. Check connection count and long-running queries.
2. Temporarily increase pool size.
3. Restart application pods if needed.

## Diagnosis
- `SELECT count(*) FROM pg_stat_activity;`
- Identify long-running queries with `pg_stat_activity`.

## Resolution
- Fix connection leaks.
- Add indexes for slow queries.
