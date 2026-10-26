# Engineering Reflection

This document contains candid reflections on the design, reverse-engineering, and implementation process of the Flock Energy API service wrapper over the legacy Urja Meter Ops portal.

---

### 1. What assumptions did you make?

Several key assumptions guided the architecture of this wrapper:
- **Read-Only Upstream System**: We assumed the Urja Meter Ops portal is strictly an upstream telemetry query portal and does not support or require write/mutation actions (such as switching meter disconnect relays or modifying DT mappings). Consequently, our API is designed as an idempotent proxy and caching layer.
- **Fixed Interval Telemetry**: We assumed the consumption dataset represents 30-minute cumulative interval readings over a 7-day rolling window (`DD/MM/YYYY HH:MM`). We assumed timestamps represent standard Indian Standard Time (IST / UTC+5:30) or distribution utility local time, and normalized them to clean ISO-8601 strings for downstream analytics.
- **Stable Signing Secret**: We assumed the cryptographic HMAC signing secret exposed by `/portal/keys` is relatively stable across sessions, but implemented dynamic fetching with caching so any key rotation on the portal will be accommodated gracefully.
- **Grid Size Fits In Memory**: With 403 meters and 40 Distribution Transformers, the entire grid metadata easily fits into a compact in-memory index (< 2 MB). We assumed local indexing would provide sub-millisecond multi-attribute and geospatial queries without needing an external database (e.g. Postgres/PostGIS) for this take-home scope.

---

### 2. Which part was the most difficult, and how did you get unstuck?

The most challenging part was discovering why initial direct POST requests to `/login` were blocked with an unexpected HTTP `403 Forbidden` (`"Cross-site POST form submissions are forbidden"`), despite providing valid credentials. 

To get unstuck:
1. We inspected the HTTP response headers and identified `X-Sveltekit-Page: true`, signaling that the application was built on SvelteKit.
2. Knowing SvelteKit's built-in CSRF protection checks the `Origin` and `Referer` headers against the incoming request URL, we tested adding `Origin: https://urja-ops.flockenergy.tech` and `Referer: https://urja-ops.flockenergy.tech/login`.
3. The request immediately succeeded with HTTP `200` returning `{"type":"redirect","status":303,"location":"/meters"}` and the `__Secure-better-auth.session_token` cookie.
4. Additionally, discovering the hidden `/portal/export` endpoint required decomposing the bundled SvelteKit client chunk (`nodes/4.2Bgc2kUI.js`), where we reverse-engineered the exact HMAC-SHA256 signing format (`GET\n/portal/export\npage=1\n{timestamp}`).

---

### 3. If you had another day, what would you improve?

With an additional day, we would implement:
1. **Persistent Backing Store & Background Poller**: Replace the in-memory index with SQLite (with SpatiaLite) or PostgreSQL with PostGIS, backed by an asynchronous background worker (using Celery or an `asyncio` task loop). The worker would poll the portal periodically, store historical consumption beyond the 7-day rolling window, and compute long-term load profiles.
2. **Streaming / WebSocket Telemetry**: Provide a Server-Sent Events (SSE) or WebSocket endpoint (`/api/v1/meters/{id}/live`) for real-time SCADA monitoring dashboards.
3. **Multi-tenant Credential Pooling**: Instead of a single shared operator credential, implement a credential pool or allow downstream API consumers to pass custom session tokens in the `Authorization: Bearer` header.
4. **Resilient Rate Limiting & Circuit Breaking**: Implement token-bucket rate limiting (e.g. `slowapi` or Redis token bucket) and circuit breakers (`tenacity` or `pybreaker`) to safeguard the legacy portal from being overwhelmed during traffic spikes.

---

### 4. What mistake did you make while solving this (there's always one)?

Early in the investigation, when viewing the `/meters` page HTML response, the SSR markup rendered:
```html
<tr><td colspan="6" class="px-4 py-6 text-center text-slate-400">No meters found.</td></tr>
```
Initially, we suspected our session cookies were not being accepted or that the operator account lacked permissions to view meters. We spent time inspecting query parameters (e.g., trying `?search=`, `?page=1`, `?all=true`).

Only upon downloading and searching through the client JavaScript chunks (`nodes/5.C4dYcCRt.js`) did we realize that Urja is a client-rendered SPA: the initial HTML is just a skeleton placeholder, and the client JavaScript asynchronously fetches `/portal/meters/search?q=&page=1` upon mounting. Once we recognized the client-side hydration pattern, progress accelerated significantly.

---

### 5. If you were reviewing your own submission, what would you criticise?

- **Synchronous HTTP Client vs Async Client**: The current `UrjaPortalClient` utilizes `httpx.Client` synchronously rather than `httpx.AsyncClient`. While this works cleanly with FastAPI's threadpool worker model for hundreds of meters, a high-throughput production service handling thousands of concurrent requests should be fully `async`/`await` from the network socket up to eliminate thread context switching.
- **In-Memory Index Scalability Boundary**: The spatial proximity query and multi-attribute filters currently evaluate in Python memory. While blazing fast for 403 meters (taking < 1 ms), this approach would struggle once the fleet reaches 100,000+ meters (due to memory overhead and $O(N)$ linear scans for distance calculations). At that scale, an R-tree spatial index (like SQLite R*Tree or PostGIS GIST index) would be required.
- **Hardcoded Credential Defaults**: While configurable via environment variables (`URJA_USERNAME`, `URJA_PASSWORD`), the code contains fallbacks to the take-home test credentials for immediate out-of-the-box evaluation. In a strict production system, missing secrets should fail loudly at startup.
