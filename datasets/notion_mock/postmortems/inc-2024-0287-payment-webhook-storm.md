# Postmortem: INC-2024-0287 — Payment Webhook Storm

**Date Written:** 2025-03-21
**Incident Date:** 2024-08-14 09:42–10:00 UTC
**Duration:** 18 minutes
**Severity:** P1
**DRI:** Payments Platform Team
**Attendees:** Payments Platform Team, SRE Team

## Executive Summary

payment webhook storm occurred on 2024-08-14. 312 duplicate orders created, 47 customer support tickets, 4 hours manual remediation. The incident was caused by stripe webhook retry storm due to their upstream infrastructure issues. checkout-service's idempotency dedup was rate-limited but not entirely effective. race condition window allowed duplicate order creation.. The service was recovered through enabled circuit breaker on webhook endpoint, identified and voided 312 duplicate orders, processed refunds.

## Timeline

| Time (UTC) | Actor | Action | Result |
|---|---|---|---|
| 09:42 | Monitoring System | Alert fired | Service metric exceeded threshold |
| 09:45 | On-Call Engineer | Paged | Notification received, joined war room |
| 09:50 | Platform Engineer | Investigated | Root cause identified from logs and metrics |
| 09:54 | Senior Engineer | Remediation deployed | Applied fixes and verified recovery |
| 10:00 | Monitoring System | Service recovered | Metrics returned to baseline |

## Root Cause Analysis (5 Whys)

1. Why did payment webhook storm occur?
   → Stripe webhook retry storm due to their upstream infrastructure issues. Checkout-service's idempotency dedup was rate-limited but not entirely effective. Race condition window allowed duplicate order creation.

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

- Enabled circuit breaker on webhook endpoint, identified and voided 312 duplicate orders, processed refunds
- Verified service recovered to baseline metrics
- Notified affected customers where applicable
- Escalated follow-up items to team backlog

## Action Items

| ID | Action | Owner | Due Date |
|---|---|---|---|
| A1 | Implement monitoring/alerting to catch recurrence | Payments Team | 2024-08-21 |
| A2 | Add automated safeguards (circuit breaker/fallback) | Payments Team | 2024-08-28 |
| A3 | Schedule architecture review and update runbook | Payments Team | 2024-09-04 |

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
