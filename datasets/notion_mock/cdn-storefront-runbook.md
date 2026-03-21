# CDN & Storefront Runbook

## Service Overview

**Service:** CDN & Storefront (ecommerce platform web layer)

**Architecture:**
- Browser traffic → CDN edge nodes (Varnish-based, 12 PoPs across NA/EU/APAC) → Origin shield (single region, AWS us-east-1) → Next.js 14 storefront application (Kubernetes cluster, 6 replicas, standard-pool) → Backend API (separate service)
- Image delivery via dedicated `image-service` (Kubernetes, 4 replicas) with passthrough CDN caching. All product images are resized on-demand by image-service.
- Static assets (JS, CSS, fonts) served from CDN with long TTLs (30 days). Dynamic pages (`/product/*`, `/cart`, `/checkout`) use `Surrogate-Control: max-age=300` for 5-minute edge cache.
- Origin shield sits between CDN edge and storefront, reducing origin traffic by 60–75% on cache hits.

**Key Dependencies:**
- CDN vendor API and edge node infrastructure (Varnish, managed by CDN team)
- Origin shield (AWS NAT gateway, CloudFront behavior)
- Storefront Next.js application + Kubernetes cluster
- Image-service for image resizing and optimization
- Backend API (product data, pricing, inventory)
- PostgreSQL database (product catalog)
- Redis (session store, cache layer)

**Service Owner:** Storefront Platform team
- **PagerDuty:** `storefront-platform-oncall`
- **Slack:** `#incident-storefront`
- **On-call runbook:** This document

**SLOs:**
- Storefront TTFB (time to first byte) <800ms P99 at edge (measured at CDN), <2s P99 at origin
- Image delivery (image-service latency) <300ms P95 globally
- CDN cache hit rate >85% (excludes api.* and internal traffic)
- Storefront availability 99.95% (allows ~22 minutes downtime/month)
- Image-service availability 99.9%

---

## Recorded Incidents

### INC-2024-0089 — Origin Shield Misconfiguration Causing Cache Bypass

**Date:** 2024-06-17
**Severity:** P1 (Customer-facing, widespread availability impact)
**Duration:** 31 minutes (detected at +8m via monitoring alert)

**Description:**
During a frontend deploy at 14:22 UTC, a Next.js config change altered the `Surrogate-Control` header generation on product pages. A template variable substitution bug set the header to `no-store` instead of `max-age=300`. This caused the CDN edge nodes to stop caching all product pages (`/product/*` paths). Every single product page request bypassed the cache and hit the origin shield directly.

**Impact:**
- CDN cache hit rate on product pages dropped from 88% to 2% in 90 seconds
- Origin request rate spiked 40x (from ~2k req/s to 80k req/s)
- Storefront application CPU and memory utilization maxed out
- Storefront P99 latency rose from 180ms to 9.2 seconds
- Error rate climbed to 12% (timeouts and 503 Service Unavailable)
- Customer conversion dip estimated at 15–18% during the incident
- Total customer sessions affected: ~4,200

**Root Cause:**
A frontend developer pushed a config change that modified the cache header logic. The change used an environment variable `NEXT_CACHE_MODE` that was accidentally set to `no-store` in the production Next.js build config, overriding the intended `max-age=300` for dynamic pages.

**Resolution Steps:**

1. **Immediate: Confirm the incident via logs and metrics**
   ```bash
   # SSH to a CDN edge node (via jump host)
   ssh -i ~/.ssh/cdn-edge.key admin@edge-us-east.cdn.example.com

   # Check Varnish cache stats
   varnishadm "stats" | grep "cache_hit"
   # Output will show hit rate dropping; expected ~88%, actual ~2%

   # Check origin traffic spike
   curl -s "https://api.internal.observability.com/v1/metrics?query=storefront_origin_requests_per_sec&duration=1h" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   ```

2. **Verify the root cause by checking recent deploys**
   ```bash
   # Check the last 5 deployments
   kubectl rollout history deployment/storefront -n ecommerce

   # Inspect the latest deployment config for env vars
   kubectl get deployment storefront -n ecommerce -o yaml | grep -A 20 "env:"
   ```

3. **Immediate mitigation: Rollback the storefront deployment**
   ```bash
   # Undo to the previous stable image (revision N-1)
   kubectl rollout undo deployment/storefront -n ecommerce

   # Verify rollout status
   kubectl rollout status deployment/storefront -n ecommerce --timeout=2m
   # Expected: "deployment "storefront" successfully rolled out"
   ```

4. **Purge CDN cache to clear stale no-store headers**
   ```bash
   # Full site purge (nuclear option)
   curl -X POST https://api.cdn.example.com/v3/purge \
     -H "Authorization: Bearer $CDN_API_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "paths": ["/*"],
       "purge_type": "full"
     }'

   # Monitor purge completion (should complete <30 seconds)
   curl -s "https://api.cdn.example.com/v3/purge-status/last" \
     -H "Authorization: Bearer $CDN_API_TOKEN"
   ```

5. **Verify recovery**
   ```bash
   # Check cache hit rate recovery
   curl -s "https://api.internal.observability.com/v1/metrics?query=cdn_cache_hit_rate&duration=5m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   # Expected: should return to >85% within 5 minutes

   # Verify origin traffic drops back to baseline
   curl -s "https://api.internal.observability.com/v1/metrics?query=storefront_origin_requests_per_sec&duration=5m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   # Expected: should drop to ~2k req/s

   # Check storefront error rate
   curl -s "https://api.internal.observability.com/v1/metrics?query=storefront_error_rate&duration=5m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   # Expected: should return to <0.5% within 2 minutes
   ```

**Follow-up Actions:**
- **Alert tuning:** Add a cache hit rate alert: fire if `cdn_cache_hit_rate < 70%` for >5 minutes. Owner: CDN team.
- **Pipeline change:** Add a config diff review step to the deploy pipeline. Require human approval of changes to `Surrogate-Control` or cache headers.
- **Testing:** Add a synthetic test that verifies correct cache headers on product pages post-deploy.
- **Root cause:** Template variable substitution in Next.js config. Added to code review checklist.

**Incident Report:** Available at [internal-link-to-postmortem]

---

### INC-2024-0445 — Image Service OOM Under Holiday Load

**Date:** 2024-12-26
**Severity:** P0 (All users affected, product images unavailable)
**Duration:** 19 minutes (detected at +4m by on-call)

**Description:**
On December 26 (post-Christmas shopping peak), traffic to the storefront spiked 3.2x above baseline. Merchants simultaneously uploaded large product images (many uncompressed, up to 24MP). The `image-service` pods began processing resize requests for these large images. Each image resize operation required up to 2GB of memory (for in-memory image buffer + resizing). The Kubernetes memory limit was set to 512Mi per pod. All four pods were OOMKilled within 3 minutes, and new pods crashed immediately upon startup. Image requests returned 502 Bad Gateway for 19 minutes until manual intervention.

**Impact:**
- All product images broken sitewide (no images loading on product pages, category pages, search results)
- Conversion rate dropped 22% (estimated $340k revenue impact for the day)
- Customer complaints flooded support; social media mentions of "broken site"
- 100% of image requests failed (4,500+ req/s returning 502)
- Estimated 12,400 sessions affected

**Root Cause:**
1. Image-service memory limit was insufficiently provisioned for large merchant uploads
2. No input validation on image upload size; merchants could upload 24MP+ images
3. Image resizing algorithm loaded entire image into memory instead of streaming
4. No memory request set, so Kubernetes scheduler could overprovision pods on a node

**Resolution Steps:**

1. **Immediate: Verify OOM status**
   ```bash
   # Check image-service pod events and logs
   kubectl get events -n ecommerce --sort-by='.lastTimestamp' | grep -i "oom\|image-service"

   # Inspect pod logs
   kubectl logs -l app=image-service -n ecommerce --tail=50
   # Expected output: "Out of memory: Kill process..."

   # Verify memory usage just before crash
   kubectl top pods -n ecommerce -l app=image-service --containers
   ```

2. **Immediate fix: Increase memory limits and requests**
   ```bash
   # Update memory resource limits for image-service
   kubectl set resources deployment/image-service \
     --limits=memory=2Gi,cpu=2 \
     --requests=memory=2Gi,cpu=500m \
     -n ecommerce

   # Verify the change
   kubectl get deployment image-service -n ecommerce -o jsonpath='{.spec.template.spec.containers[0].resources}'
   ```

3. **Force pod restart to spin up with new limits**
   ```bash
   # Trigger a rolling restart
   kubectl rollout restart deployment/image-service -n ecommerce

   # Monitor rollout
   kubectl rollout status deployment/image-service -n ecommerce --timeout=3m
   # Expected: all 4 pods become Ready within 90 seconds

   # Verify pods are healthy
   kubectl get pods -n ecommerce -l app=image-service
   ```

4. **Verify image service recovery**
   ```bash
   # Check request success rate
   curl -s "https://api.internal.observability.com/v1/metrics?query=image_service_2xx_rate&duration=5m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   # Expected: should return to >99% within 2 minutes

   # Verify latency
   curl -s "https://api.internal.observability.com/v1/metrics?query=image_service_latency_p95&duration=5m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   # Expected: should drop to <300ms P95
   ```

5. **Monitor for stability (30 minutes post-incident)**
   ```bash
   # Check for further OOMKills
   kubectl get events -n ecommerce -w | grep -i "oom"
   # Expected: no new OOM events

   # Verify memory usage stable
   watch 'kubectl top pods -n ecommerce -l app=image-service --containers | tail -5'
   # Expected: memory usage <500Mi per pod during high load
   ```

**Follow-up Actions:**
- **Input validation:** Add upload size validation to prevent merchant uploads >8MP (max 4MB file size)
- **Resource tuning:** Increase image-service memory request to 2Gi and limit to 3Gi
- **Monitoring:** Add alert: `image_service_memory_percent > 80%` for >2 minutes
- **Architecture:** Evaluate streaming image resize to reduce in-memory footprint
- **Capacity planning:** Update holiday capacity forecast for 4x peak traffic; image-service needs n+2 replica headroom
- **Postmortem:** Root cause was resource planning; image-service was provisioned for 1x baseline traffic, not peak

**Incident Report:** Available at [internal-link-to-postmortem]

---

### INC-2025-0019 — Frontend Deploy Causing Storefront 500s

**Date:** 2025-01-15
**Severity:** P1 (Customer checkout impaired, high conversion impact)
**Duration:** 8 minutes (detected by synthetic monitoring; not alerted on initially)

**Description:**
A Next.js storefront deploy at 09:47 UTC was missing the `NEXT_PUBLIC_CHECKOUT_URL` environment variable in the build-time configuration. This variable is used by the checkout button component (rendered on every product page). When the component tried to reference `process.env.NEXT_PUBLIC_CHECKOUT_URL`, it received `undefined`. The checkout button threw a runtime error, which cascaded to a full page 500 error on any page containing a checkout button. All product pages, cart page, and checkout initiation failed. Synthetic monitoring detected the spike 4 minutes after deploy; incident was declared at minute 8 when manual triage confirmed 500 errors on all product pages.

**Impact:**
- All pages with checkout button returned 500 Internal Server Error
- ~400 customer sessions in checkout flow dropped (abandoned cart impact)
- Conversion rate at 0% during incident (unable to complete purchases)
- Estimated lost revenue: $18–22k for 8 minutes of outage
- Support team received 180+ complaints/escalations

**Root Cause:**
Environment variable `NEXT_PUBLIC_CHECKOUT_URL` was not injected into the Next.js build environment during the deploy. The variable is required at build time (static generation). A recent change to the CI/CD pipeline's build step removed the explicit export of this variable from the deploy script. The variable was present in `.env.production` but not passed to the Docker build context.

**Resolution Steps:**

1. **Immediate: Confirm the 500 error source**
   ```bash
   # Check storefront pod logs for error pattern
   kubectl logs -l app=storefront -n ecommerce --tail=100 | grep -i "NEXT_PUBLIC_CHECKOUT_URL\|500"
   # Expected: error about undefined environment variable

   # Verify error rate spike
   curl -s "https://api.internal.observability.com/v1/metrics?query=storefront_5xx_error_rate&duration=10m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   ```

2. **Immediate mitigation: Rollback the deployment**
   ```bash
   # Check the rollout history
   kubectl rollout history deployment/storefront -n ecommerce

   # Undo to the previous known-good revision
   kubectl rollout undo deployment/storefront -n ecommerce

   # Verify the rollback
   kubectl rollout status deployment/storefront -n ecommerce --timeout=2m
   # Expected: "deployment 'storefront' successfully rolled out" within 90 seconds

   # Watch pod restart
   kubectl get pods -n ecommerce -l app=storefront -w
   # Expected: old pods terminate, new pods become Ready
   ```

3. **Verify checkout functionality restored**
   ```bash
   # Run synthetic test for checkout flow
   curl -s "https://api.internal.testing.com/v1/synthetics/run/checkout-flow-test" \
     -X POST \
     -H "Authorization: Bearer $TEST_API_TOKEN"
   # Expected: test passes within 30 seconds

   # Check error rate recovery
   curl -s "https://api.internal.observability.com/v1/metrics?query=storefront_5xx_error_rate&duration=5m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   # Expected: drop to <0.1% within 1 minute
   ```

4. **Validate the previous build was healthy**
   ```bash
   # Inspect the previous image to confirm it has checkout URL
   kubectl describe pod <previous-pod-id> -n ecommerce | grep "Image:"
   # Note the image digest

   # (Optional) inspect build logs from CI/CD for previous deploy
   # Access CI/CD dashboard and check checkout URL injection step
   ```

**Follow-up Actions:**
- **Build validation:** Add a build-time check that fails the Docker build if `NEXT_PUBLIC_CHECKOUT_URL` is not set. Exit code 1 if missing.
- **Post-deploy smoke test:** Add a synthetic test that verifies the checkout button renders on a product page post-deploy.
- **Env var validation:** Add a startup check in the Next.js app (e.g., in `next.config.js` or `_document.tsx`) to validate required public env vars before build completes.
- **CI/CD improvement:** Enforce env var injection in the GitHub Actions / GitLab CI script. Use a checklist of required variables and fail if any are missing.
- **Alert improvement:** Add a specific alert for "checkout button 500 errors" that fires if `checkout_page_5xx_rate > 5%` for >2 minutes (faster detection).
- **Postmortem:** Pipeline ownership unclear; add env var export as a mandatory step in the deploy runbook.

**Incident Report:** Available at [internal-link-to-postmortem]

---

## Failure Mode Catalog

### 1. CDN Cache Stampede on Origin

**Definition:** After a cache purge or TTL expiry, a large number of simultaneous requests hit the origin shield and storefront, overwhelming capacity.

**Symptoms:**
- CDN cache hit rate drops to <20%
- Origin P99 latency spikes to >5s
- Origin error rate rises (429 Too Many Requests, 503 Service Unavailable)
- Storefront application CPU and memory max out

**Causes:**
- Large-scale cache purge without staggered request replay
- TTL too short on high-traffic pages (e.g., homepage has `max-age=10`)
- Origin shield not configured with request coalescing
- Thundering herd on product launches or flash sales

**Mitigation:**
- Increase origin replica count on-demand (see Procedure: Increase Origin Replica Count)
- Implement request coalescing in Varnish to collapse simultaneous cache misses
- Use staggered purge or soft purges (`Surrogate-Key` based) instead of full `/*` purges
- Monitor cache hit rate; alert if <70% for >5 minutes

---

### 2. Stale CDN Edge After Failed Purge

**Definition:** CDN edge nodes continue serving stale content even after a purge request succeeds (CDN API reports success, but edges don't actually purge).

**Symptoms:**
- Users report seeing old product prices, images, or page content
- CDN API purge succeeds (returns 200)
- Cache hit rate appears normal (>85%)
- Stale content complaints appear in support tickets
- Browser cache headers show old `Last-Modified` dates

**Causes:**
- Purge API call succeeds but edges don't receive purge command (network partition, queue backlog)
- Varnish purge grace period `grace=24h` serving stale despite purge request
- Only a subset of edge nodes receive the purge (geographically partitioned)
- CDN API returns success before propagating to all edge nodes

**Mitigation:**
- After purge API call, verify purge status via CDN's purge-status endpoint
- Add a verification step: poll a specific edge node and validate it's serving fresh content
- Use Surrogate-Keys for targeted purges (safer than `/*` purges)
- Set a shorter grace period on Varnish (e.g., `grace=60s` instead of `24h`)
- Escalate to CDN vendor if purge status shows pending >5 minutes

---

### 3. Image Service CPU Spike on Malformed Uploads

**Definition:** A corrupt or malformed image file causes the image-service resize operation to hang or loop infinitely, consuming CPU and blocking all other resize requests.

**Symptoms:**
- Image-service CPU usage spikes to 100% on one or more pods
- Requests queue up and timeout (>30s latency)
- Image-service latency P95 >5s
- New image requests fail (timeout, connection reset)
- Only specific images fail; others succeed

**Causes:**
- Corrupted image file (partial upload, bit-flip, unsupported codec)
- Infinite loop in image processing library (libjpeg, libpng) when encountering malformed headers
- Image dimensions claim billions of pixels (zip-bomb-like attack)
- Merchant uploads partial/truncated image files

**Mitigation:**
- Add image validation on upload: check magic bytes, dimensions, file integrity before accepting
- Set timeout on image resize operations (max 10 seconds; kill operation if exceeded)
- Isolate problematic image in quarantine table for manual inspection
- Force-delete the offending image from CDN and S3, remove from product catalog
- Increase image-service CPU request to handle backlog faster (see Procedure: Increase Origin Replica Count for analogous steps)

---

### 4. Static Asset 404 After Deploy

**Definition:** After a Next.js deploy, static assets (JS bundles, CSS, fonts) return 404 errors because file hashes change but CDN still serves requests for old asset paths.

**Symptoms:**
- Browser console shows 404 errors for JS/CSS resources (e.g., `_next/static/chunks/main-abc123.js`)
- Page HTML loads but renders as unstyled, non-interactive
- CDN cache hit rate normal (>85%) but assets still 404
- Issue appears immediately after deploy and then clears after ~5 minutes (as old cache expires)
- Lighthouse scores drop; user experience reports "broken styling"

**Causes:**
- Next.js build generates new hashes for assets due to code changes
- HTML references new asset paths (e.g., `main-abc123.js` → `main-xyz789.js`)
- CDN still has old HTML in cache, pointing to old asset paths
- Old asset files still cached under old paths
- Deploy doesn't purge `_next/static/*` paths

**Mitigation:**
- Add a post-deploy step that purges `_next/static/*` and `/index.html` from CDN
  ```bash
  curl -X POST https://api.cdn.example.com/v3/purge \
    -H "Authorization: Bearer $CDN_API_TOKEN" \
    -d '{
      "paths": ["/_next/static/*", "/index.html", "/"]
    }'
  ```
- Set a shorter TTL on HTML files (`max-age=60` instead of `300`) so new paths propagate faster
- Use Next.js `out-of-band` static generation to pre-warm the asset cache post-deploy
- Monitor synthetic test that validates all JS/CSS assets return 200, not 404

---

## Runbook Procedures

### Procedure: Emergency CDN Purge

**Use when:** Origin is getting hammered, stale content is being served, or you need to force all edge nodes to re-fetch from origin.

**Prerequisites:**
- Access to CDN API token (stored in `$CDN_API_TOKEN` env var)
- Slack notification to `#incident-storefront` (optional but recommended)

**Steps:**

1. **Decide purge scope** (full vs. targeted):
   - **Full purge** (`/*`): Use if entire site is stale or broken (slowest recovery, highest origin load)
   - **Targeted purge** (e.g., `/product/*`): Use if only specific paths are broken (faster, lower origin load)

2. **Verify API access**
   ```bash
   curl -s "https://api.cdn.example.com/v3/status" \
     -H "Authorization: Bearer $CDN_API_TOKEN"
   # Expected: 200 OK with API version info
   ```

3. **Initiate purge**
   ```bash
   # For full site purge (nuclear option)
   PURGE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST https://api.cdn.example.com/v3/purge \
     -H "Authorization: Bearer $CDN_API_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "paths": ["/*"],
       "purge_type": "full",
       "async": false
     }')

   HTTP_CODE=$(echo "$PURGE_RESPONSE" | tail -n1)
   BODY=$(echo "$PURGE_RESPONSE" | head -n-1)

   if [[ "$HTTP_CODE" == "200" ]]; then
     echo "Purge initiated. Response: $BODY"
   else
     echo "Purge API failed with $HTTP_CODE. Response: $BODY"
     exit 1
   fi
   ```

4. **Monitor purge completion**
   ```bash
   # Poll purge status (should complete within 30 seconds)
   for i in {1..30}; do
     STATUS=$(curl -s "https://api.cdn.example.com/v3/purge-status/last" \
       -H "Authorization: Bearer $CDN_API_TOKEN" | jq -r '.status')
     echo "Purge status: $STATUS (attempt $i/30)"

     if [[ "$STATUS" == "completed" ]]; then
       echo "Purge completed successfully."
       break
     fi

     sleep 1
   done
   ```

5. **Verify cache hit rate recovery**
   ```bash
   # Check CDN cache hit rate after 2 minutes
   sleep 120
   curl -s "https://api.internal.observability.com/v1/metrics?query=cdn_cache_hit_rate&duration=5m" \
     -H "Authorization: Bearer $OBS_API_TOKEN" | jq '.data.result[0].value'
   # Expected: >85% within 5 minutes
   ```

6. **Alert team** (if full purge was used)
   ```bash
   # Post to Slack
   curl -X POST https://hooks.slack.com/services/YOUR_WEBHOOK_HERE \
     -H 'Content-Type: application/json' \
     -d '{
       "text": ":warning: CDN full purge initiated by '$USER' at '$(date)'. Cache recovery ETA 5 minutes. Monitor #incident-storefront."
     }'
   ```

**Rollback/Undo:**
CDN purge is not reversible. If purge degrades the situation, the solution is to re-deploy the storefront or fix the broken content.

---

### Procedure: Storefront Rollback

**Use when:** A recent deploy introduced errors, broken functionality, or performance regression. Rollback to the last known-good image.

**Prerequisites:**
- Access to Kubernetes cluster (`kubectl` configured for ecommerce namespace)
- Knowledge that the previous deploy was stable (check deployment history)

**Steps:**

1. **Verify rollback target is healthy**
   ```bash
   # View deployment history
   kubectl rollout history deployment/storefront -n ecommerce

   # Inspect the previous (N-1) revision
   REVISION=$(kubectl rollout history deployment/storefront -n ecommerce | tail -2 | head -1 | awk '{print $1}')
   echo "Rolling back to revision $REVISION"
   ```

2. **Initiate rollback**
   ```bash
   # Undo one revision (the last deploy)
   kubectl rollout undo deployment/storefront -n ecommerce

   # Optionally, undo to a specific revision
   # kubectl rollout undo deployment/storefront -n ecommerce --to-revision=$REVISION
   ```

3. **Monitor rollback progress**
   ```bash
   # Watch the rollout status
   kubectl rollout status deployment/storefront -n ecommerce --timeout=2m

   # Verify pods are becoming Ready
   watch 'kubectl get pods -n ecommerce -l app=storefront'
   # Expected: old pods terminate, new pods become Ready (all green)
   ```

4. **Verify application health**
   ```bash
   # Check HTTP health endpoint
   POD=$(kubectl get pods -n ecommerce -l app=storefront -o jsonpath='{.items[0].metadata.name}')
   kubectl exec -it $POD -n ecommerce -- curl -s http://localhost:3000/api/health | jq .
   # Expected: {"status": "healthy"}

   # Run synthetic test for critical user path
   curl -s "https://api.internal.testing.com/v1/synthetics/run/homepage-load-test" \
     -X POST \
     -H "Authorization: Bearer $TEST_API_TOKEN"
   # Expected: test passes (status 200, load time <1s)
   ```

5. **Monitor error rate and latency**
   ```bash
   # Check error rate drops
   curl -s "https://api.internal.observability.com/v1/metrics?query=storefront_5xx_error_rate&duration=5m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   # Expected: <0.1% within 1 minute

   # Verify latency recovers
   curl -s "https://api.internal.observability.com/v1/metrics?query=storefront_latency_p99&duration=5m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   # Expected: <800ms within 1 minute
   ```

6. **Notify team**
   ```bash
   # Post to Slack
   curl -X POST https://hooks.slack.com/services/YOUR_WEBHOOK_HERE \
     -H 'Content-Type: application/json' \
     -d '{
       "text": ":green_circle: Storefront rollback completed by '$USER'. Error rate now <0.1%. Investigation in progress."
     }'
   ```

**Rollback Verification Checklist:**
- [ ] All storefront pods are Ready
- [ ] Error rate <0.5%
- [ ] P99 latency <1s
- [ ] Cache hit rate >85%
- [ ] No new pod crashes (check Events: `kubectl get events -n ecommerce | grep storefront`)

**Follow-up:**
- Don't re-deploy the bad revision without fixes. Identify the root cause (see incident resolution steps above).
- Check if rollback is sufficient or if data needs cleanup (e.g., stale cache from bad deploy).

---

### Procedure: Emergency Enable Image Service Bypass

**Use when:** Image-service is down and images are critical for storefront functioning. Fallback to serving raw CDN URL directly.

**WARNING:** This disables image resizing, optimization, and format conversion (AVIF, WebP). Images will be full-resolution, large file sizes.

**Prerequisites:**
- Access to Kubernetes cluster
- Feature flag system configured (see `backend/app/models/database.py` for feature flag table)
- Understanding that this is a temporary measure (max 2 hours)

**Steps:**

1. **Enable the bypass flag in the feature flag table**
   ```bash
   # Connect to PostgreSQL
   kubectl port-forward -n ecommerce svc/postgres 5432:5432 &

   psql -h localhost -U postgres -d ecommerce_prod -c \
     "INSERT INTO feature_flags (flag_name, enabled, created_at) VALUES ('BYPASS_IMAGE_SERVICE', true, NOW()) \
      ON CONFLICT (flag_name) DO UPDATE SET enabled = true;"
   ```

2. **Verify flag is active in the storefront**
   ```bash
   # The storefront Next.js app will read the flag on next request
   # No restart needed (it's read per-request)

   # Test: Load a product page and check network tab
   # Images should now use CDN raw URLs (no /api/resize/* proxy)

   curl -s "https://storefront.example.com/product/test-product" \
     | grep -o "src=\"[^\"]*\"" | head -5
   # Expected: src="https://cdn.example.com/products/image.jpg" (no resize)
   ```

3. **Monitor for user impact**
   ```bash
   # Check page load time impact (images will be larger)
   curl -s "https://api.internal.observability.com/v1/metrics?query=storefront_page_load_time_p95&duration=10m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"

   # Alert if load time increases >50%
   ```

4. **Re-enable image-service as soon as possible**
   ```bash
   # Restart image-service pods
   kubectl rollout restart deployment/image-service -n ecommerce

   # Monitor pod health
   kubectl rollout status deployment/image-service -n ecommerce --timeout=3m

   # Disable the bypass flag
   psql -h localhost -U postgres -d ecommerce_prod -c \
     "UPDATE feature_flags SET enabled = false WHERE flag_name = 'BYPASS_IMAGE_SERVICE';"
   ```

**Automatic Rollback:**
- Set a time-limit alert: if bypass is enabled >2 hours, page on-call immediately.

---

### Procedure: Increase Origin Replica Count

**Use when:** Origin is overwhelmed (cache stampede, malicious traffic, or legitimate traffic spike). Temporarily scale up storefront pods to absorb load.

**Prerequisites:**
- Access to Kubernetes cluster
- CPU/memory capacity available in the node pool (or auto-scaling enabled)

**Steps:**

1. **Verify current replica count**
   ```bash
   kubectl get deployment storefront -n ecommerce -o jsonpath='{.spec.replicas}'
   # Current: 6 replicas
   ```

2. **Check node pool capacity**
   ```bash
   # Verify nodes have available CPU/memory
   kubectl top nodes

   # Check if cluster autoscaling can provision new nodes
   kubectl describe nodeselector -n ecommerce | grep "standard-pool"
   ```

3. **Scale up the deployment**
   ```bash
   # Increase to 12 replicas (2x current)
   kubectl scale deployment/storefront --replicas=12 -n ecommerce

   # Monitor scaling progress
   kubectl rollout status deployment/storefront -n ecommerce --timeout=5m

   # Verify all new pods are Ready
   kubectl get pods -n ecommerce -l app=storefront
   # Expected: 12 pods in Ready state
   ```

4. **Verify load distribution**
   ```bash
   # Check origin request rate drops
   curl -s "https://api.internal.observability.com/v1/metrics?query=storefront_requests_per_pod&duration=5m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   # Expected: req/pod decreases by 2x

   # Monitor origin latency
   curl -s "https://api.internal.observability.com/v1/metrics?query=storefront_latency_p99&duration=5m" \
     -H "Authorization: Bearer $OBS_API_TOKEN"
   # Expected: latency should drop within 2 minutes
   ```

5. **Scale down after incident**
   ```bash
   # Once origin load is back to normal (cache repopulated), scale back
   # Typical delay: 10–15 minutes after incident resolution

   kubectl scale deployment/storefront --replicas=6 -n ecommerce

   # Monitor graceful termination
   kubectl get pods -n ecommerce -l app=storefront -w
   ```

**Auto-Scaling Alternative:**
If this is a recurring issue, configure Kubernetes Horizontal Pod Autoscaler (HPA) instead:
```bash
kubectl autoscale deployment/storefront --min=6 --max=20 --cpu-percent=70 -n ecommerce
```

---

## Monitoring & Alerts

**Key Metrics to Monitor:**

| Metric | Source | Alert Threshold | Owner |
|---|---|---|---|
| **CDN Cache Hit Rate** | CDN API / Datadog | <70% for 5m | CDN Team |
| **Origin Request Rate** | Storefront logs | >50k req/s (spike >3x baseline) | On-Call |
| **Origin P99 Latency** | APM (Datadog) | >2s for 5m | On-Call |
| **Origin Error Rate (5xx)** | Storefront logs | >2% for 5m | On-Call |
| **Storefront TTFB P99** | Synthetic monitoring | >800ms for 5m | On-Call |
| **Image-Service Latency P95** | APM | >300ms for 5m | Image Team |
| **Image-Service Error Rate** | Image-service logs | >1% for 5m | Image Team |
| **Image-Service Memory %** | Kubernetes metrics | >80% for 2m | Image Team |
| **Image-Service Pod Restarts** | Kubernetes events | >1 restart in 15m | Image Team |
| **Storefront Pod Restarts** | Kubernetes events | >2 restarts in 15m | On-Call |
| **Database Connection Pool Usage** | PostgreSQL metrics | >80% connections in use | DBA |
| **Redis Memory Usage** | Redis metrics | >80% for 5m | Cache Team |

**Alert Channels:**
- **P0 incidents:** Page on-call immediately (PagerDuty), #incident-storefront Slack, customer comms prepare
- **P1 incidents:** Slack alert in #incident-storefront, PagerDuty warning
- **P2 incidents:** Slack alert in #incident-storefront only

**Synthetic Monitoring Tests:**
1. **Homepage load test** — Load homepage, verify all CSS/JS assets return 200
2. **Product page test** — Load random product, verify images load, checkout button renders
3. **Checkout flow test** — Add to cart, navigate to checkout, verify no 500 errors
4. **Image resize test** — Request image with various sizes, verify latency <300ms P95

---

## Escalation Policy

### Severity Levels

| Level | Response Time | Owner | Definition |
|---|---|---|---|
| **P0** | Immediate (5 min) | On-call + Manager | Customer-facing outage affecting >10% of users; revenue impact >$10k/hour; site entirely down |
| **P1** | 15 min | On-call | Customer-facing degradation (25–100% error rate, 800ms+ latency spike); revenue impact $1–10k/hour |
| **P2** | 30 min | On-call | Partial degradation (<10% error rate); non-critical features broken; estimated <$1k impact |
| **P3** | 4 hours | Product team | Internal tools broken; no customer-facing impact; operational issue |

### Escalation Chain

1. **Initial Response (On-Call, 0–5 min):**
   - Acknowledge alert in PagerDuty
   - Post incident thread in #incident-storefront Slack
   - Run initial diagnostics (logs, metrics, deployment status)
   - Declare severity level

2. **First Escalation (On-Call + Manager, 10 min if P0):**
   - If on-call is stuck: escalate to Storefront Platform manager via PagerDuty
   - Manager may authorize emergency rollback, origin scaling, or CDN purge
   - Activate war room Zoom call (link in runbook Slack pin)

3. **Second Escalation (CDN Vendor, 15 min if origin/CDN issue):**
   - If issue is confirmed to be CDN-side: open support ticket with CDN vendor
   - Use escalation channel: `support+urgent@cdn-vendor.com`
   - Provide: incident timeline, CDN API responses, error rates, affected regions

4. **Third Escalation (Database Team, 10 min if database issue):**
   - If origin latency is high due to slow queries: page DBA oncall
   - DBA may enable read replicas, kill slow queries, or increase connection pool
   - Contact: `#dba-oncall` Slack channel

### War Room

- **Zoom:** [war-room-zoom-link-pinned-in-slack]
- **Runbook:** This document (shared in Slack pin)
- **Key stakeholders to invite:**
  - On-call (host)
  - Manager (Storefront Platform)
  - Backend engineer (if API issue)
  - CDN vendor (if edge issue)
  - Customer support lead (for comms)

### Communication Template

**Initial (0 min):**
```
:warning: INCIDENT: INC-2025-XXXX — <Title>
Severity: P<N>
Status: INVESTIGATING
Affected: <Storefront product pages / image delivery / etc.>
ETA: <estimated fix time or "investigating">
```

**Update (every 5 min during incident):**
```
INCIDENT UPDATE: INC-2025-XXXX
Latest: <status — what you're doing now>
Root Cause: <preliminary hypothesis or "still investigating">
ETA: <revised estimate>
Impact: <current error rate, affected users, revenue impact>
```

**Resolution (incident end):**
```
:green_circle: INCIDENT RESOLVED: INC-2025-XXXX
Root Cause: <confirmed cause>
Fix: <what was done — rollback, config change, etc.>
Duration: <total incident time>
Impact: <final customer impact>
Postmortem: <link to postmortem doc due within 24 hours>
```

### Handoff Protocol

When passing the incident to a new on-call:
1. Brief the new on-call with current status, attempted solutions, and next steps
2. Provide admin/API access (credentials, tokens)
3. Walk through current state of Kubernetes, CDN, logs, and monitoring
4. Set a 30-minute follow-up check-in call

---

## Quick Reference

**Emergency Contacts:**
- **Storefront Platform On-Call:** `storefront-platform-oncall` (PagerDuty)
- **Slack:** `#incident-storefront`
- **CDN Vendor Escalation:** `support+urgent@cdn-vendor.com`
- **Database Team:** `#dba-oncall`

**Common Commands:**

```bash
# Verify storefront health
kubectl get deployment storefront -n ecommerce
kubectl top pods -n ecommerce -l app=storefront

# Check recent deploys
kubectl rollout history deployment/storefront -n ecommerce

# Rollback immediately
kubectl rollout undo deployment/storefront -n ecommerce

# CDN purge
curl -X POST https://api.cdn.example.com/v3/purge \
  -H "Authorization: Bearer $CDN_API_TOKEN" \
  -d '{"paths":["/*"]}'

# Check metrics
curl "https://api.internal.observability.com/v1/metrics?query=<metric>" \
  -H "Authorization: Bearer $OBS_API_TOKEN"

# View logs
kubectl logs -l app=storefront -n ecommerce --tail=100
kubectl logs -l app=image-service -n ecommerce --tail=100
```

**Useful Links:**
- [Postmortems Index](https://internal.wiki/incidents/postmortems)
- [CDN API Docs](https://api.cdn.example.com/docs)
- [Observability Dashboard](https://observability.internal/dashboards/storefront)
- [Deployment Runbook](https://internal.wiki/runbooks/deployment)

---

**Document Version:** 1.0
**Last Updated:** 2025-03-21
**Next Review:** 2025-06-21 (quarterly)
**Owner:** Storefront Platform team
