#!/usr/bin/env python3
"""
Validate the synthetic incident scenarios fixture.

Checks that datasets/synthetic_scenarios.json is present and well-formed:
- Required top-level fields per scenario
- Valid platform values (datadog, sentry)
- Required payload fields per platform
- Sequential {{TS_N}} timestamp placeholders present in each scenario

Usage:
    python datasets/validate_synthetic_scenarios.py
"""
import json
import re
import sys
from pathlib import Path

OUTPUT = Path("datasets/synthetic_scenarios.json")

REQUIRED_SCENARIO_FIELDS = {"scenario_id", "service", "postmortem_ref", "description", "alerts"}
VALID_PLATFORMS = {"datadog", "sentry"}

REQUIRED_DATADOG_FIELDS = {"id", "title", "body", "priority", "last_updated", "tags"}
VALID_DATADOG_PRIORITIES = {"critical", "high", "medium", "low"}


def check_datadog_payload(payload: dict, ctx: str) -> list[str]:
    errors = []
    missing = REQUIRED_DATADOG_FIELDS - payload.keys()
    if missing:
        errors.append(f"{ctx}: missing datadog fields: {sorted(missing)}")
    if "priority" in payload and payload["priority"] not in VALID_DATADOG_PRIORITIES:
        errors.append(f"{ctx}: invalid priority '{payload['priority']}'")
    if "tags" in payload and not isinstance(payload["tags"], list):
        errors.append(f"{ctx}: 'tags' must be a list")
    return errors


def check_sentry_payload(payload: dict, ctx: str) -> list[str]:
    errors = []
    if "action" not in payload:
        errors.append(f"{ctx}: missing sentry field 'action'")
    issue = payload.get("data", {}).get("issue", {})
    if not issue:
        errors.append(f"{ctx}: missing data.issue")
    else:
        for field in ("id", "title", "level", "lastSeen", "project"):
            if field not in issue:
                errors.append(f"{ctx}: missing data.issue.{field}")
        project = issue.get("project", {})
        for field in ("id", "name", "slug", "platform"):
            if field not in project:
                errors.append(f"{ctx}: missing data.issue.project.{field}")
    return errors


def check_timestamps(scenario_str: str, num_alerts: int, scenario_id: str) -> list[str]:
    errors = []
    for i in range(num_alerts):
        placeholder = f"{{{{TS_{i}}}}}"
        if placeholder not in scenario_str:
            errors.append(f"{scenario_id}: missing timestamp placeholder {{{{TS_{i}}}}}")
    # Warn if there are placeholders beyond the expected range
    extra = re.findall(r"\{\{TS_(\d+)\}\}", scenario_str)
    for idx in extra:
        if int(idx) >= num_alerts:
            errors.append(f"{scenario_id}: unexpected placeholder {{{{TS_{idx}}}}} (only {num_alerts} alerts)")
    return errors


def validate(scenarios: list) -> list[str]:
    errors = []
    seen_ids = set()

    for i, scenario in enumerate(scenarios):
        sid = scenario.get("scenario_id", f"<scenario[{i}]>")
        ctx_prefix = sid

        # Check for duplicate scenario_id
        if sid in seen_ids:
            errors.append(f"{ctx_prefix}: duplicate scenario_id")
        seen_ids.add(sid)

        # Required top-level fields
        missing = REQUIRED_SCENARIO_FIELDS - scenario.keys()
        if missing:
            errors.append(f"{ctx_prefix}: missing fields: {sorted(missing)}")
            continue

        alerts = scenario["alerts"]
        if not isinstance(alerts, list) or len(alerts) == 0:
            errors.append(f"{ctx_prefix}: 'alerts' must be a non-empty list")
            continue

        # Check timestamp placeholders across entire scenario payload
        scenario_str = json.dumps(alerts)
        errors.extend(check_timestamps(scenario_str, len(alerts), sid))

        for j, alert in enumerate(alerts):
            ctx = f"{ctx_prefix}/alert[{j}]"

            if "platform" not in alert:
                errors.append(f"{ctx}: missing 'platform'")
                continue
            if "payload" not in alert:
                errors.append(f"{ctx}: missing 'payload'")
                continue

            platform = alert["platform"]
            payload = alert["payload"]

            if platform not in VALID_PLATFORMS:
                errors.append(f"{ctx}: unknown platform '{platform}' (expected: {sorted(VALID_PLATFORMS)})")
            elif platform == "datadog":
                errors.extend(check_datadog_payload(payload, ctx))
            elif platform == "sentry":
                errors.extend(check_sentry_payload(payload, ctx))

    return errors


def main() -> None:
    if not OUTPUT.exists():
        print(f"Fixture not found: {OUTPUT}", file=sys.stderr)
        print(
            "Regenerate by asking Claude Code:\n"
            '  "Regenerate datasets/synthetic_scenarios.json from the notion_mock runbooks and postmortems"',
            file=sys.stderr,
        )
        sys.exit(1)

    scenarios = json.loads(OUTPUT.read_text())
    print(f"{len(scenarios)} scenarios in {OUTPUT}\n")

    services: dict[str, int] = {}
    for s in scenarios:
        svc = s.get("service", "?")
        services[svc] = services.get(svc, 0) + 1
        platforms = [a.get("platform", "?") for a in s.get("alerts", [])]
        print(f"  {s.get('scenario_id', '?')} ({svc}) — {len(s.get('alerts', []))} alerts: {platforms}")

    print()
    print("Services:", dict(sorted(services.items())))

    errors = validate(scenarios)
    if errors:
        print(f"\n{len(errors)} validation error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\nAll {len(scenarios)} scenarios valid.")


if __name__ == "__main__":
    main()
