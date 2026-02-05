# Auth Outage

## Symptoms
- Login failures spike
- Auth token validation errors
- Requests fail with 401/403 across services

## Immediate Actions
1. Check auth service health and dependencies.
2. Validate cert/keys rotation status.
3. Fail open for low-risk endpoints if policy allows.

## Investigation
- Inspect auth logs for validation errors.
- Verify token issuer and audience configs.
- Check clock drift between services.

## Resolution
- Roll back auth config or redeploy auth service.
- Restore key material and sync clocks.

## Verification
- Auth success rate returns to normal.
- 401/403 errors drop to baseline.
