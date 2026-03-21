# Auth & Sessions Runbook

## Service Overview

The Auth & Sessions service is the identity and authentication backbone of the ecommerce platform. It manages user registration, login, multi-factor authentication, OAuth federation, and session lifecycle.

**Architecture:**
- **auth-service**: Kubernetes Deployment (4 replicas, 2 CPU / 2 Gi memory per pod) running Python/FastAPI
- **PostgreSQL**: Primary data store for user accounts, credentials (bcrypt-hashed passwords), OAuth provider links, MFA enrollment
- **Redis**: Two separate instances:
  - Session store (sessions, max TTL 7 days, `noeviction` → `allkeys-lru` on memory pressure)
  - Rate-limit counter store (per-IP / per-user request counters, TTL 1 minute)
- **Vault**: Secure key management for JWT signing private key (RSA-2048), rotated monthly by ops team
- **OAuth Providers**: Google (accounts.google.com) and Apple (appleid.apple.com) as external federated identity sources

**JWT Token Flow:**
- Auth-service signs tokens with RSA-2048 private key (HS256 was deprecated in 2023)
- All outbound JWTs use RS256 signature, valid for 1 hour (refresh token extends to 30 days)
- Public key served via `GET /auth/.well-known/jwks.json` (cached 5 minutes client-side, CORS enabled)
- Other services validate tokens using the JWKS endpoint before accepting API calls

**Session Management:**
- Opaque session tokens (128-bit random, base64-encoded) generated on successful login
- Stored in Redis: `session:{token_hash}` → `{"user_id": "...", "created_at": "...", "last_activity": "...", "ip": "...", "user_agent": "..."}`
- Session TTL 7 days (hardening: idle timeout at 24 hours in 2025 roadmap)
- Session invalidation on password reset, logout, suspicious activity (geo-velocity check)

**SLOs:**
| Metric | SLO |
|--------|-----|
| Login success rate | 99.95% |
| Session validation P99 latency | <20ms (Redis read) |
| JWT token signing P99 latency | <50ms |
| Auth availability (uptime) | 99.99% (52 minutes/month) |
| OAuth provider fallback activation time | <5 minutes |

**Owner:** Identity Platform team (Slack: #identity-platform, PagerDuty: identity-platform-oncall)

---

## Recorded Incidents

### INC-2024-0156 — Redis Session Store Memory Exhaustion

**Severity:** P0 | **Date:** 2024-07-04 14:22–14:48 UTC | **Duration:** 26 minutes | **Users Affected:** 100% new login attempts

**Description:**
A UX change deployed 3 weeks prior extended user session TTL from 7 days to 30 days in an attempt to reduce re-authentication friction. Over the following weeks, the active session count in Redis grew from ~2M sessions (≈6GB memory) to ~11M sessions. At 14:22 UTC, the session Redis instance hit its configured `maxmemory` limit of 8GB. The eviction policy was set to `noeviction`, which means new write commands are rejected with an OOM error rather than evicting old entries.

All new login attempts failed with error `OOM command not allowed when used memory > 'maxmemory'`. Existing sessions (read/validation) continued to work. The automated alert `redis.login_error_rate > 50%` fired at 14:24 UTC.

**Root Cause:**
1. TTL extension was not capacity-planned; team did not calculate memory impact (11M sessions × ~1KB per session ≈ 11GB)
2. Single session Redis instance serving both active sessions and rate-limit counters created resource contention
3. `noeviction` policy meant no automatic recovery; manual intervention required
4. No alerts on Redis memory utilization % (only on error rate downstream)

**Impact:**
- 100% of new logins failed for 26 minutes
- Estimated 18k failed login attempts (assuming 700 req/s baseline)
- No data loss (sessions were never corrupted, only new writes rejected)
- Existing users with valid sessions unaffected (reads still worked)

**Resolution Steps:**

1. **Acknowledge incident and gather context (1 minute):**
   ```bash
   # SSH to session Redis pod
   kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli
   # Check memory
   > INFO memory
   # Output: used_memory_human:8.00G, maxmemory:8G, maxmemory_policy:noeviction
   ```

2. **Immediately switch eviction policy (2 minutes):**
   ```bash
   # Update policy to LRU (least-recently-used) to allow eviction
   kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli CONFIG SET maxmemory-policy allkeys-lru
   # Verify
   kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli CONFIG GET maxmemory-policy
   # Output: 1) "maxmemory-policy"
   #         2) "allkeys-lru"
   ```
   This immediately freed ~3.2GB by evicting oldest sessions; memory usage dropped to 5.1GB.

3. **Increase headroom to prevent immediate re-trigger (2 minutes):**
   ```bash
   kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli CONFIG SET maxmemory 16gb
   kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli CONFIG REWRITE
   # Verify
   kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli CONFIG GET maxmemory
   # Output: 1) "maxmemory"
   #         2) "16gb"
   ```

4. **Verify login success recovery (3 minutes):**
   ```bash
   # Watch error rate metric recovery
   kubectl logs deployment/auth-service -n ecommerce --since=5m | grep -c "login_success"
   # Should see 100+ success logs within next minute
   # Check Prometheus dashboard: login_error_rate metric should drop below 1%
   ```

5. **Revert UX change (10 minutes):**
   ```bash
   # Revert session TTL back to 7 days
   kubectl set env deployment/auth-service SESSION_TTL_DAYS=7 -n ecommerce
   kubectl rollout restart deployment/auth-service -n ecommerce
   kubectl rollout status deployment/auth-service -n ecommerce
   ```

6. **Create permanent Redis split (planning):**
   - Schedule separate Redis instance for rate-limit counters (ephemeral, can use volatile-lru policy)
   - Document in architecture decision record (ADR-2024-08: Redis Storage Tiers)

**Follow-up Actions:**
- [ ] Add Redis memory alert at 75% utilization (firing before reaching maxmemory)
- [ ] Add Redis eviction rate alert (TOFILL evictions_per_sec > 1000)
- [ ] Capacity-plan all future TTL changes: request Security + Infra review
- [ ] Implement separate Redis instances: session (persistent, allkeys-lru) vs. rate-limit (ephemeral, volatile-lru)
- [ ] Document session memory formula: N sessions × 1.2 KB avg = GB needed

---

### INC-2024-0302 — JWT Signing Key Rotation Causing Mass Logout

**Severity:** P1 | **Date:** 2024-10-30 02:00–02:21 UTC | **Duration:** 21 minutes | **Users Affected:** ~800k existing sessions invalidated

**Description:**
A scheduled Vault key rotation job ran at 02:00 UTC, rotating the RSA-2048 private key used by auth-service to sign JWT tokens. The rotation process updated the key in Vault but did NOT trigger a restart of the auth-service pods. As a result:

1. All new JWTs issued after 02:00 were signed with the new private key
2. The JWKS endpoint (`/.well-known/jwks.json`) was configured to cache responses for 5 minutes; it continued serving the old public key
3. All downstream services validated incoming JWTs using the cached old public key
4. For 4 minutes (02:00–02:04), any JWT signed with the new key was rejected as invalid signature

Additionally, upon discovering the issue, the on-call engineer manually restarted auth-service to force it to load the new key from Vault. During this restart, the session validation logic incorrectly checked the JWT signing key version against the current signing key version in memory. All existing sessions (which held JWTs signed with the old key) were suddenly invalid.

This cascading failure resulted in a mass logout: 800k active users found themselves logged out within 90 seconds of the restart.

**Root Cause:**
1. Vault key rotation was not coordinated with auth-service restart (manual step missing from automation)
2. JWKS cache TTL (5 minutes) was too long for key rotation events (should be <1 minute or event-driven)
3. Session validation logic incorrectly tied session validity to the current in-memory signing key version (should be decoupled)
4. No graceful key rotation window; new and old keys cannot coexist in acceptance period

**Impact:**
- 4 minutes of new login failures (JWT signed with new key rejected by old public key)
- 800k users logged out within 90 seconds of auth-service restart
- High support ticket volume (session invalidation generates "you were logged out" complaints from users)
- Customer trust impact; caused several high-profile merchants to open incident tickets

**Resolution Steps:**

1. **Declare incident and prepare rollback (2 minutes):**
   ```bash
   # Open incident in PagerDuty; page Identity Platform + Security
   # Assess: are existing sessions truly invalid, or is it a validation bug?
   kubectl logs deployment/auth-service -n ecommerce --tail=100 | grep "session.*invalid"
   # Observation: every session validation is failing with "signing_key_version_mismatch"
   ```

2. **Restore old signing key from Vault backup (3 minutes):**
   ```bash
   # Check Vault key history
   vault kv metadata get secret/jwt-signing-key
   # List versions
   vault kv list secret/jwt-signing-key

   # Retrieve old key (version 14, prior to rotation)
   vault kv get -version=14 -field=private_key secret/jwt-signing-key > /tmp/jwt-old.key

   # Verify it's valid PEM format
   openssl rsa -in /tmp/jwt-old.key -check -noout
   # Output: RSA key ok
   ```

3. **Restart auth-service with old key (3 minutes):**
   ```bash
   # Update deployment to mount old key temporarily
   kubectl create secret generic jwt-signing-key-rollback --from-file=/tmp/jwt-old.key -n ecommerce --dry-run=client -o yaml | kubectl apply -f -

   # Update auth-service to use fallback key
   kubectl set env deployment/auth-service JWT_KEY_SOURCE=rollback -n ecommerce
   kubectl rollout restart deployment/auth-service -n ecommerce
   kubectl rollout status deployment/auth-service -n ecommerce
   ```

4. **Verify sessions are now valid (2 minutes):**
   ```bash
   # Check session validation logs
   kubectl logs deployment/auth-service -n ecommerce --since=2m | grep -c "session_valid"
   # Should see hundreds of valid sessions per second

   # Check error rate
   kubectl logs deployment/auth-service -n ecommerce --since=2m | grep "session_invalid" | wc -l
   # Should drop to near 0
   ```

5. **Revert to current key with corrected validation logic (10 minutes):**
   ```bash
   # Do NOT immediately switch back to new key; first patch the validation logic
   # Deploy hotfix: remove signing_key_version check from session validation
   # Git ref: git checkout hotfix/session-validation-decouple
   # Build and deploy
   kubectl set image deployment/auth-service auth-service=ecommerce/auth-service:hotfix-session-decouple-20241030 -n ecommerce
   kubectl rollout status deployment/auth-service -n ecommerce
   ```

6. **Now switch to new key with dual-key window (5 minutes):**
   ```bash
   kubectl set env deployment/auth-service JWT_KEY_SOURCE=current JWT_DUAL_KEY_WINDOW_MINUTES=15 -n ecommerce
   kubectl rollout restart deployment/auth-service -n ecommerce
   kubectl rollout status deployment/auth-service -n ecommerce

   # Verify both old and new keys are accepted
   curl -s https://auth.ecommerce.internal/.well-known/jwks.json | jq '.keys | length'
   # Output: 2 (both old and new key IDs present)
   ```

**Follow-up Actions:**
- [ ] Implement dual-key acceptance window (15 minutes) for all key rotations going forward
- [ ] Decouple session validity from signing key version in code (remove `session.signing_key_version` check)
- [ ] Reduce JWKS cache TTL from 5 minutes to 30 seconds
- [ ] Add pre-rotation checklist: notify on-call, prep rollback plan, coordinate timing outside traffic peaks
- [ ] Automate key rotation: Vault rotation should trigger auth-service reload, not restart (SIGHUP handler)
- [ ] Add dual-key acceptance unit test with old/new key mix
- [ ] Implement key rotation event webhook from Vault to auth-service

---

### INC-2025-0033 — OAuth Provider Outage Locking Out Social Login Users

**Severity:** P2 | **Date:** 2025-02-18 06:47–07:34 UTC | **Duration:** 47 minutes | **Users Affected:** ~31% of user base (Google OAuth users)

**Description:**
Google's OAuth token endpoint (`accounts.google.com/o/oauth2/token`) began returning HTTP 503 Service Unavailable at 06:47 UTC. This is the endpoint used by auth-service to exchange authorization codes for ID tokens during the OAuth callback flow. All users attempting to authenticate via Google OAuth were blocked at the "Please wait" screen and eventually timed out after 30 seconds.

~31% of the active user base uses Google OAuth as their primary login method. Support received 8x spike in "can't log in" tickets within 5 minutes.

Email/password and Apple OAuth logins were unaffected.

**Root Cause:**
- Google's infrastructure incident (not disclosed publicly until 08:15 UTC status page update)
- No fallback mechanism in place; auth-service would hang and timeout waiting for Google's response
- No circuit breaker pattern; every request attempted to reach Google (adding latency)

**Impact:**
- 47 minutes of Google OAuth login unavailability
- ~18k attempted Google logins blocked (estimated at 6.4 req/s × 47 min × 60 s)
- 8x support ticket spike (800+ tickets)
- Some users attempted to reset passwords thinking they'd lost access
- Brand reputation risk; customers questioned platform reliability

**Resolution Steps:**

1. **Detect and confirm root cause (3 minutes):**
   ```bash
   # Check auth-service logs for OAuth errors
   kubectl logs deployment/auth-service -n ecommerce --since=10m | grep -i google | tail -20
   # Output: error: failed to exchange authorization code with Google: 503 Service Unavailable, err=timeout after 30s

   # Ping Google OAuth endpoint
   curl -I https://accounts.google.com/o/oauth2/token
   # HTTP/1.1 503 Service Unavailable

   # Check Google Cloud Status Page (https://status.cloud.google.com)
   # Confirmed: Google Identity Platform incident active, no ETA
   ```

2. **Enable magic link fallback (2 minutes):**
   ```bash
   # Deploy feature flag to allow email magic link bypass
   kubectl set env deployment/auth-service OAUTH_FALLBACK_MODE=email_magic_link -n ecommerce
   kubectl rollout restart deployment/auth-service -n ecommerce
   kubectl rollout status deployment/auth-service -n ecommerce
   ```

3. **Update login UI to show fallback option (1 minute, frontend deployed separately):**
   ```bash
   # Frontend team deploys change showing:
   # "Google login temporarily unavailable. Continue with your email instead."
   # + [Send magic link] button
   # This was pre-built but behind feature flag
   ```

4. **Communicate to users and support (2 minutes):**
   ```bash
   # Post to status page (status.ecommerce.io)
   # "Investigating authentication delays for Google OAuth users; email login available as fallback"

   # Notify support team in Slack
   # "Google OAuth is down (their issue). Users can log in with magic link. Guide customers to email option."
   ```

5. **Monitor fallback adoption (ongoing during incident):**
   ```bash
   # Watch magic link login success
   kubectl logs deployment/auth-service -n ecommerce --follow | grep magic_link_success
   # Observe: 200–300 magic link logins per minute (users switching to fallback)

   # Check email send queue
   # SELECT COUNT(*) FROM email_queue WHERE type='magic_link' AND created_at > now() - interval '5 min'
   # Output: ~1500 emails sent in last 5 minutes
   ```

6. **Disable fallback once Google recovers (1 minute):**
   ```bash
   # Wait for Google status page to show resolved (07:34 UTC)
   kubectl set env deployment/auth-service OAUTH_FALLBACK_MODE=none -n ecommerce
   kubectl rollout restart deployment/auth-service -n ecommerce

   # Verify Google is responsive
   curl -s -X POST https://accounts.google.com/o/oauth2/token \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=authorization_code&code=test&client_id=test&client_secret=test" \
     2>&1 | grep -q "invalid_grant"  # 400 = working; 503 = still down
   ```

**Follow-up Actions:**
- [ ] Make magic link fallback the default for all OAuth users (reduce future OAuth dependency)
- [ ] Implement circuit breaker for OAuth endpoints: after 3 consecutive 5xx, fail-open to fallback for 5 minutes
- [ ] Add monitoring for Google/Apple OAuth endpoint health (separate probes, not in auth request path)
- [ ] Subscribe to Google Cloud Status API for alerts (programmatic incident detection)
- [ ] Document fallback flow in runbook for team familiarity
- [ ] Reduce OAuth token endpoint timeout from 30s to 10s to fail-fast

---

## Failure Mode Catalog

### 1. Session Fixation After Redis Eviction

**Scenario:** Redis session store hits memory limit. LRU eviction kicks in and deletes an active session entry (e.g., `session:abc123def456` expires from Redis). The user's browser still holds the token `abc123def456` in an HTTP-only cookie.

**Symptom:** User reports "You've been logged out" suddenly mid-session, but no password reset or logout action taken. Attempting to reload page fails with 401 Unauthorized.

**Why it's risky:**
- User may have been performing a critical action (checkout, report submission)
- Browser cache/localStorage may still have stale data
- Frontend may cache user data; user sees old profile info with 401 underneath

**Mitigation:**
- Monitor Redis eviction rate: `redis.evictions_per_sec > 100` alert
- Set Redis max memory to N + 30% buffer (not tight limit)
- Separate session Redis from rate-limit Redis (different policies)
- Frontend should clear cache on 401 response

---

### 2. Rate Limit Counter Desync

**Scenario:** Redis rate-limit key (`rate-limit:ip:192.168.1.1`) expires and is deleted mid-request window. The key is set to expire after 1 minute to track requests per minute. If a key expires before the minute is up, a new counter starts from 0.

**Example timeline:**
- 14:00:00 → First request from IP; counter set to 1, expire at 14:01:00
- 14:00:30 → Key accidentally flushed or expires early due to Redis memory pressure
- 14:00:45 → Second burst of requests; new counter starts from 0, bypasses limit
- Burst of 1000 req/s floods backend, causing temporary unavailability

**Why it's risky:**
- DDoS protection is bypassed during desync window
- Backend overload cascades to database
- Can trigger cascading failures in downstream services

**Mitigation:**
- Use separate ephemeral Redis instance for rate limits (volatile-lru policy)
- Store rate-limit window start time with counter; validate in code
- Add `rate_limit_counter_sync` alert
- Implement in-memory fallback counter in auth-service (loses precision on multi-pod, but prevents total bypass)

---

### 3. Auth-Service Cold Start Under Traffic Spike

**Scenario:** A pod restart (e.g., due to node upgrade, deploy, or crash) occurs during peak traffic. The auth-service container starts but is not yet fully initialized (JWT keys loaded from Vault, connection pools opened to Redis/Postgres). Kubernetes sends traffic to the pod immediately (default `initialDelaySeconds=0`).

**Symptom:** Spike in 500 errors and timeouts for 30–60 seconds after pod appears as "Running" in `kubectl get pods`.

**Why it's risky:**
- High availability slo (99.99%) is broken if pod restarts happen during peak hours
- Cascading failure: clients retry, adding load
- Cold Vault key load can take 5–10 seconds if Vault is slow

**Mitigation:**
- Add startup probe: `initialDelaySeconds=10, periodSeconds=5, failureThreshold=3` (pod marked Ready only after 3 successful health checks)
- Preload Vault keys in pod init container (cache in ephemeral volume)
- Use `PodDisruptionBudget: minAvailable=3` (always keep 3 of 4 replicas up during maintenance)
- Implement graceful shutdown: `terminationGracePeriodSeconds=30` (finish in-flight requests)

---

### 4. Token Replay Attack Detection Gap

**Scenario:** A JWT is issued at 14:00:00 by auth-service and signed with key version 42. The JWKS endpoint caches its response (public key list) for 5 minutes. At 14:01:00, a key rotation occurs (new key version 43 published in Vault). The JWKS cache is stale until 14:05:00.

In the 4-minute gap (14:01:00–14:05:00), a hypothetical replayed token from yesterday (signed with an old, compromised key version 38) could be re-submitted and validated against the cached (but now outdated) key list. The token would fail validation (version 38 is not in today's cached list), but the point is: the validation logic is only as fresh as the cache.

**Scenario variant:** If old key version 38 is legitimately re-activated during an incident recovery, the gap widens; replays of tokens from weeks ago become valid.

**Why it's risky:**
- Token replay is a classic attack; revoked keys must be rejected immediately
- Cache staleness creates a window of weak cryptographic validation
- Incident recovery procedures may temporarily re-activate old keys

**Mitigation:**
- Reduce JWKS cache TTL to <1 minute (or event-driven push)
- Maintain a revoked key version blocklist in auth-service in-memory store (sync from Vault every 30 seconds)
- Implement token blacklist for high-value operations (add JTI to Redis on logout/password reset)
- Log and alert on old key version usage (monitor for replays)

---

## Runbook Procedures

### Procedure: Flush Expired Sessions Only (Safe Redis Cleanup)

**When to use:** Redis session memory is high (>80%), but you want to remove only expired entries without evicting active sessions.

**Duration:** 5–10 minutes

**Prerequisites:**
- Redis CLI access: `kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli`
- Backup Redis snapshot (automatic hourly; verify: `ls -lh /data/redis/dump.rdb`)

**Steps:**

1. **Count current sessions:**
   ```bash
   kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli
   > DBSIZE
   # Output: (integer) 2457834
   ```

2. **Scan and delete expired keys only (via Lua script):**
   ```bash
   # Use this Lua script to safely iterate and delete only TTL-expired keys
   cat <<'EOF' > /tmp/flush_expired.lua
   local cursor = "0"
   local deleted = 0
   repeat
     local result = redis.call("SCAN", cursor, "MATCH", "session:*", "COUNT", 1000)
     cursor = result[1]
     local keys = result[2]
     for _, key in ipairs(keys) do
       local ttl = redis.call("TTL", key)
       if ttl == -1 then  -- key has no expiration
         redis.call("DEL", key)
         deleted = deleted + 1
       elseif ttl == -2 then  -- key does not exist (already expired)
         deleted = deleted + 1
       end
     end
   until cursor == "0"
   return deleted
   EOF

   kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli --pipe < /tmp/flush_expired.lua
   # Output: (integer) 34521
   ```

3. **Verify memory freed:**
   ```bash
   kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli INFO memory
   # Compare used_memory_human before/after
   # Expected: 50–200 MB freed (depending on session count)
   ```

4. **Monitor for side effects (5 minutes):**
   ```bash
   # Watch session validation success rate
   kubectl logs deployment/auth-service -n ecommerce --follow | grep session_valid
   # Should be >99%
   ```

**Rollback:** If error rate spikes, restart Redis from backup:
```bash
kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli BGSAVE
# Wait for BGSAVE to complete, then restart pod
kubectl delete pod redis-sessions-0 -n ecommerce
```

---

### Procedure: Emergency JWT Key Rotation with Dual-Key Window

**When to use:** JWT signing key is compromised or suspected to be compromised. Must rotate keys while maintaining service availability.

**Duration:** 15–30 minutes (complex, run in maintenance window if possible)

**Prerequisites:**
- Vault access with `secret/jwt-signing-key` admin policy
- auth-service source code access (branch: `main` or hotfix)
- 5 minutes of low-traffic period (or accept temporary elevated latency)

**Steps:**

1. **Prepare new key in Vault:**
   ```bash
   # Generate new RSA-2048 private key
   openssl genrsa -out /tmp/jwt-new.key 2048

   # Store new key in Vault (create new version)
   vault kv put secret/jwt-signing-key private_key=@/tmp/jwt-new.key
   # Output: Key Value
   #         --- -----
   #         created_time  2025-02-21T10:30:00Z
   #         version       16

   # Extract public key for downstream services
   openssl rsa -in /tmp/jwt-new.key -pubout -out /tmp/jwt-new-public.key
   cat /tmp/jwt-new-public.key
   ```

2. **Enable dual-key acceptance window in auth-service:**
   ```bash
   # Ensure dual-key window code is deployed
   kubectl set env deployment/auth-service JWT_DUAL_KEY_WINDOW_MINUTES=15 JWT_KEY_SOURCE=current -n ecommerce
   kubectl rollout restart deployment/auth-service -n ecommerce
   kubectl rollout status deployment/auth-service -n ecommerce

   # Verify both old and new keys are listed in JWKS
   curl -s https://auth.ecommerce.internal/.well-known/jwks.json | jq '.keys | length'
   # Output: 2 (old + new)
   ```

3. **Notify downstream services (optional, if using pinned JWKS cache):**
   ```bash
   # Send notification: "New JWT key version 16 is active; both versions accepted for 15 minutes"
   # Downstream services can force JWKS refresh if needed
   curl -X POST https://auth.ecommerce.internal/admin/notify-key-rotation \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d '{"new_key_version": 16, "dual_window_minutes": 15}'
   ```

4. **Monitor dual-key window (during 15 minutes):**
   ```bash
   # Check both key versions are being used
   kubectl logs deployment/auth-service -n ecommerce --since=1m | grep "key_version" | sort | uniq -c
   # Should see both old and new versions in logs

   # Verify no validation errors
   kubectl logs deployment/auth-service -n ecommerce --since=1m | grep -i "signature.*invalid" | wc -l
   # Should be 0 or very low
   ```

5. **After dual-key window expires (15 minutes later):**
   ```bash
   # Disable acceptance of old key
   kubectl set env deployment/auth-service JWT_DUAL_KEY_WINDOW_MINUTES=0 -n ecommerce
   kubectl rollout restart deployment/auth-service -n ecommerce

   # Verify only new key in JWKS
   curl -s https://auth.ecommerce.internal/.well-known/jwks.json | jq '.keys | length'
   # Output: 1 (only new)
   ```

6. **Audit and cleanup:**
   ```bash
   # Revoke old private key in Vault (do NOT delete, keep as audit log)
   vault kv metadata delete secret/jwt-signing-key-v15-revoked || true
   vault kv put secret/jwt-signing-key-v15-revoked \
     private_key=@/tmp/jwt-old.key \
     revoked_at="2025-02-21T10:45:00Z" \
     reason="emergency_rotation"

   # Log key rotation event
   echo "Key rotation completed: v15 → v16, dual-window 15 min, at 2025-02-21T10:30:00Z" >> /var/log/key-rotations.log
   ```

---

### Procedure: Enable Guest Checkout Bypass (During Auth Outage)

**When to use:** Auth service is down or severely degraded, but you want to allow customers to complete purchases without logging in.

**Duration:** 3–5 minutes

**Prerequisites:**
- Feature flag system access (`kubectl` + env vars, or feature flag service)
- Customer communication plan (status page update, email notification)

**Steps:**

1. **Enable guest checkout feature flag:**
   ```bash
   # Method 1: Kubernetes env var (quick, requires frontend rebuild)
   kubectl set env deployment/frontend NEXT_PUBLIC_GUEST_CHECKOUT_ENABLED=true -n ecommerce
   kubectl rollout restart deployment/frontend -n ecommerce

   # Method 2: Feature flag service (no restart needed)
   curl -X PATCH https://feature-flags.ecommerce.internal/api/flags/guest-checkout \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d '{"enabled": true}'
   ```

2. **Verify guest checkout UI is visible:**
   ```bash
   # Manually test in browser incognito (no auth cookies)
   # Navigate to /checkout
   # Should see "Continue as Guest" button prominently
   # Order summary should work without login
   ```

3. **Monitor guest checkout usage and error rate:**
   ```bash
   # Track guest orders
   # SELECT COUNT(*) FROM orders WHERE user_id IS NULL AND created_at > now() - interval '5 min'

   # Watch backend payment processing logs
   kubectl logs deployment/payment-processor -n ecommerce --follow | grep -i guest
   # Should see successful payment processing for guest orders
   ```

4. **Test payment flow end-to-end:**
   ```bash
   # Do a real guest test order in staging first
   # Then enable in production
   ```

5. **Communicate to users (2 minutes):**
   ```bash
   # Post to status page
   # "Auth is temporarily down. You can still check out as a guest; no account needed."

   # Optional: send email to high-value users with cart abandonment risk
   ```

6. **Disable guest checkout once auth recovers:**
   ```bash
   # Method 1:
   kubectl set env deployment/frontend NEXT_PUBLIC_GUEST_CHECKOUT_ENABLED=false -n ecommerce
   kubectl rollout restart deployment/frontend -n ecommerce

   # Method 2:
   curl -X PATCH https://feature-flags.ecommerce.internal/api/flags/guest-checkout \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d '{"enabled": false}'
   ```

**Expected behavior:**
- Guest orders complete without auth
- Guest user email captured at checkout (can link account later)
- Payment processing unchanged
- No user data leakage

---

### Procedure: Disable Social Login and Force Email Auth

**When to use:** OAuth provider(s) are down or experiencing widespread attacks. Email/password auth is your fallback.

**Duration:** 2–5 minutes

**Prerequisites:**
- Kubernetes access
- Communication plan ready

**Steps:**

1. **Disable OAuth provider(s):**
   ```bash
   # Disable Google OAuth
   kubectl set env deployment/auth-service OAUTH_GOOGLE_ENABLED=false -n ecommerce

   # Disable Apple OAuth
   kubectl set env deployment/auth-service OAUTH_APPLE_ENABLED=false -n ecommerce

   # Restart auth-service
   kubectl rollout restart deployment/auth-service -n ecommerce
   kubectl rollout status deployment/auth-service -n ecommerce
   ```

2. **Update frontend to hide OAuth buttons (deploy new version or use feature flags):**
   ```bash
   # Using feature flags (no restart):
   curl -X PATCH https://feature-flags.ecommerce.internal/api/flags/oauth-login \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d '{"enabled": false}'

   # Using env var (requires frontend restart):
   kubectl set env deployment/frontend NEXT_PUBLIC_OAUTH_ENABLED=false -n ecommerce
   kubectl rollout restart deployment/frontend -n ecommerce
   ```

3. **Enable email-based login prominently:**
   ```bash
   # Email login should be the only option on login page
   # "Log in with Email" button should be primary CTA

   # Send magic link on email submit
   # or password-based login (whichever is default)
   ```

4. **Notify users:**
   ```bash
   # Status page: "Social login temporarily unavailable; please use email login"
   # Support: guide users to email login method
   ```

5. **Monitor email login traffic:**
   ```bash
   # Watch email auth logs
   kubectl logs deployment/auth-service -n ecommerce --follow | grep -i "email.*success"

   # Check email send queue
   # SELECT COUNT(*) FROM email_queue WHERE type IN ('password_reset', 'magic_link') AND created_at > now() - interval '5 min'
   ```

6. **Re-enable OAuth once providers are healthy:**
   ```bash
   # Verify provider status
   curl -I https://accounts.google.com  # should be 200
   curl -I https://appleid.apple.com     # should be 200

   # Re-enable
   kubectl set env deployment/auth-service OAUTH_GOOGLE_ENABLED=true OAUTH_APPLE_ENABLED=true -n ecommerce
   kubectl rollout restart deployment/auth-service -n ecommerce

   # Update frontend
   curl -X PATCH https://feature-flags.ecommerce.internal/api/flags/oauth-login \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d '{"enabled": true}'
   ```

---

## Monitoring & Alerts

### Key Metrics

| Metric | Alert Threshold | Notes |
|--------|-----------------|-------|
| `auth.login_error_rate` | >5% for 2 min | Alerts on failed login attempts |
| `auth.login_latency_p99` | >500ms for 5 min | Login slowdown indicator |
| `auth.session_validation_error_rate` | >1% for 1 min | Session/JWT validation failures |
| `auth.session_validation_latency_p99` | >50ms for 5 min | Redis/in-process slowdown |
| `redis.session_memory_percent` | >80% for 2 min | Session Redis capacity warning |
| `redis.session_evictions_per_sec` | >1000 for 1 min | Eviction-induced session losses |
| `redis.rate_limit_latency_p99` | >10ms for 5 min | Rate limit processing slowdown |
| `vault.key_load_latency_p99` | >5000ms for 3 min | JWT key retrieval from Vault delay |
| `auth.jwt_signing_error_rate` | >0.1% for 2 min | Token signing failures |
| `oauth.google_error_rate` | >10% for 2 min | Google OAuth provider errors |
| `oauth.apple_error_rate` | >10% for 2 min | Apple OAuth provider errors |
| `auth.rate_limit_triggered_rate` | >100 req/min (baseline 50) | DDoS detection; surge in rate-limited IPs |
| `auth.pod_restarts` | >1 in 30 min | Pod crash/restart detection |
| `auth.jwks_cache_staleness` | >5 min | JWKS endpoint response age |

### Alerting Rules (Prometheus)

```yaml
# auth-service alerts
groups:
- name: auth_service
  rules:
  - alert: AuthLoginErrorRateHigh
    expr: rate(auth_login_errors_total[2m]) / rate(auth_login_attempts_total[2m]) > 0.05
    for: 2m
    annotations:
      severity: P0
      runbook: "Login error rate spike; check auth-service logs and Redis"

  - alert: AuthSessionValidationErrorRateHigh
    expr: rate(auth_session_validation_errors_total[1m]) / rate(auth_session_validations_total[1m]) > 0.01
    for: 1m
    annotations:
      severity: P1
      runbook: "Session validation failing; check Redis and JWT key health"

  - alert: RedisSessionMemoryHigh
    expr: redis_session_memory_bytes / redis_session_maxmemory_bytes > 0.80
    for: 2m
    annotations:
      severity: P1
      runbook: "Redis session memory >80%; flush expired or increase maxmemory"

  - alert: RedisSessionEvictionsHigh
    expr: rate(redis_session_evicted_keys_total[1m]) > 1000
    for: 1m
    annotations:
      severity: P1
      runbook: "Redis evicting sessions due to memory pressure; check INC-2024-0156 procedure"

  - alert: OAuthProviderErrorRate
    expr: |
      (rate(oauth_google_errors_total[2m]) / rate(oauth_google_requests_total[2m]) > 0.10)
      or
      (rate(oauth_apple_errors_total[2m]) / rate(oauth_apple_requests_total[2m]) > 0.10)
    for: 2m
    annotations:
      severity: P2
      runbook: "OAuth provider errors; check INC-2025-0033 procedure"

  - alert: AuthServicePodRestarts
    expr: increase(kube_pod_container_status_restarts_total{pod=~"auth-service.*"}[30m]) > 1
    annotations:
      severity: P1
      runbook: "Auth-service pod restarting; check pod logs and resource limits"

  - alert: JWKSCacheStaleness
    expr: (time() - jwks_last_refresh_timestamp_seconds) > 300
    annotations:
      severity: P2
      runbook: "JWKS cache stale; check Vault connectivity and key rotation status"
```

### Dashboard Panels

1. **Login Overview** (single-stat)
   - Success rate (%) last 5 min
   - Error rate (%) last 5 min
   - P99 latency (ms) last 5 min

2. **Session Health** (line graph)
   - Active sessions (thousands)
   - Session creation rate (req/sec)
   - Session validation success rate (%)

3. **Redis Session Health** (gauge + line)
   - Memory usage vs. maxmemory
   - Eviction rate (evictions/sec)
   - Key count

4. **OAuth Provider Status** (traffic light)
   - Google OAuth error rate (%)
   - Apple OAuth error rate (%)
   - Last successful exchange timestamp

5. **Auth-Service Replicas** (status)
   - Running pod count / desired replicas
   - Recent restarts (30 days)
   - Node distribution

---

## Escalation Policy

### Incident Severity Definitions

| Severity | Criteria | Page | Target Response | Target Resolution |
|----------|----------|------|-----------------|-------------------|
| **P0** | >10% login failures OR auth unavailability >5 min | Immediate | 5 min | 15 min |
| **P1** | 1–10% login failures OR session data loss OR key compromise | Immediate | 10 min | 30 min |
| **P2** | <1% login failures OR slow logins OR single OAuth provider down | Within 15 min | 30 min | 2 hours |
| **P3** | Isolated user-reported issue OR no measurable impact | Within 1 hour | 1 hour | 24 hours |

### Escalation Chain

1. **Initial Incident Detection**
   - Alert fires in Prometheus → PagerDuty escalates to `identity-platform-oncall` (Slack: `#identity-platform`)
   - On-call engineer acknowledges in PagerDuty within 5 minutes (P0/P1) or 15 minutes (P2)

2. **P0 Escalation (Login Service Down)**
   ```
   On-Call Engineer (identity-platform-oncall)
       ↓ (5 min, no progress)
   Identity Platform Team Lead + Security Lead (page)
       ↓ (10 min, still down)
   VP Engineering + CISO (page)
   ```

3. **P1 Escalation (Data Loss / Security)**
   ```
   On-Call Engineer (identity-platform-oncall)
       ↓ (10 min, no clear root cause)
   Identity Platform Team Lead + Security Lead (page)
       ↓ (20 min, security concern confirmed)
   CISO (page)
   ```

4. **P2 Escalation (Single Provider Down)**
   ```
   On-Call Engineer (identity-platform-oncall)
       ↓ (30 min, ongoing)
   Identity Platform Team Lead (page)
   ```

5. **P3 (No Escalation)**
   - On-call engineer handles alone; may create ticket for async follow-up

### Communication Template

**Initial Notification (Slack, #incidents):**
```
[INC-YYYY-NNNN] Auth Service Issue Detected
Severity: P0 | Time: 2025-02-21 14:22 UTC
Title: Redis Session Store Memory Exhaustion
Status: INVESTIGATING
Assigned: @on-call-engineer
ETA for Update: 14:32 UTC
```

**Status Update (every 10 min during outage):**
```
[INC-YYYY-NNNN] Status Update
Current Status: MITIGATING
Findings: Redis eviction policy was set to `noeviction`. Switched to `allkeys-lru`. Memory freed ~40%.
Action in Progress: Monitoring session validation recovery. P99 latency returning to baseline.
Customer Impact: ~5,200 failed logins in last 2 minutes (recovery trend visible).
ETA Resolution: 14:45 UTC
```

**Incident Close (post-incident):**
```
[INC-YYYY-NNNN] Incident Closed
Final Status: RESOLVED
Duration: 26 minutes
Root Cause: Session TTL extension to 30 days + no capacity planning
Mitigation: Switched Redis policy to `allkeys-lru`, increased maxmemory to 16GB
Timeline: Full incident doc posted in Slack thread
Follow-up: Post-mortem scheduled for 2025-02-22 10:00 UTC
```

### Handoff Protocol

When handing off to next on-call engineer:
1. Post summary of incident, current status, and any open action items in `#identity-platform`
2. Tag new on-call in PagerDuty (if incident ongoing)
3. Verbally sync (Slack call) for >30-minute incidents, explaining:
   - What was tried
   - What partially worked
   - What's still unknown
   - Next steps

### Post-Incident Review

Conduct post-mortem within 48 hours of major incident (P0/P1):
1. Timeline reconstruction
2. Root cause analysis (5 whys)
3. Assigned follow-up tasks (owner + deadline)
4. Update runbook and monitoring if needed
5. Share findings in #identity-platform (no blame, focus on systems)

---

## Quick Reference

**On-Call Contact:** `identity-platform-oncall` (PagerDuty) / `#identity-platform` (Slack)

**Key Dashboards:**
- Auth Health: https://grafana.ecommerce.internal/d/auth-overview
- Redis Session: https://grafana.ecommerce.internal/d/redis-sessions
- OAuth Status: https://grafana.ecommerce.internal/d/oauth-providers

**Key Commands:**
```bash
# Check auth-service status
kubectl get deployment/auth-service -n ecommerce

# View auth logs
kubectl logs deployment/auth-service -n ecommerce --tail=100 -f

# Access Redis session store
kubectl exec -it redis-sessions-0 -n ecommerce -- redis-cli
> DBSIZE
> INFO memory

# Restart auth-service
kubectl rollout restart deployment/auth-service -n ecommerce

# Check JWT key version
kubectl get secret jwt-signing-key -n ecommerce -o yaml | grep version
```

**Vault JWT Key Path:** `secret/jwt-signing-key` (read-only for normal ops; rotate via terraform)

**Database Auth Queries:**
```sql
-- Check recent failed logins
SELECT user_id, ip_address, error_message, created_at
FROM login_attempts
WHERE success = false
  AND created_at > now() - interval '5 minutes'
ORDER BY created_at DESC
LIMIT 20;

-- Check active sessions
SELECT COUNT(*) as active_sessions,
       COUNT(DISTINCT user_id) as unique_users
FROM sessions
WHERE expires_at > now();

-- Check rate-limited IPs (last 5 min)
SELECT ip_address, COUNT(*) as failed_attempts
FROM login_attempts
WHERE success = false
  AND created_at > now() - interval '5 minutes'
GROUP BY ip_address
ORDER BY failed_attempts DESC
LIMIT 10;
```

---

**Document Version:** 1.0
**Last Updated:** 2025-02-21
**Owner:** Identity Platform Team (@identity-platform-oncall)
**Review Frequency:** Quarterly or after any P1+ incident
