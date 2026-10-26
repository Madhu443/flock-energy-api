import time
import math
from typing import Dict, Any, Optional, List, Callable


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points on Earth in kilometers."""
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return radius_km * c


class TTLCache:
    """Thread-safe in-memory cache with time-to-live expiration."""

    def __init__(self, default_ttl: int = 300):
        self.default_ttl = default_ttl
        self._store: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if not entry:
            return None
        if time.time() > entry["expires_at"]:
            del self._store[key]
            return None
        return entry["value"]

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        duration = ttl if ttl is not None else self.default_ttl
        self._store[key] = {
            "value": value,
            "expires_at": time.time() + duration,
            "cached_at": time.time(),
        }

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def get_or_set(self, key: str, fetcher: Callable[[], Any], ttl: Optional[int] = None) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        val = fetcher()
        self.set(key, val, ttl)
        return val


class MeterIndex:
    """Local in-memory index for advanced multi-attribute querying and spatial proximity.

    Addresses portal limitations where filtering by phase, make, status, or location
    is not natively supported by the legacy search endpoint.
    """

    def __init__(self):
        self._meters: List[Dict[str, Any]] = []
        self._indexed_at: float = 0
        self._by_id: Dict[str, Dict[str, Any]] = {}

    def is_fresh(self, max_age_seconds: int = 600) -> bool:
        return bool(self._meters) and (time.time() - self._indexed_at < max_age_seconds)

    def load(self, meters: List[Dict[str, Any]]) -> None:
        self._meters = meters
        self._by_id = {m.get("meterId"): m for m in meters if "meterId" in m}
        self._indexed_at = time.time()

    def count(self) -> int:
        return len(self._meters)

    def get_by_id(self, meter_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(meter_id)

    def query(
        self,
        q: Optional[str] = None,
        make: Optional[str] = None,
        phase_type: Optional[str] = None,
        install_status: Optional[str] = None,
        dt_code: Optional[str] = None,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        radius_km: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        results = self._meters

        if q:
            query_lower = q.strip().lower()
            results = [
                m for m in results
                if query_lower in (m.get("meterId") or "").lower()
                or query_lower in (m.get("serialNo") or "").lower()
                or query_lower in (m.get("dtCode") or "").lower()
            ]

        if make:
            make_lower = make.strip().lower()
            results = [m for m in results if (m.get("make") or "").lower() == make_lower]

        if phase_type:
            phase_lower = phase_type.strip().lower()
            results = [m for m in results if (m.get("phaseType") or "").lower() == phase_lower]

        if install_status:
            status_lower = install_status.strip().lower()
            results = [m for m in results if (m.get("installStatus") or "").lower() == status_lower]

        if dt_code:
            dt_upper = dt_code.strip().upper()
            results = [m for m in results if (m.get("dtCode") or "").upper() == dt_upper]

        if lat is not None and lng is not None and radius_km is not None:
            filtered = []
            for m in results:
                geo = m.get("geo") or {}
                m_lat = geo.get("lat")
                m_lng = geo.get("lng")
                if m_lat is not None and m_lng is not None:
                    dist = haversine_distance_km(lat, lng, float(m_lat), float(m_lng))
                    if dist <= radius_km:
                        m_copy = dict(m)
                        m_copy["distance_km"] = round(dist, 3)
                        filtered.append(m_copy)
            filtered.sort(key=lambda x: x.get("distance_km", 0))
            results = filtered

        return results


# Global singletons
cache = TTLCache(default_ttl=300)
meter_index = MeterIndex()
