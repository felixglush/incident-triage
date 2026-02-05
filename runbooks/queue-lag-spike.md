# Queue Lag Spike

## Symptoms
- Consumer lag exceeds alert threshold
- Message processing throughput drops
- Backlog grows steadily

## Immediate Actions
1. Scale consumers to regain throughput.
2. Check for stuck partitions or poison messages.
3. Verify downstream service health.

## Investigation
- Inspect recent code changes to consumer logic.
- Review broker disk I/O and network saturation.
- Identify slow message types via sampling.

## Resolution Steps
1. Roll back consumer deployment if regression found.
2. Pause traffic sources to drain backlog.
3. Rebalance partitions after scaling.

## Verification
- Lag returns to normal within SLA.
- Error rate on consumers returns to baseline.
