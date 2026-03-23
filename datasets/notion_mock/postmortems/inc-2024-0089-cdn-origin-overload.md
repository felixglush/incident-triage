# Postmortem: INC-2024-0089 — CDN Origin Overload

**Date Written:** 2025-03-21
**Incident Date:** 2024-05-10 14:33–15:11 UTC
**Duration:** 38 minutes
**Severity:** P0
**DRI:** Infrastructure Team
**Attendees:** Infrastructure Team, SRE Team

## Executive Summary

cdn origin overload occurred on 2024-05-10. 38 minutes of 403 errors on product images, 45,000 customers affected, perceived downtime. The incident was caused by cdn origin health check misconfigured. healthy origin was marked unhealthy by overly strict timeout (50ms). all traffic routed to single backup origin which was rate-limited.. The service was recovered through fixed health check timeout, rebalanced traffic, added circuit breaker to origin routing.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 14:33 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 14:36 | On-Call Engineer | Paged | Notification received, joined war room |
| 14:41 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 14:45 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 15:11 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did cdn origin overload occur?
   → CDN origin health check misconfigured. Healthy origin was marked unhealthy by overly strict timeout (50ms). All traffic routed to single backup origin which was rate-limited.

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

- Fixed health check timeout, rebalanced traffic, added circuit breaker to origin routing
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Infrastructure Team | 2024-05-17 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Infrastructure Team | 2024-05-24 |
| A3 | Schedule architecture review and update runbook | Infrastructure Team | 2024-05-31 |

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

- Runbook: CDN & Storefront Runbook — Recorded Incidents section
- Slack: #incidents thread (internal link)
- Related incidents: Check runbook for similar failure patterns
