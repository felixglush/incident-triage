# Synthetic Incident Seeder — Design Spec

**Date:** 2026-03-21
**Branch:** codex/phase-4-chat-rag

---

## Overview

Seed the OpsRelay database with realistic synthetic incidents derived from the six ecommerce runbooks and their postmortems in `datasets/notion_mock/`. Alerts travel through the full ingestion pipeline: webhook endpoint → Celery worker → ML classification/entity extraction → incident grouping.

---

## Components

### 1. `datasets/generate_synthetic_scenarios.py`

A one-time generator script. Spawns a Haiku subagent that reads all six runbook `.md` files and all 18 postmortem `.md` files from `datasets/notion_mock/` directly (no Notion API or token required). Writes `datasets/synthetic_scenarios.json`. Re-run to regenerate or extend the fixture.

**Postmortem-to-service mapping:** The postmortem files contain an incident ID (e.g. `INC-2024-0112`) in their content. Each runbook file references those IDs in its "Recorded Incidents" section. The subagent maps each postmortem to a service by matching its incident ID against the runbook cross-references. The six service slugs correspond to the runbook filenames: `checkout-payments`, `product-catalog`, `cdn-storefront`, `auth-sessions`, `queue-workers`, `database-cache`.

**External ID uniqueness:** Each alert gets a stable ID of the form `{platform}-{postmortem_ref}-{alert_index}` (e.g. `dd-inc-2024-0112-001`, `sentry-inc-2024-0112-002`). This pattern guarantees uniqueness across all 18 scenarios.

### 2. `datasets/synthetic_scenarios.json`

Pre-generated fixture committed to the repo. Contains 18 scenarios (one per postmortem), each with 2–4 alerts. Infrastructure/metric alerts use Datadog format; application exception alerts use Sentry format.

### 3. `datasets/seed_synthetic_incidents.py`

Reads the fixture, substitutes live timestamps, and POSTs each alert to `/webhook/datadog` or `/webhook/sentry`. Requires `SKIP_SIGNATURE_VERIFICATION=true` in the environment (simulation tool — no HMAC needed).

**Pre-requisite:** `synthetic_scenarios.json` must exist. Run `generate_synthetic_scenarios.py` first if it does not.

**Idempotency:** Alert `external_id` values are stable strings. The backend deduplicates on `(source, external_id)`, so running the seeder twice returns the existing alert rather than creating a duplicate.

**Error handling:** If a webhook POST returns non-200, the seeder logs the failure, continues to the next alert, and includes the failure count in the final summary. It does not abort on individual failures.

### 4. `backend/app/workers/tasks.py` — grouping window

Change the hardcoded `timedelta(minutes=5)` in `group_alerts_into_incidents` to read `ALERT_GROUPING_WINDOW_MINUTES` env var (default `30`).

Unit tests mock Celery task internals and are unaffected. Any integration test that asserts grouping behavior based on a 5-minute window must set `ALERT_GROUPING_WINDOW_MINUTES=5` in its test environment. Run `grep -r "grouping\|timedelta.*5\|group_alerts" tests/` to identify affected tests before merging.

---

## Scenario JSON Structure

```json
[
  {
    "scenario_id": "inc-2024-0112-black-friday-checkout-latency",
    "service": "checkout-payments",
    "postmortem_ref": "inc-2024-0112",
    "description": "Black Friday checkout latency spike under load",
    "alerts": [
      {
        "platform": "datadog",
        "payload": {
          "id": "dd-inc-2024-0112-001",
          "title": "P99 checkout latency > 8s on payment-processor",
          "body": "P99 latency exceeded 8000ms for 5 consecutive minutes on payment-processor in us-east-1.",
          "priority": "critical",
          "last_updated": "{{TS_0}}",
          "tags": ["service:payment-processor", "env:production", "region:us-east-1"]
        }
      },
      {
        "platform": "sentry",
        "payload": {
          "action": "triggered",
          "data": {
            "issue": {
              "id": "sentry-inc-2024-0112-002",
              "title": "TimeoutError: payment gateway timed out after 30s",
              "level": "error",
              "lastSeen": "{{TS_1}}",
              "project": {
                "id": "1",
                "name": "checkout-service",
                "slug": "checkout-service",
                "platform": "python"
              }
            }
          }
        }
      }
    ]
  }
]
```

### Timestamp substitution

`{{TS_N}}` placeholders use a zero-based index **within each scenario's alerts array** (reset per scenario). The seeder computes:

```
base_time     = now - (scenario_index * 35 minutes)
alert_time[i] = base_time + (i * 60 seconds)   # ISO 8601 UTC string
```

- `last_updated` (Datadog) and `lastSeen` (Sentry) both receive the per-alert timestamp.
- The 35-minute inter-scenario gap exceeds the 30-minute grouping window, so each scenario produces a distinct incident.
- The 60-second intra-scenario offset keeps all alerts in a scenario within the same 30-minute window so they group into one incident.

Sentry payloads use the **issue alert nested format** (`data.issue.*`) which is the primary format handled by `process_sentry_webhook` in `webhook_processor.py`.

---

## Seeder Script Behavior

1. Pre-flight `GET /health` (single attempt) — abort if non-200 or unreachable.
2. Load `datasets/synthetic_scenarios.json` — abort if file not found.
3. Optionally filter by `--service` (matches scenario `service` field) or cap with `--count`.
4. For each scenario:
   - Compute per-alert timestamps using the formula above.
   - Replace `{{TS_N}}` placeholders in the payload (N = alert index within scenario).
   - POST to `/webhook/{platform}` as `application/json`.
   - Print one progress line: `[scenario_id] platform | title → HTTP status`.
5. Print summary: scenarios attempted, alerts sent, failures.

**Dry-run mode:** Skips the health check and all POSTs. Timestamps are still substituted. Prints each alert as a `curl`-equivalent line with the final payload.

### CLI

```
python datasets/seed_synthetic_incidents.py [OPTIONS]

Options:
  --url TEXT       Backend base URL  [default: http://localhost:8000]
  --service TEXT   Filter to one service slug (e.g. checkout-payments)
  --count INT      Max number of scenarios to send
  --dry-run        Substitute timestamps and print payloads; do not POST
```

### Environment

| Var | Required | Purpose |
|-----|----------|---------|
| `SKIP_SIGNATURE_VERIFICATION` | Yes (set `true`) | Bypasses HMAC check on webhook endpoints |
| `ALERT_GROUPING_WINDOW_MINUTES` | No (default `30`) | Controls grouping window in Celery task |

---

## Grouping Window Change

**File:** `backend/app/workers/tasks.py`, function `group_alerts_into_incidents`

```python
# Before (Phase 1 — hardcoded)
time_window = alert.alert_timestamp - timedelta(minutes=5)

# After
window_minutes = int(os.getenv("ALERT_GROUPING_WINDOW_MINUTES", "30"))
time_window = alert.alert_timestamp - timedelta(minutes=window_minutes)
```

Rationale: real distributed-system cascades (e.g. DB replica lag → stale inventory reads → checkout errors) develop across multiple services over 15–30 minutes. Five minutes causes realistic alert clusters to fragment into spurious separate incidents.

---

## Scenario Coverage

18 scenarios across 6 services:

| Service | Postmortems |
|---------|-------------|
| checkout-payments | inc-2024-0112, inc-2024-0287, inc-2025-0044 |
| product-catalog | inc-2024-0331, inc-2025-0071 |
| cdn-storefront | inc-2024-0089, inc-2024-0198, inc-2024-0445, inc-2025-0019 |
| auth-sessions | inc-2024-0156, inc-2024-0302, inc-2025-0033 |
| queue-workers | inc-2024-0118, inc-2024-0377, inc-2025-0058 |
| database-cache | inc-2024-0203, inc-2024-0419, inc-2025-0012 |

Each scenario has 2–4 alerts. Datadog format is used for metric/infrastructure signals; Sentry format for application exceptions.

---

## Out of Scope

- PagerDuty support (webhook handler is a stub)
- HMAC signature generation
- Fixture auto-regeneration on git hooks
- Historical timestamps anchored to original postmortem dates
- Schema validation of generated payloads against webhook processor contracts
