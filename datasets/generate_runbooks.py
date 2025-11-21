#!/usr/bin/env python3
"""
Generate sample runbook content for RAG system (Phase 2).

Runbooks are operational procedures that help on-call engineers resolve
incidents. This script creates sample runbooks that can be stored in the
database for semantic search via the RAG system.

Usage:
    python datasets/generate_runbooks.py              # Generate runbooks
    python datasets/generate_runbooks.py --output custom.json

Output:
    Generates sample_runbooks.json with runbook content and chunks
"""
import json
import argparse
import sys
from pathlib import Path

# Sample runbooks with operational procedures
RUNBOOKS = [
    {
        "title": "Restarting the API Gateway",
        "category": "deployment",
        "tags": ["api-gateway", "kubernetes", "rollout", "restart"],
        "content": """
## Overview
The API Gateway is the entry point for all client requests. Restarting it safely requires coordination to avoid dropping in-flight requests.

## Prerequisites
- kubectl configured with cluster access
- Write permissions on production-api namespace

## Procedure

### 1. Check Current Status
```bash
kubectl get pods -n production-api | grep api-gateway
kubectl get deployment api-gateway -n production-api -o wide
```

### 2. Check Pending Requests
```bash
kubectl logs -n production-api -l app=api-gateway --tail=50
```

### 3. Initiate Rolling Restart
The rolling restart ensures that some API gateway instances are always available to handle traffic.
```bash
kubectl rollout restart deployment/api-gateway -n production-api
```

### 4. Monitor the Restart
```bash
kubectl rollout status deployment/api-gateway -n production-api --timeout=5m
```

### 5. Verify Health
```bash
curl https://api.example.com/health
```

## Expected Timeline
- Rolling restart typically takes 2-3 minutes
- During restart, traffic is automatically routed to healthy pods
- No manual requests need to be drained

## Troubleshooting

**If health checks fail after restart:**
- Check pod logs: `kubectl logs -n production-api <pod-name>`
- Check environment variables: `kubectl describe pod <pod-name>`
- Rollback restart: `kubectl rollout undo deployment/api-gateway -n production-api`

**If restart appears stuck:**
- Check resource limits: `kubectl top pod -n production-api`
- Check node status: `kubectl get nodes`
- Manually delete pod: `kubectl delete pod <pod-name> -n production-api`

## Prevention
- Monitor API gateway memory usage
- Review recent deployments before restart
- Ensure sufficient cluster capacity
"""
    },
    {
        "title": "Database Connection Pool Saturation",
        "category": "database",
        "tags": ["database", "postgresql", "connections", "pool", "troubleshooting"],
        "content": """
## Overview
When applications exhaust the database connection pool, new connections fail and requests timeout. This is a critical issue that requires immediate action.

## Symptoms
- "connection pool exhausted" errors in application logs
- Timeout errors in client requests
- Database appears to be accepting new connections but application can't use them

## Root Causes
- Application not closing connections properly (connection leak)
- Queries taking longer than expected, holding connections
- Sudden traffic spike exceeding pool capacity
- Database connection configuration too small

## Diagnosis

### 1. Check Connection Count
```sql
SELECT count(*) FROM pg_stat_activity;
```

### 2. Identify Active Connections
```sql
SELECT
  datname,
  state,
  count(*)
FROM pg_stat_activity
GROUP BY datname, state;
```

### 3. Find Long-Running Queries
```sql
SELECT
  pid,
  usename,
  query_start,
  now() - query_start as duration,
  query
FROM pg_stat_activity
WHERE state = 'active'
  AND query_start < now() - interval '5 minutes'
ORDER BY duration DESC;
```

### 4. Check for Idle Connections
```sql
SELECT
  pid,
  usename,
  state,
  state_change,
  application_name
FROM pg_stat_activity
WHERE state = 'idle'
ORDER BY state_change;
```

## Immediate Relief (Temporary)

### Option 1: Kill Idle Connections
```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle'
  AND state_change < now() - interval '30 minutes';
```

### Option 2: Kill Long-Running Queries (Use Caution)
```sql
-- First identify the problem query
SELECT pid, query FROM pg_stat_activity WHERE duration > interval '10 minutes';

-- Then terminate it
SELECT pg_terminate_backend(12345);  -- Replace with actual PID
```

### Option 3: Restart Application
Restarting the application service will reset all connections in the pool:
```bash
kubectl rollout restart deployment/api-service -n production
```

## Long-Term Solutions

### 1. Optimize Queries
- Check slow query log
- Add indexes for frequently queried columns
- Analyze execution plans: `EXPLAIN ANALYZE <query>`

### 2. Increase Pool Size
In application configuration:
```python
pool_size=20  # Increase from default 10
max_overflow=10  # Allow temporary overflow
```

### 3. Implement Connection Pooling
Use pgBouncer for application-level connection pooling:
```
[databases]
myapp = host=db.internal port=5432 dbname=myapp
```

### 4. Monitor Connection Usage
Set up alerts for:
- Total connections > 80% of max
- Idle connections > 50
- Query duration > 10 seconds

## Prevention

1. **Connection Monitoring**
   - Alert when connections exceed 70% of pool
   - Track connection trends over time

2. **Query Optimization**
   - Regularly review slow queries
   - Maintain indexes on join columns

3. **Load Testing**
   - Test with expected peak traffic
   - Verify connection pool configuration

4. **Application Configuration**
   - Set appropriate pool sizes for workload
   - Configure connection timeouts
   - Implement graceful degradation
"""
    },
    {
        "title": "High CPU Usage Incident Response",
        "category": "performance",
        "tags": ["cpu", "performance", "throttling", "scaling"],
        "content": """
## Overview
High CPU usage indicates that application/service is compute-bound and unable to handle current load.

## Immediate Actions (0-5 minutes)

### 1. Identify Which Service/Host
```bash
# Host-level CPU
top -b -n1 | head -15

# Kubernetes pod CPU
kubectl top pods --all-namespaces | sort --reverse --key 3 --numeric
```

### 2. Check for Runaway Process
```bash
# Show processes sorted by CPU
ps aux | sort -rnk 3,3 | head -20

# In Kubernetes
kubectl top pod -n <namespace> --sort-by=cpu
```

### 3. Assess Impact
- Check if requests are still being processed
- Monitor error rates
- Check if other services are affected

## Short-Term Mitigation (5-30 minutes)

### Option 1: Scale Up Horizontally
```bash
# Kubernetes - increase replicas
kubectl scale deployment <app> --replicas=5 -n <namespace>

# This spreads load across more pods
```

### Option 2: Identify Resource-Intensive Operations
```bash
# In application logs, look for operations taking > 5s
grep "duration_ms" application.log | sort -rn | head -20
```

### Option 3: Throttle Non-Critical Work
- Disable background jobs
- Reduce batch sizes
- Pause scheduled tasks

## Root Cause Analysis (30+ minutes)

### 1. Check Recent Deployments
```bash
kubectl rollout history deployment/<app> -n <namespace>
```

### 2. Monitor CPU Metrics Over Time
```bash
# Prometheus query
rate(process_cpu_seconds_total[5m])
```

### 3. Profile the Application
- Use flame graphs
- Check for hot loops
- Analyze memory allocation patterns

## Long-Term Solutions

### 1. Optimize Code
- Profile application
- Optimize hot paths
- Reduce memory allocations

### 2. Improve Caching
- Cache frequently computed values
- Use Redis for distributed cache
- Implement cache warming

### 3. Adjust Resource Limits
```yaml
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi
```

### 4. Implement Autoscaling
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: myapp
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```
"""
    },
]


def chunk_runbook(runbook: dict, chunk_size: int = 500) -> list:
    """
    Split runbook content into semantic chunks.

    Chunks are split by logical sections (separated by blank lines).
    This allows better retrieval in RAG system.

    Args:
        runbook: Runbook dictionary with 'title' and 'content'
        chunk_size: Maximum characters per chunk

    Returns:
        List of chunk dictionaries with title, content, and source
    """
    content = runbook["content"].strip()
    chunks = []

    # Split by headers (lines starting with #)
    sections = []
    current_section = ""

    for line in content.split("\n"):
        if line.startswith("##") and current_section:
            sections.append(current_section)
            current_section = line + "\n"
        else:
            current_section += line + "\n"

    if current_section:
        sections.append(current_section)

    # Combine sections into chunks respecting chunk_size
    current_chunk = ""
    for section in sections:
        if len(current_chunk) + len(section) > chunk_size and current_chunk:
            # Chunk is full, save it
            chunks.append({
                "content": current_chunk.strip(),
                "source": f"{runbook['title']} - Part {len(chunks) + 1}"
            })
            current_chunk = section
        else:
            current_chunk += section

    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append({
            "content": current_chunk.strip(),
            "source": f"{runbook['title']} - Part {len(chunks) + 1}"
        })

    return chunks


def generate_runbook_data(include_chunks: bool = True) -> list:
    """
    Generate runbook data with optional chunking.

    Args:
        include_chunks: If True, split each runbook into chunks

    Returns:
        List of runbook dictionaries
    """
    runbooks = []

    for runbook in RUNBOOKS:
        runbook_data = {
            "id": runbook["title"].lower().replace(" ", "-"),
            "title": runbook["title"],
            "category": runbook.get("category", "general"),
            "tags": runbook.get("tags", []),
            "content": runbook["content"].strip(),
        }

        if include_chunks:
            runbook_data["chunks"] = chunk_runbook(runbook)

        runbooks.append(runbook_data)

    return runbooks


def main():
    """Parse arguments and generate runbooks."""
    parser = argparse.ArgumentParser(
        description="Generate sample runbook content for RAG system",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--output",
        default="datasets/sample_runbooks.json",
        help="Output file path"
    )
    parser.add_argument(
        "--no-chunks",
        action="store_true",
        help="Don't generate chunks (keep full content only)"
    )

    args = parser.parse_args()

    # Generate runbooks
    print(f"Generating runbooks...")
    runbooks = generate_runbook_data(include_chunks=not args.no_chunks)

    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to file
    with open(output_path, "w") as f:
        json.dump(runbooks, f, indent=2)

    print(f"✓ Generated {len(runbooks)} runbooks")
    print(f"✓ Saved to {output_path}")

    # Print summary
    total_chunks = sum(len(r.get("chunks", [])) for r in runbooks)
    total_chars = sum(len(r["content"]) for r in runbooks)

    print("\nSummary:")
    print(f"  Runbooks: {len(runbooks)}")
    if not args.no_chunks:
        print(f"  Total chunks: {total_chunks}")
    print(f"  Total characters: {total_chars:,}")

    print("\nRunbooks generated:")
    for runbook in runbooks:
        category = runbook.get("category", "general")
        chunks = len(runbook.get("chunks", []))
        if not args.no_chunks:
            print(f"  - {runbook['title']} ({category}) - {chunks} chunks")
        else:
            print(f"  - {runbook['title']} ({category})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
