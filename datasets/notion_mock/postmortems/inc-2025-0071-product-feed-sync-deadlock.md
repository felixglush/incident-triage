# Postmortem: INC-2025-0071 — Product Feed Sync Deadlock

**Date Written:** 2025-03-21
**Incident Date:** 2025-01-30 03:22–04:11 UTC
**Duration:** 49 minutes
**Severity:** P1
**DRI:** Product Catalog Team
**Attendees:** Product Catalog Team, SRE Team

## Executive Summary

product feed sync deadlock occurred on 2025-01-30. New products not visible for 49 minutes, 2 SKUs unable to be updated, sync job hung indefinitely. The incident was caused by concurrent product update during feed sync created database lock. no transaction timeout on feed job. lock escalated to table-level.. The service was recovered through killed blocking query, replayed failed product updates, added transaction timeout to sync job.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 03:22 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 03:25 | On-Call Engineer | Paged | Notification received, joined war room |
| 03:30 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 03:34 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 04:11 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did product feed sync deadlock occur?
   → Concurrent product update during feed sync created database lock. No transaction timeout on feed job. Lock escalated to table-level.

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

- Killed blocking query, replayed failed product updates, added transaction timeout to sync job
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Product Team | 2025-02-06 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Product Team | 2025-02-13 |
| A3 | Schedule architecture review and update runbook | Product Team | 2025-02-20 |

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
