#!/usr/bin/env python3
"""
Generate realistic sample alert data for testing.

This script creates sample Datadog-formatted alert payloads that can be used
for testing the webhook endpoints, Celery processing, and incident grouping
without needing real monitoring platform integrations.

Usage:
    python datasets/generate_alerts.py              # Generate 100 alerts
    python datasets/generate_alerts.py --count 50   # Generate 50 alerts
    python datasets/generate_alerts.py --output custom.json

Output:
    Generates sample_alerts.json with Datadog webhook format
"""
import json
import random
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Services that might trigger alerts
SERVICES = [
    "api-gateway",
    "auth-service",
    "payment-processor",
    "search-engine",
    "database",
    "cache-layer",
    "message-queue"
]

# Environments where services run
ENVIRONMENTS = [
    "production",
    "staging",
]

# Geographic regions for deployment
REGIONS = [
    "us-east-1",
    "us-west-2",
    "eu-west-1",
]

# Alert templates (Datadog format)
ALERT_TEMPLATES = [
    {
        "title": "High CPU usage on {service}",
        "message": "CPU usage has exceeded 80% for the last 5 minutes on {service} in {environment} ({region})",
        "severity": "warning",
        "priority": "warning"
    },
    {
        "title": "High memory usage on {service}",
        "message": "Memory usage is above 85% on {service}. Free memory: {memory_pct}%",
        "severity": "warning",
        "priority": "warning"
    },
    {
        "title": "Database connection pool exhausted",
        "message": "Connection pool for {service} database has reached maximum capacity. Available connections: 0/100",
        "severity": "error",
        "priority": "high"
    },
    {
        "title": "High request latency on {service}",
        "message": "P99 latency exceeded 5000ms on {service}. Current: {latency}ms",
        "severity": "error",
        "priority": "high"
    },
    {
        "title": "Service {service} is down",
        "message": "Health check failed for {service} in {region}. Service unreachable. Status: 503",
        "severity": "critical",
        "priority": "critical"
    },
    {
        "title": "Disk usage critical on {service}",
        "message": "Disk usage is {disk_usage}%. Available space: 100MB. Immediate action required.",
        "severity": "critical",
        "priority": "critical"
    },
    {
        "title": "High error rate on {service}",
        "message": "Error rate on {service} is {error_rate}%. Threshold: 5%",
        "severity": "error",
        "priority": "high"
    },
    {
        "title": "Database query timeout on {service}",
        "message": "Query execution time exceeded 30s on {service}. Slow queries detected.",
        "severity": "warning",
        "priority": "normal"
    },
]


def generate_alerts(count: int = 100) -> list:
    """
    Generate realistic sample alerts.

    Args:
        count: Number of alerts to generate

    Returns:
        List of alert dictionaries in Datadog webhook format

    Alert Format:
        - id: Unique identifier (datadog-alert-NNNN)
        - title: Alert title (formatted with service/env/region)
        - body: Alert message body
        - priority: Severity level (warning, normal, high, critical)
        - last_updated: ISO format timestamp
        - tags: Array of tags for filtering
        - alert_type: "metric_alert" (constant)
        - org: Organization info
    """
    alerts = []
    base_time = datetime.now(timezone.utc) - timedelta(days=7)

    for i in range(count):
        # Select random values for this alert
        template = random.choice(ALERT_TEMPLATES)
        service = random.choice(SERVICES)
        environment = random.choice(ENVIRONMENTS)
        region = random.choice(REGIONS)

        # Generate realistic metrics for the alert message
        cpu_usage = random.randint(80, 99)
        memory_pct = random.randint(85, 99)
        latency = random.randint(5000, 15000)
        disk_usage = random.randint(90, 99)
        error_rate = random.uniform(5.0, 25.0)

        # Format message with random values
        message = template["message"].format(
            service=service,
            environment=environment,
            region=region,
            memory_pct=memory_pct,
            latency=latency,
            disk_usage=disk_usage,
            error_rate=f"{error_rate:.1f}%"
        )

        # Create alert in Datadog format
        alert = {
            "id": f"datadog-alert-{1000 + i}",
            "title": template["title"].format(service=service),
            "body": message,
            "priority": template["priority"],
            "last_updated": (base_time + timedelta(hours=i % 168)).isoformat(),  # Spread over 7 days
            "tags": [
                f"service:{service}",
                f"env:{environment}",
                f"region:{region}",
                f"severity:{template['severity']}"
            ],
            "alert_type": "metric_alert",
            "org": {
                "id": "12345",
                "name": "Test Organization"
            }
        }

        alerts.append(alert)

    return alerts


def main():
    """Parse arguments and generate alerts."""
    parser = argparse.ArgumentParser(
        description="Generate realistic sample alert data for testing",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of alerts to generate"
    )
    parser.add_argument(
        "--output",
        default="datasets/sample_alerts.json",
        help="Output file path"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility"
    )

    args = parser.parse_args()

    # Set random seed if provided (for reproducibility)
    if args.seed is not None:
        random.seed(args.seed)
        print(f"Using random seed: {args.seed}")

    # Generate alerts
    print(f"Generating {args.count} sample alerts...")
    alerts = generate_alerts(args.count)

    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to file
    with open(output_path, "w") as f:
        json.dump(alerts, f, indent=2)

    print(f"✓ Generated {len(alerts)} alerts")
    print(f"✓ Saved to {output_path}")

    # Print summary
    severity_counts = {}
    service_counts = {}

    for alert in alerts:
        # Count by severity
        tags = alert.get("tags", [])
        for tag in tags:
            if tag.startswith("severity:"):
                severity = tag.split(":", 1)[1]
                severity_counts[severity] = severity_counts.get(severity, 0) + 1
            elif tag.startswith("service:"):
                service = tag.split(":", 1)[1]
                service_counts[service] = service_counts.get(service, 0) + 1

    print("\nSummary:")
    print("  By Severity:")
    for severity, count in sorted(severity_counts.items()):
        print(f"    {severity}: {count}")

    print("  By Service (top 5):")
    for service, count in sorted(service_counts.items(), key=lambda x: -x[1])[:5]:
        print(f"    {service}: {count}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
