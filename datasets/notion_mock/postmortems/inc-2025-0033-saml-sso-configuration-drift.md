# Postmortem: INC-2025-0033 — SAML SSO Configuration Drift

**Date Written:** 2025-03-21
**Incident Date:** 2025-02-14 07:33–08:01 UTC
**Duration:** 28 minutes
**Severity:** P1
**DRI:** Authentication Team
**Attendees:** Authentication Team, SRE Team

## Executive Summary

saml sso configuration drift occurred on 2025-02-14. Enterprise SSO users unable to login for 28 minutes, 12 companies affected, escalations to account managers. The incident was caused by saml idp certificate was rotated upstream. service config not updated. no certificate expiry monitoring.. The service was recovered through updated saml certificate in service config, added monitoring for cert expiry (30-day warnings).

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 07:33 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 07:36 | On-Call Engineer | Paged | Notification received, joined war room |
| 07:41 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 07:45 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 08:01 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did saml sso configuration drift occur?
   → SAML IdP certificate was rotated upstream. Service config not updated. No certificate expiry monitoring.

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

- Updated SAML certificate in service config, added monitoring for cert expiry (30-day warnings)
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Authentication Team | 2025-02-21 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Authentication Team | 2025-02-28 |
| A3 | Schedule architecture review and update runbook | Authentication Team | 2025-03-07 |

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
