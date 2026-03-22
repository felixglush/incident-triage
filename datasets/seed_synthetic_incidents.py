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


def post_alert(base_url: str, platform: str, payload: dict) -> tuple:
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


def seed(base_url: str, scenarios: list, dry_run: bool) -> tuple:
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
                print(f"[{scenario_id}] {platform} | {title[:60]} -> {status_str}")
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
