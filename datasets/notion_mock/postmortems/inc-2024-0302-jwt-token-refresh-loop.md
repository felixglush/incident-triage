# Postmortem: INC-2024-0302 — JWT Token Refresh Loop

**Date Written:** 2025-03-21
**Incident Date:** 2024-09-28 16:05–16:33 UTC
**Duration:** 28 minutes
**Severity:** P2
**DRI:** Authentication Team
**Attendees:** Authentication Team, SRE Team

## Executive Summary

jwt token refresh loop occurred on 2024-09-28. Refresh token endpoint performance degraded, 28 minutes of elevated latency, P99 latency 8.2 seconds. The incident was caused by token refresh logic had o(n) query to check revocation list. no caching of revoked tokens. revocation list grew to 50,000 entries.. The service was recovered through added redis cache for revoked tokens, implemented efficient revocation check with bloom filter.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 16:05 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 16:08 | On-Call Engineer | Paged | Notification received, joined war room |
| 16:13 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 16:17 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 16:33 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did jwt token refresh loop occur?
   → Token refresh logic had O(n) query to check revocation list. No caching of revoked tokens. Revocation list grew to 50,000 entries.

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

- Added Redis cache for revoked tokens, implemented efficient revocation check with Bloom filter
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Authentication Team | 2024-10-05 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Authentication Team | 2024-10-12 |
| A3 | Schedule architecture review and update runbook | Authentication Team | 2024-10-19 |

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
