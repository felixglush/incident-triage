# Postmortem: INC-2024-0118 — Background Worker Queue Poison Message

**Date Written:** 2025-03-21
**Incident Date:** 2024-04-03 13:18–14:02 UTC
**Duration:** 44 minutes
**Severity:** P1
**DRI:** Platform Engineering
**Attendees:** Platform Engineering, SRE Team

## Executive Summary

background worker queue poison message occurred on 2024-04-03. 44 minutes of failed order processing, 3,240 orders queued but not processed, cascading delays. The incident was caused by worker process encountered malformed message in queue. error handler re-queued message infinitely. no max retry logic.. The service was recovered through drained poison message, added dead-letter queue, implemented max retry threshold (3 attempts).

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 13:18 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 13:21 | On-Call Engineer | Paged | Notification received, joined war room |
| 13:26 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 13:30 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 14:02 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did background worker queue poison message occur?
   → Worker process encountered malformed message in queue. Error handler re-queued message infinitely. No max retry logic.

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

- Drained poison message, added dead-letter queue, implemented max retry threshold (3 attempts)
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Platform Team | 2024-04-10 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Platform Team | 2024-04-17 |
| A3 | Schedule architecture review and update runbook | Platform Team | 2024-04-24 |

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
