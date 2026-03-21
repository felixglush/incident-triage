# Postmortem: INC-2024-0419 — Connection Pool Exhaustion

**Date Written:** 2025-03-21
**Incident Date:** 2024-10-29 15:22–15:58 UTC
**Duration:** 36 minutes
**Severity:** P1
**DRI:** Database Team
**Attendees:** Database Team, SRE Team

## Executive Summary

connection pool exhaustion occurred on 2024-10-29. Service unable to acquire DB connections for 36 minutes, application hung, timeouts on all queries. The incident was caused by long-running transaction held connection without releasing. connection pool max size reached. no connection timeout.. The service was recovered through killed blocking transaction, increased pool size, added connection timeout and idle timeout.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 15:22 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 15:25 | On-Call Engineer | Paged | Notification received, joined war room |
| 15:30 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 15:34 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 15:58 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did connection pool exhaustion occur?
   → Long-running transaction held connection without releasing. Connection pool max size reached. No connection timeout.

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

- Killed blocking transaction, increased pool size, added connection timeout and idle timeout
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Database Team | 2024-11-05 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Database Team | 2024-11-12 |
| A3 | Schedule architecture review and update runbook | Database Team | 2024-11-19 |

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
