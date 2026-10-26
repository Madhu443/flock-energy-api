# Urja Meter Ops — Protocol & Architecture Discovery

This document details the reverse-engineered internal behavior of the legacy utility portal (**Urja Meter Ops** hosted at `https://urja-ops.flockenergy.tech`). It documents the authentication mechanics, discovered internal API endpoints, client-side rendering pipeline, data structures, and idiosyncrasies.

---

## 1. Architectural Overview

The Urja Meter Ops application is a **SvelteKit Single-Page Application (SPA)** with server-side rendering (SSR) and dynamic client-side hydration:
- **Framework**: SvelteKit (identifiable by `X-Sveltekit-Page: true`, `__sveltekit_uzbk0k`, and `kit.start(...)` initialization calls in page scripts).
- **Authentication**: `Better-Auth` session management using HttpOnly, SameSite cookies.
- **Rendering Pattern**: Hybrid SSR + client-side data fetching. When a user requests `/meters`, the initial server HTML renders an empty table placeholder (`"No meters found"`), which is immediately populated on the client through asynchronous fetch calls to internal `/portal/*` endpoints.

---

## 2. Authentication & Session Management

### 2.1 Login Workflow
- **URL**: `POST https://urja-ops.flockenergy.tech/login`
- **Content-Type**: `application/x-www-form-urlencoded`
- **Form Fields**:
  - `email`: Operator email address (`operator@urja.local`). *Note*: The input is named `email`, not `username`.
  - `password`: Account password (`urja-ops-2026`).

### 2.2 CSRF Protection Mechanism
SvelteKit enforces origin-based Cross-Site Request Forgery (CSRF) protection on all form actions:
- If a client makes a `POST /login` without explicit `Origin` or `Referer` headers matching `https://urja-ops.flockenergy.tech`, the server immediately rejects the request with HTTP **`403 Forbidden`** and the body:
  ```
  Cross-site POST form submissions are forbidden
  ```
- **Resolution**: The HTTP client must explicitly supply:
  ```http
  Origin: https://urja-ops.flockenergy.tech
  Referer: https://urja-ops.flockenergy.tech/login
  ```

### 2.3 Session Token & Cookies
Upon valid credentials, the server returns HTTP **`200 OK`** with a redirect action payload:
```json
{"type": "redirect", "status": 303, "location": "/meters"}
```
Along with the `Set-Cookie` response header:
```http
Set-Cookie: __Secure-better-auth.session_token=<TOKEN>; Max-Age=3600; Path=/; HttpOnly; Secure; SameSite=Lax
```
- **Cookie Name**: `__Secure-better-auth.session_token`
- **TTL**: 3600 seconds (1 hour).
- **Behavior on Expiration**: Subsequent calls to `/portal/*` return HTTP **`401 Unauthorized`** with:
  ```json
  {"error": "unauthorized", "message": "A valid session is required"}
  ```
  Calls to HTML routes return HTTP **`302 Found`** redirecting to `/login`.

### 2.4 Sign Out
- **URL**: `POST /api/auth/sign-out`
- Clears the session token cookie.

---

## 3. Discovered Internal Endpoints

During network reconnaissance and inspection of SvelteKit client chunks (`nodes/4.2Bgc2kUI.js`, `nodes/5.C4dYcCRt.js`, `nodes/6.l777LXKL.js`), the following internal endpoints were identified:

| Endpoint | Method | Auth Required | Description |
| :--- | :--- | :--- | :--- |
| `/portal/meters/search?q={query}&page={page}` | `GET` | Yes | Paginated search of meters by ID or serial. |
| `/meters/{meter_id}` | `GET` | Yes | Meter detail HTML page (server-side rendered). |
| `/meters/{meter_id}/__data.json` | `GET` | Yes | SvelteKit serialized route data (requires `x-sveltekit-invalidated`). |
| `/portal/meters/{meter_id}/geo` | `GET` | Yes | Returns GPS coordinates for a meter. |
| `/portal/meters/{meter_id}/energy` | `GET` | Yes | Returns 30-minute interval power telemetry. |
| `/portal/dts?page={page}` | `GET` | Yes | Paginated list of Distribution Transformers (DTs). |
| `/portal/keys` | `GET` | Yes | Returns cryptographic HMAC signing secret for export. |
| `/portal/export?page=1` | `GET` | Yes (HMAC) | Bulk dump of all 403 meters with hierarchy & coordinates. |

---

## 4. Endpoint Details & Payload Structures

### 4.1 Meter Search (`GET /portal/meters/search`)
- **Query Parameters**:
  - `q` (string): Text query matching meter ID or serial number (case-insensitive substring).
  - `page` (integer): 1-indexed page number.
- **Server Pagination Quirk**: The endpoint accepts a `pageSize` query parameter but **completely ignores it**, consistently returning 20 records per page.
- **Response Format**:
  ```json
  {
    "data": [
      {
        "meterId": "J100000",
        "serialNo": "SE33962",
        "make": "HPL",
        "phaseType": "single",
        "installStatus": "Decommissioned",
        "dtCode": "DT-001"
      }
    ],
    "total": 403,
    "page": 1,
    "pageSize": 20
  }
  ```

---

### 4.2 Meter Detail (`GET /meters/{meter_id}`)
There is **no direct JSON endpoint** at `/portal/meters/{id}` (requesting it yields 404). Instead, meter nameplate and hierarchy details are embedded inside the server-rendered HTML page `/meters/{id}`.

#### Schema Inconsistency Anomaly:
Investigation revealed that different meters in the database have radically different internal representations:

1. **Legacy Format 1 (`parameterName` array)**:
   Found in older meters (e.g., `J100000`, `J100001`):
   ```json
   "detail": {
     "data": [
       {"parameterName": "Meter ID", "parameterValue": "J100000"},
       {"parameterName": "Serial No", "parameterValue": "SE33962"},
       {"parameterName": "Make", "parameterValue": "HPL"},
       {"parameterName": "Phase Type", "parameterValue": "single"},
       {"parameterName": "Installation Status", "parameterValue": "Decommissioned"},
       {"parameterName": "Installation Type", "parameterValue": "Whole Current"}
     ]
   }
   ```

2. **Legacy Format 2 (`classData` stringified JSON)**:
   Found in newer/migrated meters (e.g., `J100004`, `J100007`, `J100020`):
   ```json
   "detail": {
     "classData": "{\"installed_meter\":{\"MeterId\":\"J100004\",\"SerialNo\":\"SE65293\",\"Make\":\"Genus\",\"PhaseType\":\"single\",\"InstallationStatus\":\"Faulty\",\"InstallationType\":\"CT Operated\"}}"
   }
   ```
   *Notice the camelCase property naming (`MeterId` vs `Meter ID`, `SerialNo` vs `Serial No`).*

3. **HTML Presentation**:
   Both formats are rendered on the page using a standard `<dl>` definition list:
   - `<dt>` contains parameter label.
   - `<dd>` contains parameter value.
   - Breadcrumbs in `<nav class="...text-xs...">` define the grid hierarchy:
     `Zone › Circle › Division › Subdivision › Sub Station › Feeder › DT`.

---

### 4.3 Meter Geolocation (`GET /portal/meters/{meter_id}/geo`)
- **Response**:
  ```json
  {
    "data": {
      "latitude": "26.938961002479868",
      "longitude": "75.83095696146852"
    }
  }
  ```
- **Quirk**: Coordinates are encoded as **strings**, requiring conversion to floating-point numbers.

---

### 4.4 Meter Telemetry / Consumption (`GET /portal/meters/{meter_id}/energy`)
- **Response**:
  ```json
  {
    "data": [
      {
        "timestamp": "23/06/2026 23:30",
        "kwh": "48438.74",
        "kvah": "52313.84",
        "voltR": "226"
      },
      {
        "timestamp": "24/06/2026 00:00",
        "kwh": "48439.16",
        "kvah": "52314.29",
        "voltR": "229"
      }
    ]
  }
  ```
- **Quirks & Anomalies**:
  - **Date format**: Formatted as non-standard localized string `"DD/MM/YYYY HH:MM"`, without timezone information.
  - **Numeric types**: `kwh`, `kvah`, and `voltR` are strings of floats/integers rather than JSON numbers.
  - **Interval**: Fixed 30-minute interval spanning exactly 7 days (337 readings per meter).

---

### 4.5 Distribution Transformers (`GET /portal/dts?page={page}`)
- **Response**:
  ```json
  {
    "data": [
      {
        "code": "DT-001",
        "name": "Malviya Nagar DT 1",
        "feederCode": "F-001",
        "capacityKva": 100
      }
    ],
    "total": 40
  }
  ```
- Exactly 40 DT assets mapped across Jaipur distribution zones.

---

### 4.6 Bulk Export & Cryptographic HMAC Signature (`GET /portal/export`)
The client bundle `nodes/4.2Bgc2kUI.js` revealed a bulk export feature protected by HMAC authentication:

1. **Secret Retrieval**:
   - `GET /portal/keys` returns:
     ```json
     {"data": {"signingSecret": "I3dZPPf5CgTp7JyGNMI8i6z8LFR7TmSR"}}
     ```
2. **Signature Computation**:
   - Message to sign:
     ```
     GET\n/portal/export\npage=1\n<UNIX_TIMESTAMP>
     ```
   - Signature: HMAC-SHA256 hex digest using `signingSecret`.
3. **Execution**:
   - Request to `GET /portal/export?page=1` with headers:
     - `x-timestamp`: `<UNIX_TIMESTAMP>`
     - `x-signature`: `<HEX_DIGEST>`
4. **Data Yield**:
   Returns all **403 meters** at once in a single round-trip, complete with full hierarchical taxonomy (zone, circle, division, subdivision, substation, feeder, dt) and coordinates.

---

## 5. Summary of Portal Anomalies Handled by Adapter

| Portal Behavior | Legacy Issue | Adapter Solution in `flock-energy-api` |
| :--- | :--- | :--- |
| **CSRF Validation** | Blocks POSTs without origin headers (HTTP 403) | Enforces automatic `Origin` and `Referer` headers on all auth requests. |
| **Silent Expiration** | Session token expires after 1 hour (HTTP 401 or 302 redirect) | `UrjaPortalClient` intercepts 401/302, runs thread-safe re-login, and retries request. |
| **Two Detail Schemas** | Some meters use `classData` JSON string, others use `data` array | Unified parser inspects both AST branches + HTML `<dl>` to produce clean `MeterDetail`. |
| **String Numerics** | `kwh`, `kvah`, `voltR`, `lat`, `lng` returned as strings | Parsed and cast into type-safe Python/Pydantic `float` values. |
| **Localized Dates** | `timestamp` provided as `"DD/MM/YYYY HH:MM"` | Converted to ISO-8601 strings (`"YYYY-MM-DDTHH:MM:00Z"`). |
| **Fixed Pagination** | `search` ignores `pageSize` and caps at 20 | In-memory indexing layer supports arbitrary client-side `page_size` and offsets. |
| **Missing Search Filters**| Search endpoint only matches `q` string | Local index allows multi-attribute filtering (make, phase, status, DT, proximity). |
