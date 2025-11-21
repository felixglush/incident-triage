#!/usr/bin/env python3
"""
Load sample data into OpsRelay via webhook endpoints.

This script reads sample_alerts.json and sends each alert to the backend
API via POST requests to the /webhook/datadog endpoint. The backend will
process alerts through Celery workers.

Usage:
    python datasets/load_sample_data.py              # Load all alerts
    python datasets/load_sample_data.py --count 10   # Load first 10
    python datasets/load_sample_data.py --wait 2     # 2 second delay

Requirements:
    - Backend API running on http://localhost:8000
    - SKIP_SIGNATURE_VERIFICATION=true in environment
    - Sample alerts generated via generate_alerts.py
"""
import json
import sys
import time
import argparse
import requests
from pathlib import Path
from typing import Optional

# Default paths
ALERTS_FILE = Path("datasets/sample_alerts.json")
API_URL = "http://localhost:8000"
WEBHOOK_ENDPOINT = f"{API_URL}/webhook/datadog"


def load_alerts_from_file(filepath: Path) -> list:
    """
    Load alerts from JSON file.

    Args:
        filepath: Path to sample_alerts.json

    Returns:
        List of alert dictionaries

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is invalid JSON
    """
    if not filepath.exists():
        raise FileNotFoundError(f"Alerts file not found: {filepath}")

    with open(filepath, "r") as f:
        alerts = json.load(f)

    if not isinstance(alerts, list):
        raise ValueError(f"Expected list of alerts, got {type(alerts).__name__}")

    return alerts


def check_api_health(url: str = API_URL) -> bool:
    """
    Check if backend API is running.

    Args:
        url: Base API URL

    Returns:
        True if API is healthy, False otherwise
    """
    try:
        response = requests.get(f"{url}/health", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def send_alert(alert: dict, endpoint: str = WEBHOOK_ENDPOINT) -> Optional[int]:
    """
    Send single alert to webhook endpoint.

    Args:
        alert: Alert dictionary to send
        endpoint: Webhook endpoint URL

    Returns:
        Alert ID if successful, None if failed

    The alert is sent as-is in Datadog format. The backend will:
    1. Validate and deduplicate by source + external_id
    2. Store in database
    3. Queue for Celery processing
    """
    try:
        response = requests.post(
            endpoint,
            json=alert,
            timeout=10,
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            data = response.json()
            alert_id = data.get("alert_id")
            return alert_id
        else:
            print(f"  ❌ Failed: {response.status_code}")
            if response.text:
                try:
                    error = response.json()
                    print(f"     Error: {error.get('detail', response.text)}")
                except json.JSONDecodeError:
                    print(f"     Error: {response.text[:100]}")
            return None

    except requests.RequestException as e:
        print(f"  ❌ Connection error: {e}")
        return None


def main():
    """Parse arguments and load sample data."""
    parser = argparse.ArgumentParser(
        description="Load sample alerts into OpsRelay",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--alerts",
        type=Path,
        default=ALERTS_FILE,
        help="Path to sample_alerts.json"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Only load first N alerts (default: all)"
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=0.5,
        help="Delay between requests (seconds)"
    )
    parser.add_argument(
        "--api",
        default=API_URL,
        help="Backend API base URL"
    )

    args = parser.parse_args()

    # Update endpoint with custom API URL
    endpoint = f"{args.api}/webhook/datadog"

    print("\n" + "=" * 60)
    print("OpsRelay Sample Data Loader")
    print("=" * 60)

    # Check API health
    print("\n1. Checking API health...")
    if not check_api_health(args.api):
        print(f"❌ API not responding at {args.api}")
        print("   Start backend with: docker-compose up backend")
        sys.exit(1)
    print(f"✓ API healthy at {args.api}")

    # Load alerts
    print("\n2. Loading sample alerts...")
    try:
        alerts = load_alerts_from_file(args.alerts)
        print(f"✓ Loaded {len(alerts)} alerts from {args.alerts}")
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        print(f"❌ Error loading alerts: {e}")
        print(f"   Generate with: python datasets/generate_alerts.py")
        sys.exit(1)

    # Limit count if specified
    if args.count:
        alerts = alerts[:args.count]
        print(f"✓ Processing first {args.count} alerts")

    # Send alerts
    print(f"\n3. Sending {len(alerts)} alerts to {endpoint}...")
    print(f"   (with {args.wait}s delay between requests)\n")

    successful = 0
    failed = 0
    start_time = time.time()

    try:
        for i, alert in enumerate(alerts, 1):
            # Show progress
            alert_id = alert.get("id", f"alert-{i}")
            title = alert.get("title", "Unknown")[:50]
            print(f"  [{i:3d}/{len(alerts)}] {alert_id:20s} - {title:50s}", end=" ")

            # Send alert
            api_id = send_alert(alert, endpoint)

            if api_id is not None:
                print(f"✓ (ID: {api_id})")
                successful += 1
            else:
                failed += 1

            # Delay between requests (don't hammer the API)
            if i < len(alerts):
                time.sleep(args.wait)

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        print(f"Sent {successful}/{len(alerts)} alerts before interruption")
        sys.exit(1)

    # Summary
    elapsed = time.time() - start_time
    rate = successful / elapsed if elapsed > 0 else 0

    print("\n" + "=" * 60)
    print("Results")
    print("=" * 60)
    print(f"Successful: {successful}/{len(alerts)}")
    print(f"Failed:     {failed}/{len(alerts)}")
    print(f"Time:       {elapsed:.1f} seconds")
    print(f"Rate:       {rate:.1f} alerts/second")

    # Next steps
    if successful > 0:
        print("\n✓ Sample data loaded successfully!")
        print("\nNext steps:")
        print("  1. Check alerts in database:")
        print("     docker-compose exec postgres psql -U user -d opsrelay \\")
        print("       -c \"SELECT COUNT(*) FROM alerts;\"")
        print("  2. Monitor Celery worker processing:")
        print("     docker-compose logs -f celery-worker")
        print("  3. View processed data:")
        print("     curl http://localhost:8000/incidents | jq '.'")
    else:
        print("\n❌ No alerts loaded successfully")
        print("\nTroubleshooting:")
        print("  - Verify backend is running: curl http://localhost:8000/health")
        print("  - Check backend logs: docker-compose logs backend")
        print("  - Verify sample_alerts.json exists")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
