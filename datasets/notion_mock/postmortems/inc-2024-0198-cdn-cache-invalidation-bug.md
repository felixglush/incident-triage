# Postmortem: INC-2024-0198 — CDN Cache Invalidation Bug

**Date Written:** 2025-03-21
**Incident Date:** 2024-07-15 11:22–11:58 UTC
**Duration:** 36 minutes
**Severity:** P1
**DRI:** Infrastructure Team
**Attendees:** Infrastructure Team, SRE Team

## Executive Summary

cdn cache invalidation bug occurred on 2024-07-15. Stale product images served for 36 minutes, 34,000 impressions of incorrect photos, customer confusion. The incident was caused by cache invalidation routine had off-by-one error in url path matching. purge requests didn't match origin paths correctly.. The service was recovered through deployed hot-fix for cache invalidation regex, manually purged affected cache keys, verified with test requests.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 11:22 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 11:25 | On-Call Engineer | Paged | Notification received, joined war room |
| 11:30 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 11:34 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 11:58 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did cdn cache invalidation bug occur?
   → Cache invalidation routine had off-by-one error in URL path matching. Purge requests didn't match origin paths correctly.

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

- Deployed hot-fix for cache invalidation regex, manually purged affected cache keys, verified with test requests
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Infrastructure Team | 2024-07-22 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Infrastructure Team | 2024-07-29 |
| A3 | Schedule architecture review and update runbook | Infrastructure Team | 2024-08-05 |

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
