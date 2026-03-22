# Synthetic Incident Seeder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-script pipeline that uses Claude Haiku to generate realistic ecommerce incident scenarios from existing runbooks/postmortems, then seeds them through the full OpsRelay webhook→Celery→ML pipeline.

**Architecture:** `generate_synthetic_scenarios.py` calls Claude Haiku (via Anthropic SDK) with all 6 runbooks + 18 postmortems and writes `synthetic_scenarios.json`. `seed_synthetic_incidents.py` reads that fixture, injects live timestamps, and POSTs to the running backend's webhook endpoints. The Celery grouping window in `tasks.py` is widened from 5 to 30 minutes (env-configurable) so realistic multi-service cascades group correctly.

**Tech Stack:** Python 3, `requests`, `anthropic` SDK (Haiku model), `argparse`, `pytest`, `unittest.mock`

**Spec:** `docs/superpowers/specs/2026-03-21-synthetic-incident-seeder-design.md`

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `backend/app/workers/tasks.py:254` | Replace hardcoded 5-min window with env var |
| Modify | `tests/backend/unit/test_celery_tasks.py:284` | Fix test that assumes 5-min window |
| Create | `datasets/generate_synthetic_scenarios.py` | Calls Haiku to write the fixture |
| Create | `datasets/synthetic_scenarios.json` | Generated fixture (committed after running generator) |
| Create | `datasets/seed_synthetic_incidents.py` | Reads fixture, POSTs to webhook endpoints |
| Create | `tests/datasets/test_seed_synthetic_incidents.py` | Unit tests for seeder logic |

---

## Task 1: Make the grouping window configurable

The hardcoded `timedelta(minutes=5)` in `group_alerts_into_incidents` will fragment realistic cascades. Change it to read `ALERT_GROUPING_WINDOW_MINUTES` (default 30). One existing test (`test_alerts_outside_window_create_separate_incidents`) uses a 10-minute gap expecting separation — it must be patched to set the env var to 5.

**Files:**
- Modify: `backend/app/workers/tasks.py:254-255`
- Modify: `tests/backend/unit/test_celery_tasks.py:284-307`
- Modify: `tests/backend/unit/test_celery_tasks.py` (add two new test cases)

- [ ] **Step 1: Write two new failing tests for env-var-driven window**

Add to `tests/backend/unit/test_celery_tasks.py` inside the existing `TestGroupAlertsIntoIncidents` class:

```python
@pytest.mark.unit
@pytest.mark.database
def test_grouping_window_respects_env_var_wide(self, db_session, monkeypatch):
    """Alerts 10 min apart group together when window is 15 min."""
    monkeypatch.setenv("ALERT_GROUPING_WINDOW_MINUTES", "15")
    configure_factories(db_session)
    base_time = datetime.now(timezone.utc)

    alert1 = AlertFactory(alert_timestamp=base_time, incident_id=None)
    db_session.commit()
    incident_id_1 = group_alerts_into_incidents(db_session, alert1)

    alert2 = AlertFactory(
        alert_timestamp=base_time + timedelta(minutes=10), incident_id=None
    )
    db_session.commit()
    incident_id_2 = group_alerts_into_incidents(db_session, alert2)

    assert incident_id_1 == incident_id_2

@pytest.mark.unit
@pytest.mark.database
def test_grouping_window_respects_env_var_narrow(self, db_session, monkeypatch):
    """Alerts 10 min apart create separate incidents when window is 5 min."""
    monkeypatch.setenv("ALERT_GROUPING_WINDOW_MINUTES", "5")
    configure_factories(db_session)
    base_time = datetime.now(timezone.utc)

    alert1 = AlertFactory(alert_timestamp=base_time, incident_id=None)
    db_session.commit()
    incident_id_1 = group_alerts_into_incidents(db_session, alert1)

    alert2 = AlertFactory(
        alert_timestamp=base_time + timedelta(minutes=10), incident_id=None
    )
    db_session.commit()
    incident_id_2 = group_alerts_into_incidents(db_session, alert2)

    assert incident_id_1 != incident_id_2
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```
pytest tests/backend/unit/test_celery_tasks.py::TestGroupAlertsIntoIncidents::test_grouping_window_respects_env_var_wide tests/backend/unit/test_celery_tasks.py::TestGroupAlertsIntoIncidents::test_grouping_window_respects_env_var_narrow -v
```

Expected: both FAIL (function still uses hardcoded 5 minutes).

- [ ] **Step 3: Update `group_alerts_into_incidents` in tasks.py**

In `backend/app/workers/tasks.py`, find line 254-255:
```python
        # Calculate time window (5 minutes before alert)
        time_window = alert.alert_timestamp - timedelta(minutes=5)
```

Replace with:
```python
        # Calculate time window — configurable for realistic cascade scenarios
        window_minutes = int(os.getenv("ALERT_GROUPING_WINDOW_MINUTES", "30"))
        time_window = alert.alert_timestamp - timedelta(minutes=window_minutes)
```

(`os` is already imported at the top of the file.)

- [ ] **Step 4: Fix the existing test that assumed a 5-minute window**

In `tests/backend/unit/test_celery_tasks.py`, find `test_alerts_outside_window_create_separate_incidents` (around line 284). Add `monkeypatch` to its signature and set the env var:

```python
def test_alerts_outside_window_create_separate_incidents(self, db_session, monkeypatch):
    """Test that alerts outside window create separate incidents."""
    monkeypatch.setenv("ALERT_GROUPING_WINDOW_MINUTES", "5")
    configure_factories(db_session)
    # ... rest of test unchanged
```

- [ ] **Step 5: Run the full grouping test class**

```
pytest tests/backend/unit/test_celery_tasks.py::TestGroupAlertsIntoIncidents -v
```

Expected: all tests PASS.

- [ ] **Step 6: Run the full unit test suite to catch any regressions**

```
pytest tests/ -m unit -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/workers/tasks.py tests/backend/unit/test_celery_tasks.py
git commit -m "feat: make alert grouping window configurable via ALERT_GROUPING_WINDOW_MINUTES (default 30m)"
```

---

## Task 2: Write the scenario generator script

This script calls Claude Haiku with all runbook and postmortem content, asking it to produce a `synthetic_scenarios.json` fixture. It requires `ANTHROPIC_API_KEY` in the environment. No TDD — it's a one-shot LLM-powered generator.

**Files:**
- Create: `datasets/generate_synthetic_scenarios.py`

- [ ] **Step 1: Create `datasets/generate_synthetic_scenarios.py`**

```python
#!/usr/bin/env python3
"""
Generate synthetic incident scenarios from ecommerce runbooks and postmortems.

Calls Claude Haiku with all runbook + postmortem content from datasets/notion_mock/
and asks it to produce datasets/synthetic_scenarios.json.

Requirements:
    ANTHROPIC_API_KEY must be set in the environment.

Usage:
    python datasets/generate_synthetic_scenarios.py
    python datasets/generate_synthetic_scenarios.py --output datasets/synthetic_scenarios.json
"""
import json
import sys
import argparse
from pathlib import Path

import anthropic

NOTION_MOCK_DIR = Path("datasets/notion_mock")
DEFAULT_OUTPUT = Path("datasets/synthetic_scenarios.json")

SERVICE_SLUGS = [
    "checkout-payments",
    "product-catalog",
    "cdn-storefront",
    "auth-sessions",
    "queue-workers",
    "database-cache",
]

POSTMORTEM_SERVICE_MAP = {
    "inc-2024-0112": "checkout-payments",
    "inc-2024-0287": "checkout-payments",
    "inc-2025-0044": "checkout-payments",
    "inc-2024-0331": "product-catalog",
    "inc-2025-0071": "product-catalog",
    "inc-2024-0089": "cdn-storefront",
    "inc-2024-0198": "cdn-storefront",
    "inc-2024-0445": "cdn-storefront",
    "inc-2025-0019": "cdn-storefront",
    "inc-2024-0156": "auth-sessions",
    "inc-2024-0302": "auth-sessions",
    "inc-2025-0033": "auth-sessions",
    "inc-2024-0118": "queue-workers",
    "inc-2024-0377": "queue-workers",
    "inc-2025-0058": "queue-workers",
    "inc-2024-0203": "database-cache",
    "inc-2024-0419": "database-cache",
    "inc-2025-0012": "database-cache",
}


def load_runbooks() -> str:
    """Read all runbook markdown files and concatenate them."""
    parts = []
    for slug in SERVICE_SLUGS:
        path = NOTION_MOCK_DIR / f"{slug}-runbook.md"
        if path.exists():
            parts.append(f"=== RUNBOOK: {slug} ===\n{path.read_text()}")
    return "\n\n".join(parts)


def load_postmortems() -> dict[str, str]:
    """Return dict of postmortem_ref → markdown content."""
    postmortems = {}
    pm_dir = NOTION_MOCK_DIR / "postmortems"
    for path in sorted(pm_dir.glob("*.md")):
        # Derive ref from filename: inc-2024-0112-black-friday... → inc-2024-0112
        parts = path.stem.split("-")
        if len(parts) >= 3:
            ref = "-".join(parts[:3])  # e.g. inc-2024-0112
            postmortems[ref] = path.read_text()
    return postmortems


def build_prompt(runbooks: str, postmortems: dict[str, str]) -> str:
    pm_block = "\n\n".join(
        f"=== POSTMORTEM: {ref} (service: {POSTMORTEM_SERVICE_MAP.get(ref, 'unknown')}) ===\n{content}"
        for ref, content in postmortems.items()
    )

    return f"""You are generating a synthetic incident scenario fixture for a monitoring system test harness.

Read the following runbooks and postmortems, then produce a JSON array of exactly 18 scenario objects — one per postmortem.

RUNBOOKS:
{runbooks}

POSTMORTEMS:
{pm_block}

OUTPUT FORMAT — a JSON array where each element is:
{{
  "scenario_id": "<postmortem_ref>-<short-slug>",
  "service": "<service-slug>",
  "postmortem_ref": "<inc-YYYY-NNNN>",
  "description": "<one-sentence summary of the incident>",
  "alerts": [
    {{
      "platform": "datadog",
      "payload": {{
        "id": "dd-<postmortem_ref>-001",
        "title": "<realistic metric alert title>",
        "body": "<2-3 sentence alert body with realistic metrics from the postmortem>",
        "priority": "critical|high|normal",
        "last_updated": "{{{{TS_0}}}}",
        "tags": ["service:<actual-service-name>", "env:production", "region:<region>"]
      }}
    }},
    {{
      "platform": "sentry",
      "payload": {{
        "action": "triggered",
        "data": {{
          "issue": {{
            "id": "sentry-<postmortem_ref>-002",
            "title": "<realistic exception class and message from postmortem>",
            "level": "fatal|error|warning",
            "lastSeen": "{{{{TS_1}}}}",
            "project": {{
              "id": "1",
              "name": "<service-slug>",
              "slug": "<service-slug>",
              "platform": "python"
            }}
          }}
        }}
      }}
    }}
  ]
}}

RULES:
- Use the postmortem content to write realistic titles, error messages, and metrics.
- Use {{{{TS_0}}}}, {{{{TS_1}}}}, {{{{TS_2}}}}, {{{{TS_3}}}} as timestamp placeholders (zero-indexed per alert, reset per scenario).
- Each scenario must have 2-4 alerts. First alert is always Datadog (metric/infra). Second is always Sentry (exception). Optional 3rd/4th can be either.
- Use the POSTMORTEM_SERVICE_MAP service assignments above.
- External IDs must be unique: dd-<postmortem_ref>-001, sentry-<postmortem_ref>-002, etc.
- Output ONLY the JSON array. No markdown fences, no explanation.
"""


def generate(output_path: Path) -> None:
    runbooks = load_runbooks()
    postmortems = load_postmortems()

    print(f"Loaded {len(postmortems)} postmortems across {len(SERVICE_SLUGS)} services")

    client = anthropic.Anthropic()
    print("Calling Claude Haiku to generate scenarios...")

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        messages=[{"role": "user", "content": build_prompt(runbooks, postmortems)}],
    )

    raw = message.content[0].text.strip()

    # Parse and validate
    try:
        scenarios = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON response: {e}", file=sys.stderr)
        print("Raw response (first 500 chars):", raw[:500], file=sys.stderr)
        sys.exit(1)

    if not isinstance(scenarios, list):
        print(f"Expected JSON array, got {type(scenarios).__name__}", file=sys.stderr)
        sys.exit(1)

    print(f"Generated {len(scenarios)} scenarios")

    output_path.write_text(json.dumps(scenarios, indent=2))
    print(f"Wrote {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic incident scenarios via Claude Haiku")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    generate(args.output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the generator**

Ensure `ANTHROPIC_API_KEY` is set, then:
```
python datasets/generate_synthetic_scenarios.py
```

Expected output:
```
Loaded 18 postmortems across 6 services
Calling Claude Haiku to generate scenarios...
Generated 18 scenarios
Wrote datasets/synthetic_scenarios.json
```

- [ ] **Step 3: Spot-check the output**

```
python -c "
import json
from pathlib import Path
scenarios = json.loads(Path('datasets/synthetic_scenarios.json').read_text())
print(f'{len(scenarios)} scenarios')
for s in scenarios:
    print(f\"  {s['scenario_id']} ({s['service']}) — {len(s['alerts'])} alerts\")
"
```

Confirm: 18 scenarios, all 6 services covered, 2–4 alerts each, mix of `datadog`/`sentry` platforms.

- [ ] **Step 4: Commit**

```bash
git add datasets/generate_synthetic_scenarios.py datasets/synthetic_scenarios.json
git commit -m "feat: add Haiku-powered synthetic scenario generator and fixture"
```

---

## Task 3: Write the seeder script

The seeder reads `synthetic_scenarios.json`, substitutes timestamps, and POSTs to the backend. We test the pure-Python logic (timestamp substitution, filtering) in isolation before writing the full script.

**Files:**
- Create: `tests/datasets/test_seed_synthetic_incidents.py`
- Create: `datasets/seed_synthetic_incidents.py`

- [ ] **Step 1: Create the test directory and init file**

```bash
mkdir -p tests/datasets
touch tests/datasets/__init__.py
```

- [ ] **Step 2: Write failing unit tests for the seeder helpers**

Create `tests/datasets/test_seed_synthetic_incidents.py`:

```python
"""Unit tests for seed_synthetic_incidents helpers."""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# The datasets/ directory is NOT on sys.path by default — add it
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "datasets"))

from seed_synthetic_incidents import substitute_timestamps, filter_scenarios, compute_base_time


@pytest.mark.unit
class TestSubstituteTimestamps:
    def test_replaces_ts0_in_string(self):
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        payload_str = '{"last_updated": "{{TS_0}}"}'
        result = substitute_timestamps(payload_str, base, num_alerts=1)
        data = json.loads(result)
        assert data["last_updated"] == "2026-01-01T12:00:00+00:00"

    def test_replaces_multiple_placeholders(self):
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        payload_str = '[{"t": "{{TS_0}}"}, {"t": "{{TS_1}}"}, {"t": "{{TS_2}}"}]'
        result = substitute_timestamps(payload_str, base, num_alerts=3)
        data = json.loads(result)
        assert data[0]["t"] == "2026-01-01T12:00:00+00:00"
        assert data[1]["t"] == "2026-01-01T12:01:00+00:00"
        assert data[2]["t"] == "2026-01-01T12:02:00+00:00"

    def test_offsets_are_60_seconds_apart(self):
        base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        payload_str = '{"a": "{{TS_0}}", "b": "{{TS_1}}"}'
        result = substitute_timestamps(payload_str, base, num_alerts=2)
        data = json.loads(result)
        t0 = datetime.fromisoformat(data["a"])
        t1 = datetime.fromisoformat(data["b"])
        assert (t1 - t0) == timedelta(seconds=60)


@pytest.mark.unit
class TestFilterScenarios:
    SCENARIOS = [
        {"scenario_id": "a", "service": "checkout-payments", "alerts": []},
        {"scenario_id": "b", "service": "auth-sessions", "alerts": []},
        {"scenario_id": "c", "service": "checkout-payments", "alerts": []},
    ]

    def test_no_filter_returns_all(self):
        result = filter_scenarios(self.SCENARIOS, service=None, count=None)
        assert len(result) == 3

    def test_service_filter(self):
        result = filter_scenarios(self.SCENARIOS, service="checkout-payments", count=None)
        assert len(result) == 2
        assert all(s["service"] == "checkout-payments" for s in result)

    def test_count_cap(self):
        result = filter_scenarios(self.SCENARIOS, service=None, count=2)
        assert len(result) == 2

    def test_service_and_count_combined(self):
        result = filter_scenarios(self.SCENARIOS, service="checkout-payments", count=1)
        assert len(result) == 1
        assert result[0]["service"] == "checkout-payments"


@pytest.mark.unit
class TestComputeBaseTime:
    def test_first_scenario_is_closest_to_now(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        t0 = compute_base_time(scenario_index=0, now=now)
        t1 = compute_base_time(scenario_index=1, now=now)
        assert t0 > t1

    def test_scenarios_35_minutes_apart(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        t0 = compute_base_time(scenario_index=0, now=now)
        t1 = compute_base_time(scenario_index=1, now=now)
        assert (t0 - t1) == timedelta(minutes=35)
```

- [ ] **Step 3: Run the tests to confirm they fail (module not found)**

```
pytest tests/datasets/test_seed_synthetic_incidents.py -v
```

Expected: `ModuleNotFoundError: No module named 'seed_synthetic_incidents'`

- [ ] **Step 4: Create `datasets/seed_synthetic_incidents.py`**

```python
#!/usr/bin/env python3
"""
Seed synthetic incidents into OpsRelay via webhook endpoints.

Reads datasets/synthetic_scenarios.json, injects live timestamps, and POSTs
each alert to /webhook/datadog or /webhook/sentry.

Requirements:
    - Backend running at --url (default http://localhost:8000)
    - SKIP_SIGNATURE_VERIFICATION=true in the backend environment

Usage:
    python datasets/seed_synthetic_incidents.py
    python datasets/seed_synthetic_incidents.py --service checkout-payments
    python datasets/seed_synthetic_incidents.py --count 3 --dry-run
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

SCENARIOS_FILE = Path("datasets/synthetic_scenarios.json")
DEFAULT_URL = "http://localhost:8000"


def compute_base_time(scenario_index: int, now: Optional[datetime] = None) -> datetime:
    """Base timestamp for a scenario: now minus (index * 35 minutes)."""
    if now is None:
        now = datetime.now(timezone.utc)
    return now - timedelta(minutes=scenario_index * 35)


def substitute_timestamps(payload_str: str, base_time: datetime, num_alerts: int) -> str:
    """Replace {{TS_N}} placeholders with ISO 8601 UTC timestamps."""
    for i in range(num_alerts):
        ts = (base_time + timedelta(seconds=i * 60)).isoformat()
        payload_str = payload_str.replace(f"{{{{TS_{i}}}}}", ts)
    return payload_str


def filter_scenarios(scenarios: list, service: Optional[str], count: Optional[int]) -> list:
    """Filter scenarios by service slug and/or cap by count."""
    if service:
        scenarios = [s for s in scenarios if s.get("service") == service]
    if count is not None:
        scenarios = scenarios[:count]
    return scenarios


def check_health(base_url: str) -> bool:
    try:
        resp = requests.get(f"{base_url}/health", timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def post_alert(base_url: str, platform: str, payload: dict) -> tuple[int, Optional[int]]:
    """POST alert to webhook endpoint. Returns (http_status, alert_id)."""
    try:
        resp = requests.post(
            f"{base_url}/webhook/{platform}",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        alert_id = None
        if resp.status_code == 200:
            alert_id = resp.json().get("alert_id")
        return resp.status_code, alert_id
    except requests.RequestException as e:
        print(f"  Connection error: {e}", file=sys.stderr)
        return 0, None


def seed(base_url: str, scenarios: list, dry_run: bool) -> tuple[int, int]:
    """Send all scenarios. Returns (alerts_sent, failures)."""
    now = datetime.now(timezone.utc)
    sent = 0
    failures = 0

    for idx, scenario in enumerate(scenarios):
        scenario_id = scenario["scenario_id"]
        alerts = scenario["alerts"]
        base_time = compute_base_time(idx, now)

        payload_str = json.dumps(alerts)
        payload_str = substitute_timestamps(payload_str, base_time, len(alerts))
        hydrated_alerts = json.loads(payload_str)

        for alert in hydrated_alerts:
            platform = alert["platform"]
            payload = alert["payload"]
            title = payload.get("title") or payload.get("data", {}).get("issue", {}).get("title", "?")

            if dry_run:
                print(f"[DRY] [{scenario_id}] {platform} | {title}")
                print(f"      curl -X POST {base_url}/webhook/{platform} \\")
                print(f"        -H 'Content-Type: application/json' \\")
                print(f"        -d '{json.dumps(payload)}'")
            else:
                status, alert_id = post_alert(base_url, platform, payload)
                status_str = f"HTTP {status} (id={alert_id})" if alert_id else f"HTTP {status}"
                print(f"[{scenario_id}] {platform} | {title[:60]} → {status_str}")
                if status == 200:
                    sent += 1
                else:
                    failures += 1

    return sent, failures


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed synthetic incidents into OpsRelay via webhooks",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Backend base URL")
    parser.add_argument("--service", default=None, help="Filter to one service slug")
    parser.add_argument("--count", type=int, default=None, help="Max scenarios to send")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without POSTing")
    args = parser.parse_args()

    # Load fixture
    if not SCENARIOS_FILE.exists():
        print(f"Fixture not found: {SCENARIOS_FILE}", file=sys.stderr)
        print("Run: python datasets/generate_synthetic_scenarios.py", file=sys.stderr)
        sys.exit(1)

    scenarios = json.loads(SCENARIOS_FILE.read_text())
    scenarios = filter_scenarios(scenarios, args.service, args.count)
    total_alerts = sum(len(s["alerts"]) for s in scenarios)

    print(f"Loaded {len(scenarios)} scenarios ({total_alerts} alerts)")

    if not args.dry_run:
        print(f"Checking backend health at {args.url}...")
        if not check_health(args.url):
            print(f"Backend not reachable at {args.url}", file=sys.stderr)
            print("Start with: docker-compose up backend celery-worker", file=sys.stderr)
            sys.exit(1)
        print("Backend healthy. Seeding...\n")

    sent, failures = seed(args.url, scenarios, args.dry_run)

    print(f"\nDone. Scenarios: {len(scenarios)} | Alerts sent: {sent} | Failures: {failures}")
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the unit tests — all should pass**

```
pytest tests/datasets/test_seed_synthetic_incidents.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 6: Smoke test with dry-run (no backend needed)**

```
python datasets/seed_synthetic_incidents.py --dry-run --count 2
```

Expected: prints `[DRY]` lines with curl commands, no HTTP calls made.

- [ ] **Step 7: Commit**

```bash
git add datasets/seed_synthetic_incidents.py tests/datasets/__init__.py tests/datasets/test_seed_synthetic_incidents.py
git commit -m "feat: add synthetic incident seeder with timestamp substitution and dry-run support"
```

---

## Task 4: End-to-end smoke test

Verify the full pipeline works with a live backend before calling the feature done.

- [ ] **Step 1: Start the stack**

```bash
docker-compose up --build -d
```

Wait ~30s for services to be ready.

- [ ] **Step 2: Seed a single service**

```bash
SKIP_SIGNATURE_VERIFICATION=true python datasets/seed_synthetic_incidents.py \
  --service checkout-payments
```

Expected: 3 scenarios, 6–12 alerts sent, all `HTTP 200`.

- [ ] **Step 3: Verify incidents were created**

```bash
docker-compose exec postgres psql -U user -d opsrelay \
  -c "SELECT id, title, status, severity FROM incidents ORDER BY created_at DESC LIMIT 5;"
```

Expected: 3 incidents (one per scenario), each with severity set and status `open`.

- [ ] **Step 4: Verify alerts are grouped correctly**

```bash
docker-compose exec postgres psql -U user -d opsrelay \
  -c "SELECT incident_id, COUNT(*) as alerts FROM alerts GROUP BY incident_id ORDER BY incident_id DESC LIMIT 5;"
```

Expected: each incident has 2–4 alerts grouped into it.

- [ ] **Step 5: Verify Celery processed the alerts**

```bash
docker-compose logs celery-worker --tail 30
```

Expected: log lines showing `ML classification`, `Extracted entities`, `Alert N processed successfully`.

- [ ] **Step 6: Final commit (if any fixups needed)**

```bash
git add -p
git commit -m "fix: <description of any fixups from e2e testing>"
```
