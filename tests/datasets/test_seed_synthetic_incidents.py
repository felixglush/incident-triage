"""Unit tests for seed_synthetic_incidents helpers."""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

# datasets/ is not on sys.path by default — mirror how conftest.py handles backend/
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
