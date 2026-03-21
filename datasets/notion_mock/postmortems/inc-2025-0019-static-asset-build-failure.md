# Postmortem: INC-2025-0019 — Static Asset Build Failure

**Date Written:** 2025-03-21
**Incident Date:** 2025-03-15 10:47–11:14 UTC
**Duration:** 27 minutes
**Severity:** P1
**DRI:** Infrastructure Team
**Attendees:** Infrastructure Team, SRE Team

## Executive Summary

static asset build failure occurred on 2025-03-15. 27 minutes of 404 errors on CSS/JS assets, 23,000 users affected, broken storefront styling. The incident was caused by frontend build process failed silently during deployment. assets not uploaded to cdn origin. no pre-deployment validation.. The service was recovered through rolled back deployment, redeployed with validation checks, verified assets present before dns switch.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 10:47 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 10:50 | On-Call Engineer | Paged | Notification received, joined war room |
| 10:55 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 10:59 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 11:14 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did static asset build failure occur?
   → Frontend build process failed silently during deployment. Assets not uploaded to CDN origin. No pre-deployment validation.

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

- Rolled back deployment, redeployed with validation checks, verified assets present before DNS switch
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Infrastructure Team | 2025-03-22 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Infrastructure Team | 2025-03-29 |
| A3 | Schedule architecture review and update runbook | Infrastructure Team | 2025-04-05 |

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
