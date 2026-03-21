# Postmortem: INC-2024-0331 — Search Index Corruption

**Date Written:** 2025-03-21
**Incident Date:** 2024-10-22 08:15–09:42 UTC
**Duration:** 87 minutes
**Severity:** P1
**DRI:** Product Catalog Team
**Attendees:** Product Catalog Team, SRE Team

## Executive Summary

search index corruption occurred on 2024-10-22. Search returning 0 results for 40% of common queries, product discoverability broken for 87 minutes. The incident was caused by elasticsearch snapshot restore operation during index rebalancing corrupted shard mappings. no validation of index health after restore.. The service was recovered through restored from prior clean snapshot, replayed 87 minutes of product updates, rebuilt inverted index.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 08:15 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 08:18 | On-Call Engineer | Paged | Notification received, joined war room |
| 08:23 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 08:27 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 09:42 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did search index corruption occur?
   → Elasticsearch snapshot restore operation during index rebalancing corrupted shard mappings. No validation of index health after restore.

2. Why did this infrastructure/code issue exist?
   → Insufficient monitoring or safeguards were in place during design/implementation.

3. Why was the issue not caught earlier?
   → Load testing or chaos engineering practices were not applied before production deployment.

4. Why don't we have automated detection for this class of issue?
   → Monitoring and alerting were insufficient. Detection thresholds were set too high.

5. Why don't we have systematic processes to prevent regression?
   → Postmortem action items were not tracked to completion or process improvements were not institutionalized.

## Contributing Factors

- Insufficient monitoring/alerting for this failure mode
- Design did not account for scale or edge cases
- Load testing did not cover peak traffic scenarios
- No circuit breaker or fallback mechanism
- Missing safeguards in code or infrastructure
- Process gap in pre-deployment validation

## Remediation (What We Did)

- Restored from prior clean snapshot, replayed 87 minutes of product updates, rebuilt inverted index
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Product Team | 2024-10-29 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Product Team | 2024-11-05 |
| A3 | Schedule architecture review and update runbook | Product Team | 2024-11-12 |

## Lessons Learned

**What went well:**
- Team responded quickly to alerts and mobilized war room efficiently
- Root cause identified within acceptable time frame
- Automated recovery steps executed smoothly
- Effective communication throughout the incident

**What didn't go well:**
- Initial detection took longer than desired (alert threshold was too permissive)
- Manual intervention was required instead of automated mitigation
- No preventive monitoring was in place for this failure mode
- Remediation could have been faster with better runbook

**What we'll do differently:**
- Implement automated circuit breakers and fallback mechanisms
- Add comprehensive monitoring for all critical paths
- Conduct chaos engineering exercises to test failure scenarios
- Improve runbook documentation with concrete troubleshooting steps
- Establish SLA for postmortem action item completion and tracking
- Review dependencies and failure modes during architecture reviews

## References

- Runbook: Product Catalog & Search Runbook — Recorded Incidents section
- Slack: #incidents thread (internal link)
- Related incidents: Check runbook for similar failure patterns
