from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field


# --- Auth Models ---

class LoginRequest(BaseModel):
    """Credentials payload for manual authentication."""
    username: str = Field(..., description="Operator email or username", json_schema_extra={"example": "operator@urja.local"})
    password: str = Field(..., description="Account password", json_schema_extra={"example": "urja-ops-2026"})


class UserProfile(BaseModel):
    """User profile information returned from portal session."""
    name: str = Field(default="Ops Desk", json_schema_extra={"example": "Ops Desk"})
    email: str = Field(default="operator@urja.local", json_schema_extra={"example": "operator@urja.local"})


class LoginResponse(BaseModel):
    """Response returned upon authentication."""
    status: str = Field(default="authenticated", json_schema_extra={"example": "authenticated"})
    message: str = Field(..., json_schema_extra={"example": "Successfully authenticated with Urja portal"})
    user: Optional[UserProfile] = None


# --- Geolocation & Hierarchy Models ---

class GeoLocation(BaseModel):
    """Geographic coordinates of a meter."""
    latitude: Optional[float] = Field(None, description="Latitude in decimal degrees", json_schema_extra={"example": 26.938961})
    longitude: Optional[float] = Field(None, description="Longitude in decimal degrees", json_schema_extra={"example": 75.830956})


class HierarchyNodeDetail(BaseModel):
    """Specific level node in the utility grid hierarchy."""
    name: str = Field(..., json_schema_extra={"example": "Jaipur Zone 1"})
    code: Optional[str] = Field(None, json_schema_extra={"example": "Z-01"})


class MeterHierarchy(BaseModel):
    """Utility network hierarchy for a meter."""
    zone: Optional[Union[str, HierarchyNodeDetail]] = Field(None, json_schema_extra={"example": "Jaipur Zone 1 (Z-01)"})
    circle: Optional[Union[str, HierarchyNodeDetail]] = Field(None, json_schema_extra={"example": "Circle 1 (C-01)"})
    division: Optional[Union[str, HierarchyNodeDetail]] = Field(None, json_schema_extra={"example": "Division 1 (D-01)"})
    subdivision: Optional[Union[str, HierarchyNodeDetail]] = Field(None, json_schema_extra={"example": "Subdivision 1 (SD-01)"})
    substation: Optional[Union[str, HierarchyNodeDetail]] = Field(None, json_schema_extra={"example": "Substation 1 (SS-01)"})
    feeder: Optional[Union[str, HierarchyNodeDetail]] = Field(None, json_schema_extra={"example": "Feeder 1 (F-001)"})
    dt: Optional[Union[str, HierarchyNodeDetail]] = Field(None, json_schema_extra={"example": "Malviya Nagar DT 1 (DT-001)"})
    breadcrumbs: Optional[List[str]] = Field(default_factory=list, description="Ordered path from Zone to DT")


# --- Meter Models ---

class MeterListItem(BaseModel):
    """Summary representation of a smart meter in listing endpoints."""
    meter_id: str = Field(..., description="Unique meter identifier", json_schema_extra={"example": "J100000"})
    serial_number: str = Field(..., description="Manufacturer serial number", json_schema_extra={"example": "SE33962"})
    make: str = Field(..., description="Manufacturer make (HPL, Genus, Secure, etc.)", json_schema_extra={"example": "HPL"})
    phase_type: str = Field(..., description="Single-phase or three-phase", json_schema_extra={"example": "single"})
    install_status: str = Field(..., description="Installation status (Active, Faulty, Decommissioned)", json_schema_extra={"example": "Active"})
    dt_code: Optional[str] = Field(None, description="Distribution Transformer code", json_schema_extra={"example": "DT-001"})
    location: Optional[GeoLocation] = None


class MeterListResponse(BaseModel):
    """Paginated list of smart meters."""
    data: List[MeterListItem]
    total: int = Field(..., description="Total matching meters across the grid", json_schema_extra={"example": 403})
    page: int = Field(default=1, description="Current page number", json_schema_extra={"example": 1})
    page_size: int = Field(default=20, description="Items per page", json_schema_extra={"example": 20})
    total_pages: int = Field(default=1, description="Total number of pages", json_schema_extra={"example": 21})


class MeterDetail(BaseModel):
    """Detailed record of a smart meter including nameplate, location, and hierarchy."""
    meter_id: str = Field(..., json_schema_extra={"example": "J100000"})
    serial_number: str = Field(..., json_schema_extra={"example": "SE33962"})
    make: str = Field(..., json_schema_extra={"example": "HPL"})
    phase_type: str = Field(..., json_schema_extra={"example": "single"})
    install_status: str = Field(..., json_schema_extra={"example": "Decommissioned"})
    install_type: Optional[str] = Field(None, json_schema_extra={"example": "Whole Current"})
    dt_code: Optional[str] = Field(None, json_schema_extra={"example": "DT-001"})
    build: Optional[str] = Field(None, json_schema_extra={"example": "legacy"})
    location: Optional[GeoLocation] = None
    hierarchy: Optional[MeterHierarchy] = None
    raw_parameters: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="Normalized key-value pairs of all nameplate attributes"
    )


# --- Consumption Models ---

class ConsumptionReading(BaseModel):
    """A single interval consumption reading."""
    timestamp: str = Field(..., description="Original timestamp as provided by meter ops", json_schema_extra={"example": "24/06/2026 00:00"})
    iso_timestamp: Optional[str] = Field(None, description="ISO 8601 formatted timestamp", json_schema_extra={"example": "2026-06-24T00:00:00Z"})
    kwh: Optional[float] = Field(None, description="Cumulative active energy in kWh", json_schema_extra={"example": 48439.16})
    kvah: Optional[float] = Field(None, description="Cumulative apparent energy in kVAh", json_schema_extra={"example": 52314.29})
    voltage_r: Optional[float] = Field(None, description="R-Phase voltage in Volts", json_schema_extra={"example": 229.0})


class ConsumptionSummary(BaseModel):
    """Statistical summary over the retrieved consumption window."""
    reading_count: int = Field(..., description="Number of readings returned", json_schema_extra={"example": 337})
    earliest_timestamp: Optional[str] = Field(None, json_schema_extra={"example": "2026-06-23T23:30:00Z"})
    latest_timestamp: Optional[str] = Field(None, json_schema_extra={"example": "2026-06-30T23:30:00Z"})
    latest_kwh: Optional[float] = Field(None, json_schema_extra={"example": 48580.45})
    kwh_delta: Optional[float] = Field(None, description="Total active energy consumed over window", json_schema_extra={"example": 141.71})
    avg_voltage_r: Optional[float] = Field(None, json_schema_extra={"example": 228.4})
    min_voltage_r: Optional[float] = Field(None, json_schema_extra={"example": 215.0})
    max_voltage_r: Optional[float] = Field(None, json_schema_extra={"example": 242.0})


class MeterConsumptionResponse(BaseModel):
    """Consumption history and analytics for a smart meter."""
    meter_id: str = Field(..., json_schema_extra={"example": "J100000"})
    summary: ConsumptionSummary
    readings: List[ConsumptionReading]


# --- Transformer Models ---

class DistributionTransformer(BaseModel):
    """Distribution Transformer (DT) infrastructure node."""
    code: str = Field(..., json_schema_extra={"example": "DT-001"})
    name: str = Field(..., json_schema_extra={"example": "Malviya Nagar DT 1"})
    feeder_code: str = Field(..., json_schema_extra={"example": "F-001"})
    capacity_kva: int = Field(..., json_schema_extra={"example": 100})


class TransformerListResponse(BaseModel):
    """Paginated list of Distribution Transformers."""
    data: List[DistributionTransformer]
    total: int = Field(..., json_schema_extra={"example": 40})
    page: int = Field(default=1, json_schema_extra={"example": 1})
    total_pages: int = Field(default=1, json_schema_extra={"example": 2})


# --- Hierarchy Tree Models ---

class HierarchyTreeNode(BaseModel):
    """Hierarchical node representing an element in the power grid tree."""
    level: str = Field(..., description="Level type: zone, circle, division, subdivision, substation, feeder, dt, meter", json_schema_extra={"example": "zone"})
    code: str = Field(..., json_schema_extra={"example": "Z-01"})
    name: str = Field(..., json_schema_extra={"example": "Jaipur Zone 1"})
    children: List["HierarchyTreeNode"] = Field(default_factory=list)
    meter_count: int = Field(default=0, description="Total smart meters under this subtree")


class HierarchyTreeResponse(BaseModel):
    """Full organized tree of the electricity distribution grid."""
    total_zones: int
    total_meters: int
    total_dts: int
    tree: List[HierarchyTreeNode]


# --- Health & Metadata Models ---

class HealthResponse(BaseModel):
    """Service health and upstream connectivity status."""
    status: str = Field(default="healthy", json_schema_extra={"example": "healthy"})
    portal_connected: bool = Field(..., description="Whether legacy portal responds")
    session_authenticated: bool = Field(..., description="Whether an active session is established")
    portal_base_url: str
    version: str = "1.0.0"
    uptime_cached_meters: int = Field(default=0)
