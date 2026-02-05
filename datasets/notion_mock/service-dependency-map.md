# Service Dependency Map (Notion)

## Core Services
- api-gateway depends on auth-service and billing-service
- worker-service depends on queue and database

## Known Bottlenecks
- database connection pool saturation during peak deploys
- queue backlog during batch jobs

## Related Docs
- db-troubleshooting
- queue-ops
