# Postmortem: INC-2024-0203 — Read Replica Lag Causing Stale Inventory Reads

**Date Written:** 2025-03-21
**Incident Date:** 2024-09-05 11:30–11:54 UTC
**Duration:** 24 minutes
**Severity:** P1
**DRI:** Database Team
**Attendees:** Database Team, SRE Team

## Executive Summary

read replica lag causing stale inventory reads occurred on 2024-09-05. Stale inventory reads for 24 minutes, 156 oversold items, $7,200 in refunds issued. The incident was caused by analytics workload running on oltp read replicas with no query timeout. replica lag not monitored. no fallback to primary.. The service was recovered through separated analytics workload to dedicated read replica, added lag monitoring, implemented primary fallback.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 11:30 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 11:33 | On-Call Engineer | Paged | Notification received, joined war room |
| 11:38 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 11:42 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 11:54 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did read replica lag causing stale inventory reads occur?
   → Analytics workload running on OLTP read replicas with no query timeout. Replica lag not monitored. No fallback to primary.

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

- Separated analytics workload to dedicated read replica, added lag monitoring, implemented primary fallback
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Database Team | 2024-09-12 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Database Team | 2024-09-19 |
| A3 | Schedule architecture review and update runbook | Database Team | 2024-09-26 |

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

- Runbook: Database & Cache Runbook — Recorded Incidents section
- Slack: #incidents thread (internal link)
- Related incidents: Check runbook for similar failure patterns
