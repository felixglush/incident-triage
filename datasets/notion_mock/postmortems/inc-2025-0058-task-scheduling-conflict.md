# Postmortem: INC-2025-0058 — Task Scheduling Conflict

**Date Written:** 2025-03-21
**Incident Date:** 2025-03-08 02:15–03:09 UTC
**Duration:** 54 minutes
**Severity:** P2
**DRI:** Platform Engineering
**Attendees:** Platform Engineering, SRE Team

## Executive Summary

task scheduling conflict occurred on 2025-03-08. Duplicate inventory adjustments for 54 minutes, 847 items double-decremented from stock, manual reconciliation required. The incident was caused by scheduled task ran concurrently with manual trigger. no locking or idempotency. inventory adjustment not idempotent.. The service was recovered through added distributed lock to inventory tasks, marked task as idempotent with dedup key.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 02:15 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 02:18 | On-Call Engineer | Paged | Notification received, joined war room |
| 02:23 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 02:27 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 03:09 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did task scheduling conflict occur?
   → Scheduled task ran concurrently with manual trigger. No locking or idempotency. Inventory adjustment not idempotent.

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

- Added distributed lock to inventory tasks, marked task as idempotent with dedup key
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Platform Team | 2025-03-15 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Platform Team | 2025-03-22 |
| A3 | Schedule architecture review and update runbook | Platform Team | 2025-03-29 |

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

- Runbook: Queue & Workers Runbook — Recorded Incidents section
- Slack: #incidents thread (internal link)
- Related incidents: Check runbook for similar failure patterns
