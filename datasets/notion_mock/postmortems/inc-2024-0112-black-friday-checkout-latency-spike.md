# Postmortem: INC-2024-0112 — Black Friday Checkout Latency Spike

**Date Written:** 2025-03-21
**Incident Date:** 2024-11-29 14:10–14:40 UTC
**Duration:** 30 minutes
**Severity:** P0
**DRI:** Payments Platform Team
**Attendees:** Payments Platform Team, SRE Team

## Executive Summary

black friday checkout latency spike occurred on 2024-11-29. 1,847 abandoned checkouts, ~$340,000 GMV lost, 12,300+ customers affected. The incident was caused by redis memory exhaustion (maxmemory=4gb, traffic consumed 6.1gb). eviction policy dropped active cart sessions, causing fallback to database reconstruction which saturated connection pool.. The service was recovered through expanded redis memory to 8gb, scaled checkout-service to 12 replicas, reloaded active sessions from db.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 14:10 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 14:13 | On-Call Engineer | Paged | Notification received, joined war room |
| 14:18 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 14:22 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 14:40 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did black friday checkout latency spike occur?
   → Redis memory exhaustion (maxmemory=4GB, traffic consumed 6.1GB). Eviction policy dropped active cart sessions, causing fallback to database reconstruction which saturated connection pool.

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

- Expanded Redis memory to 8GB, scaled checkout-service to 12 replicas, reloaded active sessions from DB
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Payments Team | 2024-12-06 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Payments Team | 2024-12-13 |
| A3 | Schedule architecture review and update runbook | Payments Team | 2024-12-20 |

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

- Runbook: Checkout & Payments Runbook — Recorded Incidents section
- Slack: #incidents thread (internal link)
- Related incidents: Check runbook for similar failure patterns
