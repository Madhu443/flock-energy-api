# Flock Energy — Urja Meter Ops REST API Wrapper

A modern, type-safe, production-ready REST API service wrapper around the legacy **Urja Meter Ops** portal (`https://urja-ops.flockenergy.tech`).

This service automates authentication, session lifecycle, and cryptographic HMAC requests against the legacy portal, transforms unstructured HTML and inconsistent JSON data into clean normalized schemas, and exposes high-performance REST endpoints alongside an interactive operations dashboard.

---

## 📑 Table of Contents

- [Quick Start & Installation](#-quick-start--installation)
- [System Architecture](#-system-architecture)
- [API Endpoints & Sample Requests](#-api-endpoints--sample-requests)
- [Protocol Discovery (PROTOCOL.md)](#-protocol-discovery)
- [Interactive Documentation & Modern Dashboard](#-interactive-documentation--modern-dashboard)
- [Key Features & Implemented Extensions](#-key-features--implemented-extensions)
- [Engineering Notes & Trade-Offs](#-engineering-notes--trade-offs)
- [Reflection (REFLECTION.md)](#-reflection)
- [Testing](#-testing)

---

## 🚀 Quick Start & Installation

### Prerequisites
- **Python**: 3.10+ (tested on Python 3.14)
- **Git**

### 1. Clone & Setup Environment
```bash
git clone <repo-url> flock-energy-api
cd flock-energy-api

# Create and activate virtual environment (optional but recommended)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration (Optional)
The service operates out of the box with default credentials for the take-home instance. You can override settings via environment variables:
```bash
# Optional overrides:
export URJA_PORTAL_URL="https://urja-ops.flockenergy.tech"
export URJA_USERNAME="operator@urja.local"
export URJA_PASSWORD="urja-ops-2026"
export HTTP_TIMEOUT=20.0
export CACHE_TTL_SECONDS=300
```

### 3. Run the API Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- **REST API Base URL**: `http://localhost:8000/api/v1`
- **Interactive Swagger UI**: `http://localhost:8000/docs`
- **ReDoc Documentation**: `http://localhost:8000/redoc`
- **OpenAPI Schema**: `http://localhost:8000/openapi.json`
- **Modern Web Dashboard**: `http://localhost:8000/` or `http://localhost:8000/dashboard`

---

## 🏛 System Architecture

```
flock-energy-api/
│
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI application, route handlers & dependency injection
│   ├── client.py        # Legacy Urja Portal adapter, CSRF handler, HMAC signing & scrapers
│   ├── models.py        # Pydantic V2 type-safe schemas & validation models
│   ├── config.py        # Centralized configuration & environment loader
│   ├── cache.py         # Thread-safe in-memory TTL cache & Haversine spatial indexer
│   └── static/
│       └── index.html   # Modern responsive operations dashboard (Tailwind + Chart.js)
│
├── tests/
│   ├── __init__.py
│   ├── test_client.py   # Unit tests for client adapter, HMAC signing & spatial queries
│   └── test_api.py      # Integration tests for FastAPI endpoints
│
├── openapi.json         # Exported OpenAPI 3.1 specification for downstream clients
├── PROTOCOL.md          # Comprehensive legacy reverse-engineering write-up
├── REFLECTION.md        # Detailed answers to the 5 take-home reflection prompts
├── requirements.txt     # Python runtime dependencies
├── export_openapi.py    # Schema exporter utility
└── .gitignore
```

---

## 📡 API Endpoints & Sample Requests

### 1. Health & Status
Checks connectivity to the legacy portal and returns active session status.
```bash
curl -X GET "http://localhost:8000/api/v1/health"
```
**Response (200 OK):**
```json
{
  "status": "healthy",
  "portal_connected": true,
  "session_authenticated": true,
  "portal_base_url": "https://urja-ops.flockenergy.tech",
  "version": "1.0.0",
  "uptime_cached_meters": 403
}
```

---

### 2. Authentication
Explicitly authenticates against the Urja portal (note: the API also handles transparent re-authentication automatically).
```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"username": "operator@urja.local", "password": "urja-ops-2026"}'
```

---

### 3. List Smart Meters
Supports text search (`q`), pagination (`page`, `page_size`), multi-attribute filtering (`make`, `phase_type`, `install_status`, `dt_code`), and spatial queries (`lat`, `lng`, `radius_km`).
```bash
# Query active single-phase meters manufactured by HPL
curl -X GET "http://localhost:8000/api/v1/meters?make=HPL&phase_type=single&install_status=Active&page=1&page_size=5"
```
**Response (200 OK):**
```json
{
  "data": [
    {
      "meter_id": "J100008",
      "serial_number": "SE53702",
      "make": "HPL",
      "phase_type": "single",
      "install_status": "Active",
      "dt_code": "DT-001",
      "location": {
        "latitude": 26.938961,
        "longitude": 75.830956
      }
    }
  ],
  "total": 124,
  "page": 1,
  "page_size": 5,
  "total_pages": 25
}
```

#### Spatial Proximity Query (Optional Extension):
Find all smart meters within 2.5 km of Malviya Nagar coordinates:
```bash
curl -X GET "http://localhost:8000/api/v1/meters?lat=26.9389&lng=75.8309&radius_km=2.5"
```

---

### 4. Get Meter Details
Retrieves complete nameplate specifications, normalized hierarchy, and GPS coordinates for a specific meter.
```bash
curl -X GET "http://localhost:8000/api/v1/meters/J100000"
```
**Response (200 OK):**
```json
{
  "meter_id": "J100000",
  "serial_number": "SE33962",
  "make": "HPL",
  "phase_type": "single",
  "install_status": "Decommissioned",
  "install_type": "Whole Current",
  "dt_code": "DT-001",
  "build": "legacy",
  "location": {
    "latitude": 26.938961,
    "longitude": 75.830956
  },
  "hierarchy": {
    "zone": { "name": "Jaipur Zone 1", "code": "Z-01" },
    "circle": { "name": "Circle 1", "code": "C-01" },
    "division": { "name": "Division 1", "code": "D-01" },
    "subdivision": { "name": "Subdivision 1", "code": "SD-01" },
    "substation": { "name": "Substation 1", "code": "SS-01" },
    "feeder": { "name": "Feeder 1", "code": "F-001" },
    "dt": { "name": "Malviya Nagar DT 1", "code": "DT-001" },
    "breadcrumbs": [
      "Jaipur Zone 1 (Z-01)",
      "Circle 1 (C-01)",
      "Division 1 (D-01)",
      "Subdivision 1 (SD-01)",
      "Substation 1 (SS-01)",
      "Feeder 1 (F-001)",
      "Malviya Nagar DT 1 (DT-001)"
    ]
  },
  "raw_parameters": {
    "Meter ID": "J100000",
    "Serial No": "SE33962",
    "Make": "HPL",
    "Phase Type": "single",
    "Installation Status": "Decommissioned",
    "Installation Type": "Whole Current"
  }
}
```

---

### 5. Get Meter Consumption & Telemetry
Retrieves 30-minute interval readings converted to ISO-8601 timestamps and typed floats, alongside statistical aggregations (`kwh_delta`, `avg_voltage_r`, `min_voltage_r`, `max_voltage_r`).
```bash
curl -X GET "http://localhost:8000/api/v1/meters/J100000/consumption"
```
**Response (200 OK):**
```json
{
  "meter_id": "J100000",
  "summary": {
    "reading_count": 337,
    "earliest_timestamp": "2026-06-23T23:30:00Z",
    "latest_timestamp": "2026-06-30T23:30:00Z",
    "latest_kwh": 48580.45,
    "kwh_delta": 141.71,
    "avg_voltage_r": 228.4,
    "min_voltage_r": 215.0,
    "max_voltage_r": 242.0
  },
  "readings": [
    {
      "timestamp": "23/06/2026 23:30",
      "iso_timestamp": "2026-06-23T23:30:00Z",
      "kwh": 48438.74,
      "kvah": 52313.84,
      "voltage_r": 226.0
    },
    {
      "timestamp": "24/06/2026 00:00",
      "iso_timestamp": "2026-06-24T00:00:00Z",
      "kwh": 48439.16,
      "kvah": 52314.29,
      "voltage_r": 229.0
    }
  ]
}
```

---

### 6. Network Hierarchy Tree (Optional Extension)
Reconstructs the hierarchical topology from Zone down to Distribution Transformers and meters.
```bash
curl -X GET "http://localhost:8000/api/v1/hierarchy"
```
**Response (200 OK):**
```json
{
  "total_zones": 2,
  "total_meters": 403,
  "total_dts": 40,
  "tree": [
    {
      "level": "zone",
      "code": "Z-01",
      "name": "Jaipur Zone 1",
      "meter_count": 215,
      "children": [
        {
          "level": "circle",
          "code": "C-01",
          "name": "Circle 1",
          "meter_count": 215,
          "children": []
        }
      ]
    }
  ]
}
```

---

### 7. Distribution Transformers
```bash
curl -X GET "http://localhost:8000/api/v1/transformers?page=1"
```

---

### 8. Bulk Dataset Export
HMAC-authenticated extraction returning all 403 meters in a single call.
```bash
curl -X GET "http://localhost:8000/api/v1/export"
```

---

## 🔍 Protocol Discovery

The legacy Urja portal was thoroughly reverse-engineered during Step 1. All findings regarding SvelteKit CSRF origin restrictions, session token cookies, dual legacy detail schemas (`classData` vs `parameterName`), localized date formats, and the cryptographic HMAC-signed bulk export are documented in:

👉 **[PROTOCOL.md](PROTOCOL.md)**

---

## 🖥 Interactive Documentation & Modern Dashboard

- **OpenAPI Schema (JSON)**: Available at [`/openapi.json`](openapi.json) and exported to [`openapi.json`](openapi.json).
- **Swagger UI**: Visit `http://localhost:8000/docs` in your browser for interactive testing.
- **Modern Web Dashboard**: Visit `http://localhost:8000/` or `http://localhost:8000/dashboard` for a rich operations console featuring:
  - KPI summary metrics (total fleet, active ratio, transformers, health status)
  - Search and multi-attribute dropdown filters
  - Detailed modal inspection with nameplate specs and OpenStreetMap links
  - Interactive Chart.js time-series consumption curves (Active Energy kWh & Voltage V)
  - Visual Network Hierarchy Tree explorer
  - Haversine Spatial Proximity Finder

---

## ⚙️ Key Features & Implemented Extensions

1. **Automatic Session Recovery & Re-Authentication**:
   - The client maintains session persistence with `__Secure-better-auth.session_token`.
   - Thread-safe interceptor catches HTTP 401s or 302 redirects to `/login` and re-authenticates on the fly without failing client requests.
2. **In-Memory TTL Caching & Local Query Layer**:
   - Upstream portal responses are cached in a thread-safe `TTLCache`.
   - An in-memory `MeterIndex` enables multi-attribute filtering (make, phase type, status, DT code) and Haversine spatial radius searches that the legacy portal's search endpoint cannot perform.
3. **Dual Legacy Data Normalization**:
   - Parses both older `parameterName` array structures and newer `classData` stringified JSON objects into unified, strongly typed Pydantic models.
4. **Cryptographic HMAC Bulk Extraction**:
   - Automatically queries `/portal/keys` and calculates HMAC-SHA256 signatures (`x-timestamp` and `x-signature`) for bulk exports.
5. **Network Hierarchy Reconstruction**:
   - Assembles the complete utility hierarchy from Zone down to DT and meters.
6. **Modern Web UI**:
   - Standalone Tailwind + Chart.js dashboard built directly into the service.

---

## 📐 Engineering Notes & Trade-Offs

### Assumptions Made
1. **Read-Only System**: The portal is treated as an upstream telemetry store.
2. **In-Memory Scale**: The fleet size (403 meters, 40 DTs) comfortably resides in memory (< 2 MB footprint), allowing sub-millisecond query execution without external database infrastructure.
3. **IST Timezone**: Localized timestamps `"DD/MM/YYYY HH:MM"` were normalized to standard ISO-8601 strings.

### Architectural Trade-offs
- **In-Memory Index vs External Database (Postgres/Redis)**:
  - *Trade-off*: An in-memory Python index was chosen for zero-dependency simplicity and immediate local execution.
  - *Scale Boundary*: This approach thrives up to ~50,000 meters. For a utility managing 1,000,000+ meters, an external PostgreSQL database with PostGIS spatial indices and a background worker (Celery/Temporal) would be required to avoid high process memory usage and $O(N)$ linear scans.
- **Synchronous httpx vs Async Client**:
  - *Trade-off*: Synchronous `httpx.Client` was selected inside FastAPI threadpool handlers for reliable lock-based re-authentication and straightforward session sharing. For extreme concurrent throughput, converting to `httpx.AsyncClient` with `asyncio.Lock` would yield higher I/O concurrency.

### Intentional Omissions
- **Database Migrations / ORM**: Omitted to keep the take-home repo self-contained with zero external database dependencies.
- **Write Actions / Telemetry Push**: The portal offers no mutation APIs (e.g. meter remote disconnects), so mutation endpoints were intentionally omitted to preserve read-only safety.

---

## 💭 Reflection

Detailed answers addressing assumptions, challenges, mistakes, future enhancements, and critical self-review are documented in:

👉 **[REFLECTION.md](REFLECTION.md)**

---

## 🧪 Testing

The test suite validates both unit-level client behaviors (caching, HMAC signing, Haversine distance, parsing) and integration-level FastAPI endpoints against the live Urja portal:

```bash
# Run test suite
python -m pytest -v
```

**Test Results:**
```
tests/test_api.py::test_health_endpoint PASSED                           [  6%]
tests/test_api.py::test_dashboard_ui PASSED                              [ 13%]
tests/test_api.py::test_auth_login PASSED                                [ 20%]
tests/test_api.py::test_auth_bad_credentials PASSED                      [ 26%]
tests/test_api.py::test_list_meters PASSED                               [ 33%]
tests/test_api.py::test_get_meter_detail PASSED                          [ 40%]
tests/test_api.py::test_get_meter_consumption PASSED                     [ 46%]
tests/test_api.py::test_get_transformers PASSED                          [ 53%]
tests/test_api.py::test_meter_not_found PASSED                           [ 60%]
tests/test_api.py::test_network_hierarchy PASSED                         [ 66%]
tests/test_client.py::test_haversine_distance PASSED                     [ 73%]
tests/test_client.py::test_ttl_cache PASSED                              [ 80%]
tests/test_client.py::test_meter_index_filtering PASSED                  [ 86%]
tests/test_client.py::test_live_portal_client_auth_and_search PASSED     [ 93%]
tests/test_client.py::test_live_portal_not_found PASSED                  [100%]

======================= 15 passed in 6.34s =======================
```
