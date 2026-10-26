import os
import math
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.models import (
    LoginRequest,
    LoginResponse,
    UserProfile,
    MeterListResponse,
    MeterListItem,
    MeterDetail,
    MeterConsumptionResponse,
    TransformerListResponse,
    DistributionTransformer,
    HierarchyTreeResponse,
    HealthResponse,
    GeoLocation,
)
from app.client import (
    UrjaPortalClient,
    UrjaAuthenticationError,
    UrjaNotFoundError,
    UrjaPortalClientError,
)
from app.cache import cache, meter_index


app = FastAPI(
    title=settings.title,
    version=settings.version,
    description=settings.description,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Enable CORS for external API consumers and frontend dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared client instance (transparently persists cookies and auto-reauthenticates)
portal_client = UrjaPortalClient()


def get_client() -> UrjaPortalClient:
    """Dependency injector for portal client."""
    return portal_client


def ensure_index_populated(client: UrjaPortalClient) -> None:
    """Ensure the local query index is populated from the portal bulk export."""
    if not meter_index.is_fresh(max_age_seconds=settings.cache_ttl_seconds):
        try:
            meters = client.export_all_meters()
            meter_index.load(meters)
        except Exception:
            # Fallback gracefully if bulk export is temporarily unavailable
            pass


# --- Static Files / Modern Web Dashboard ---

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", tags=["Dashboard & UI"], include_in_schema=False)
@app.get("/dashboard", tags=["Dashboard & UI"], response_class=HTMLResponse)
def read_dashboard():
    """Serves the modern, interactive web client and operations dashboard."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse(
        "<html><body><h1>Flock Energy - Urja Meter Ops API</h1>"
        "<p>API is active. Visit <a href='/docs'>/docs</a> for OpenAPI Interactive Documentation.</p>"
        "</body></html>"
    )


# --- Health & Status ---

@app.get("/api/v1/health", response_model=HealthResponse, tags=["System Health"])
def health_check(client: UrjaPortalClient = Depends(get_client)):
    """Check connectivity to the upstream Urja portal and report session status."""
    try:
        client.ensure_authenticated()
        is_conn = True
    except Exception:
        is_conn = False

    return HealthResponse(
        status="healthy" if is_conn else "degraded",
        portal_connected=is_conn,
        session_authenticated=client.is_authenticated,
        portal_base_url=client.base_url,
        version=settings.version,
        uptime_cached_meters=meter_index.count(),
    )


# --- Authentication ---

@app.post("/api/v1/auth/login", response_model=LoginResponse, tags=["Authentication"])
def login(payload: LoginRequest, client: UrjaPortalClient = Depends(get_client)):
    """Authenticate with the legacy Urja portal.

    Maintains session tokens and validates credentials against the portal's SvelteKit session layer.
    """
    try:
        success = client.login(username=payload.username, password=payload.password)
        if success:
            return LoginResponse(
                status="authenticated",
                message="Successfully authenticated with Urja portal",
                user=UserProfile(name="Ops Desk", email=payload.username),
            )
    except UrjaAuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Portal connection error: {str(e)}",
        )


# --- Meters Endpoints ---

@app.get("/api/v1/meters", response_model=MeterListResponse, tags=["Meters"])
def list_meters(
    q: Optional[str] = Query(None, description="Search query string matching meter ID, serial number, or DT code"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    make: Optional[str] = Query(None, description="Filter by meter manufacturer (e.g., HPL, Genus, Secure)"),
    phase_type: Optional[str] = Query(None, description="Filter by phase type (e.g., single, three)"),
    install_status: Optional[str] = Query(None, description="Filter by installation status (Active, Faulty, Decommissioned)"),
    dt_code: Optional[str] = Query(None, description="Filter by Distribution Transformer code (e.g., DT-001)"),
    lat: Optional[float] = Query(None, description="Latitude for spatial proximity filtering"),
    lng: Optional[float] = Query(None, description="Longitude for spatial proximity filtering"),
    radius_km: Optional[float] = Query(None, description="Search radius in kilometers around (lat, lng)"),
    fresh: bool = Query(False, description="Bypass in-memory cache and fetch directly from upstream portal"),
    client: UrjaPortalClient = Depends(get_client),
):
    """Retrieve a list of smart meters.

    Supports:
    - Search by meter ID or serial number
    - Multi-attribute filtering (make, phase type, installation status, DT code)
    - Geospatial proximity queries using Haversine distance formula
    - Pagination with page and page_size controls
    """
    has_advanced_filters = any([
        make, phase_type, install_status, dt_code,
        (lat is not None and lng is not None and radius_km is not None)
    ])

    if has_advanced_filters or fresh:
        ensure_index_populated(client)

    # If advanced filters are applied, use local query index
    if has_advanced_filters and meter_index.count() > 0:
        filtered = meter_index.query(
            q=q,
            make=make,
            phase_type=phase_type,
            install_status=install_status,
            dt_code=dt_code,
            lat=lat,
            lng=lng,
            radius_km=radius_km,
        )
        total = len(filtered)
        total_pages = max(1, math.ceil(total / page_size))
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_items = filtered[start_idx:end_idx]

        items = [
            MeterListItem(
                meter_id=m.get("meterId"),
                serial_number=m.get("serialNo") or "UNKNOWN",
                make=m.get("make") or "UNKNOWN",
                phase_type=m.get("phaseType") or "UNKNOWN",
                install_status=m.get("installStatus") or "UNKNOWN",
                dt_code=m.get("dtCode"),
                location=GeoLocation(
                    latitude=m.get("geo", {}).get("lat"),
                    longitude=m.get("geo", {}).get("lng"),
                ) if m.get("geo") else None,
            )
            for m in page_items
        ]

        return MeterListResponse(
            data=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    # Standard query through portal search endpoint with caching
    cache_key = f"meters:search:{q or ''}:{page}:{page_size}"
    if not fresh:
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result

    try:
        raw_res = client.search_meters(q=q or "", page=page)
        total = raw_res.get("total", 0)
        total_pages = max(1, math.ceil(total / raw_res.get("pageSize", 20)))

        items = [
            MeterListItem(
                meter_id=m.get("meterId"),
                serial_number=m.get("serialNo") or "UNKNOWN",
                make=m.get("make") or "UNKNOWN",
                phase_type=m.get("phaseType") or "UNKNOWN",
                install_status=m.get("installStatus") or "UNKNOWN",
                dt_code=m.get("dtCode"),
            )
            for m in raw_res.get("data", [])
        ]

        result = MeterListResponse(
            data=items,
            total=total,
            page=page,
            page_size=raw_res.get("pageSize", 20),
            total_pages=total_pages,
        )

        cache.set(cache_key, result, ttl=settings.cache_ttl_seconds)
        return result

    except UrjaPortalClientError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Portal error retrieving meters: {str(e)}",
        )


@app.get("/api/v1/meters/{meter_id}", response_model=MeterDetail, tags=["Meters"])
def get_meter_details(
    meter_id: str,
    fresh: bool = Query(False, description="Bypass cache and force scrape fresh page"),
    client: UrjaPortalClient = Depends(get_client),
):
    """Retrieve full details for a specific smart meter.

    Scrapes the legacy HTML portal page, parses nameplate parameters,
    normalizes inconsistent legacy schemas (classData vs data array),
    resolves breadcrumbs hierarchy, and attaches GPS coordinates.
    """
    cache_key = f"meter:detail:{meter_id}"
    if not fresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    try:
        detail = client.get_meter_details(meter_id)
        result = MeterDetail(**detail)
        cache.set(cache_key, result, ttl=settings.cache_ttl_seconds)
        return result
    except UrjaNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except UrjaPortalClientError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error scraping meter details: {str(e)}",
        )


@app.get("/api/v1/meters/{meter_id}/consumption", response_model=MeterConsumptionResponse, tags=["Consumption"])
def get_meter_consumption(
    meter_id: str,
    fresh: bool = Query(False, description="Bypass cache and retrieve fresh readings"),
    client: UrjaPortalClient = Depends(get_client),
):
    """Retrieve interval consumption history and statistical analytics for a meter.

    Normalizes 30-minute interval readings into ISO-8601 timestamps, converts
    string values to typed floats, and generates consumption summary statistics.
    """
    cache_key = f"meter:consumption:{meter_id}"
    if not fresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    try:
        consumption_data = client.get_meter_consumption(meter_id)
        result = MeterConsumptionResponse(**consumption_data)
        cache.set(cache_key, result, ttl=settings.cache_ttl_seconds)
        return result
    except UrjaNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except UrjaPortalClientError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error retrieving consumption: {str(e)}",
        )


# --- Transformers Endpoints ---

@app.get("/api/v1/transformers", response_model=TransformerListResponse, tags=["Infrastructure"])
def list_transformers(
    page: int = Query(1, ge=1, description="Page number"),
    fresh: bool = Query(False, description="Bypass cache"),
    client: UrjaPortalClient = Depends(get_client),
):
    """Retrieve paginated Distribution Transformers (DTs) from the utility infrastructure."""
    cache_key = f"transformers:page:{page}"
    if not fresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    try:
        raw = client.get_dts(page=page)
        data = [
            DistributionTransformer(
                code=dt.get("code"),
                name=dt.get("name"),
                feeder_code=dt.get("feederCode"),
                capacity_kva=dt.get("capacityKva"),
            )
            for dt in raw.get("data", [])
        ]
        total = raw.get("total", len(data))
        total_pages = max(1, math.ceil(total / 20))

        result = TransformerListResponse(
            data=data,
            total=total,
            page=page,
            total_pages=total_pages,
        )
        cache.set(cache_key, result, ttl=settings.cache_ttl_seconds)
        return result
    except UrjaPortalClientError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error retrieving transformers: {str(e)}",
        )


# --- Network Hierarchy Tree (Optional Extension) ---

@app.get("/api/v1/hierarchy", response_model=HierarchyTreeResponse, tags=["Hierarchy"])
def get_network_hierarchy(
    fresh: bool = Query(False, description="Bypass cache and reconstruct network hierarchy"),
    client: UrjaPortalClient = Depends(get_client),
):
    """Retrieve the fully reconstructed utility network hierarchy tree.

    Organizes assets systematically from Zone -> Circle -> Division ->
    Subdivision -> Substation -> Feeder -> Distribution Transformer with meter counts.
    """
    cache_key = "network:hierarchy:tree"
    if not fresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    try:
        ensure_index_populated(client)
        meters = meter_index._meters if meter_index.count() > 0 else client.export_all_meters()
        tree_data = client.build_network_hierarchy(meters=meters)
        result = HierarchyTreeResponse(**tree_data)
        cache.set(cache_key, result, ttl=settings.cache_ttl_seconds)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error building hierarchy tree: {str(e)}",
        )


# --- Full Dataset Export ---

@app.get("/api/v1/export", tags=["Bulk Export"])
def export_all_meters(
    client: UrjaPortalClient = Depends(get_client),
):
    """Retrieve full bulk dump of all smart meters via HMAC-authenticated export.

    Returns the complete grid catalog with full hierarchy nodes and GPS coordinates.
    """
    try:
        meters = client.export_all_meters()
        meter_index.load(meters)
        return {
            "total": len(meters),
            "data": meters,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error performing export: {str(e)}",
        )
