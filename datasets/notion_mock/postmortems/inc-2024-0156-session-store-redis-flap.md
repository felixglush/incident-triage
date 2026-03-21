# Postmortem: INC-2024-0156 — Session Store Redis Flap

**Date Written:** 2025-03-21
**Incident Date:** 2024-06-18 09:12–09:47 UTC
**Duration:** 35 minutes
**Severity:** P1
**DRI:** Authentication Team
**Attendees:** Authentication Team, SRE Team

## Executive Summary

session store redis flap occurred on 2024-06-18. Sessions dropped mid-request for 35 minutes, users logged out unexpectedly, 4,100+ re-authentication attempts. The incident was caused by redis session store had no replica configured. network partition isolated the single node. no automatic failover.. The service was recovered through restored redis connectivity, configured replicas, added sentinel for automatic failover.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 09:12 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 09:15 | On-Call Engineer | Paged | Notification received, joined war room |
| 09:20 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 09:24 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 09:47 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did session store redis flap occur?
   → Redis session store had no replica configured. Network partition isolated the single node. No automatic failover.

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

- Restored Redis connectivity, configured replicas, added sentinel for automatic failover
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Authentication Team | 2024-06-25 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Authentication Team | 2024-07-02 |
| A3 | Schedule architecture review and update runbook | Authentication Team | 2024-07-09 |

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

- Runbook: Auth & Sessions Runbook — Recorded Incidents section
- Slack: #incidents thread (internal link)
- Related incidents: Check runbook for similar failure patterns
