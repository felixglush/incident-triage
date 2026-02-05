# Disk Saturation

## Symptoms
- Disk usage exceeds 90%
- Writes fail with "no space left on device"
- Database or queue latency spikes

## Immediate Actions
1. Identify largest directories and files.
2. Clear temporary/log files if safe.
3. Expand volume if cleanup is insufficient.

## Investigation
- Review log rotation and retention settings.
- Check for runaway dumps or backups.
- Inspect growth trends per service.

## Resolution
- Fix retention policy or move heavy workloads.
- Add storage alerts with earlier thresholds.

## Verification
- Disk usage returns below 70%.
- Write errors cease.
