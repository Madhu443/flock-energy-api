import os
from pydantic import BaseModel


class Settings(BaseModel):
    """Application configuration settings loaded from environment or defaults."""
    portal_base_url: str = os.getenv("URJA_PORTAL_URL", "https://urja-ops.flockenergy.tech").rstrip("/")
    portal_username: str = os.getenv("URJA_USERNAME", "operator@urja.local")
    portal_password: str = os.getenv("URJA_PASSWORD", "urja-ops-2026")
    http_timeout: float = float(os.getenv("HTTP_TIMEOUT", "20.0"))
    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))
    api_prefix: str = "/api/v1"
    title: str = "Flock Energy - Urja Meter Ops API"
    version: str = "1.0.0"
    description: str = (
        "Modern, type-safe REST API wrapper over the legacy Urja Meter Ops portal. "
        "Provides automated session management, normalized JSON schemas, "
        "hierarchy exploration, smart filtering, and consumption analytics."
    )


settings = Settings()
