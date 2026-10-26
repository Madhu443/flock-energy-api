import re
import json
import time
import hmac
import hashlib
import threading
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import httpx
from bs4 import BeautifulSoup

from app.config import settings


class UrjaPortalClientError(Exception):
    """Base exception for Urja portal errors."""
    pass


class UrjaAuthenticationError(UrjaPortalClientError):
    """Authentication or credential failure."""
    pass


class UrjaNotFoundError(UrjaPortalClientError):
    """Requested resource (meter/transformer) was not found."""
    pass


class UrjaPortalClient:
    """HTTP client and scraper adapter for the legacy Urja Meter Ops portal.

    Handles:
    - Session lifecycle, cookies, and SvelteKit CSRF origin requirements.
    - Automatic transparent re-authentication on session expiration (401 / redirect).
    - HTML scraping of meter detail pages using BeautifulSoup4.
    - Normalization of legacy data formats (classData JSON strings vs data parameter lists).
    - Cryptographic HMAC-signed bulk data exports.
    - Transformation of raw string-encoded energy intervals into ISO-8601 typed floats.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = (base_url or settings.portal_base_url).rstrip("/")
        self.username = username or settings.portal_username
        self.password = password or settings.portal_password
        self.timeout = timeout or settings.http_timeout

        # Persistent HTTP client storing session cookies
        self._client = httpx.Client(
            follow_redirects=False,
            timeout=self.timeout,
            headers={
                "User-Agent": "FlockEnergy-API-Adapter/1.0",
                "Accept": "*/*",
            }
        )
        self._auth_lock = threading.Lock()
        self._is_authenticated = False
        self._cached_signing_secret: Optional[str] = None

    @property
    def is_authenticated(self) -> bool:
        return self._is_authenticated

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """Authenticate with the legacy portal using email and password.

        SvelteKit requires Origin and Referer headers to pass CSRF validation.
        """
        user = username or self.username
        pwd = password or self.password

        login_url = f"{self.base_url}/login"
        headers = {
            "Origin": self.base_url,
            "Referer": login_url,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        payload = {
            "email": user,
            "password": pwd,
        }

        try:
            resp = self._client.post(login_url, data=payload, headers=headers)
        except httpx.RequestError as exc:
            raise UrjaPortalClientError(f"Network error connecting to Urja portal: {exc}") from exc

        # Check for CSRF rejection
        if resp.status_code == 403:
            raise UrjaAuthenticationError("Portal rejected login with 403: Cross-site POST forbidden")

        # Check response body for SvelteKit action response
        if resp.status_code in (200, 302, 303):
            # Inspect body for failure payload
            try:
                data = resp.json()
                if isinstance(data, dict) and data.get("type") == "failure":
                    self._is_authenticated = False
                    raise UrjaAuthenticationError("Invalid email or password provided to Urja portal")
            except (json.JSONDecodeError, ValueError):
                pass

            # Check if session token cookie is established
            token = self._client.cookies.get("__Secure-better-auth.session_token")
            if token or resp.status_code in (302, 303) or "redirect" in resp.text:
                self._is_authenticated = True
                return True

        self._is_authenticated = False
        raise UrjaAuthenticationError(f"Login failed with status {resp.status_code}: {resp.text[:200]}")

    def ensure_authenticated(self) -> None:
        """Ensure the client has an active authenticated session."""
        if not self._is_authenticated:
            with self._auth_lock:
                if not self._is_authenticated:
                    self.login()

    def _request_with_retry(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Any] = None,
        json_data: Optional[Any] = None,
    ) -> httpx.Response:
        """Execute HTTP request with automatic re-authentication on 401 or redirect to /login."""
        self.ensure_authenticated()

        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        req_headers = headers.copy() if headers else {}

        resp = self._client.request(
            method=method,
            url=url,
            params=params,
            headers=req_headers,
            data=data,
            json=json_data,
        )

        # Detect session expiration: 401 Unauthorized or 302 redirecting to /login
        is_expired = (
            resp.status_code == 401
            or (resp.status_code in (302, 303) and "/login" in (resp.headers.get("location") or ""))
        )

        if is_expired:
            with self._auth_lock:
                # Re-authenticate and retry once
                self.login()
            resp = self._client.request(
                method=method,
                url=url,
                params=params,
                headers=req_headers,
                data=data,
                json=json_data,
            )

        return resp

    def search_meters(self, q: str = "", page: int = 1) -> Dict[str, Any]:
        """Search meters with optional query string and page number."""
        resp = self._request_with_retry(
            "GET",
            "/portal/meters/search",
            params={"q": q, "page": page},
        )
        if resp.status_code != 200:
            raise UrjaPortalClientError(f"Failed to query meters: {resp.status_code} - {resp.text}")
        return resp.json()

    def get_meter_geo(self, meter_id: str) -> Optional[Dict[str, float]]:
        """Fetch latitude and longitude for a meter from /portal/meters/{id}/geo."""
        resp = self._request_with_retry("GET", f"/portal/meters/{meter_id}/geo")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            return None

        try:
            geo_data = resp.json().get("data", {})
            lat_str = geo_data.get("latitude")
            lng_str = geo_data.get("longitude")
            if lat_str is not None and lng_str is not None:
                return {
                    "latitude": float(lat_str),
                    "longitude": float(lng_str),
                }
        except (ValueError, TypeError):
            pass
        return None

    def get_meter_details(self, meter_id: str) -> Dict[str, Any]:
        """Retrieve and parse comprehensive meter details from /meters/{meter_id}."""
        resp = self._request_with_retry("GET", f"/meters/{meter_id}")

        if resp.status_code == 404 or "Meter not found" in resp.text:
            raise UrjaNotFoundError(f"Meter '{meter_id}' not found in Urja portal")
        if resp.status_code != 200:
            raise UrjaPortalClientError(f"Error fetching meter page: status {resp.status_code}")

        soup = BeautifulSoup(resp.text, "html.parser")

        # 1. Parse nameplate parameters from HTML definition list <dl>
        raw_parameters: Dict[str, str] = {}
        for dl in soup.find_all("dl"):
            dts = [dt.get_text(strip=True) for dt in dl.find_all("dt")]
            dds = [dd.get_text(strip=True) for dd in dl.find_all("dd")]
            for k, v in zip(dts, dds):
                if k:
                    raw_parameters[k] = v

        # 2. Extract breadcrumbs from <nav class="...text-xs...">
        breadcrumbs: List[str] = []
        nav = soup.find("nav", class_=lambda c: c and "text-xs" in c)
        if nav:
            for span in nav.find_all("span"):
                txt = span.get_text(strip=True)
                if txt and txt != "›" and txt != ">":
                    breadcrumbs.append(txt)

        # 3. Parse embedded SvelteKit data script for hierarchy and anomaly fields
        hierarchy_dict: Dict[str, Any] = {}
        class_data_parsed: Dict[str, Any] = {}

        for script in soup.find_all("script"):
            script_text = script.string or ""
            if "kit.start" in script_text or "classData" in script_text or "installed_meter" in script_text:
                # Extract embedded JSON data structure if possible
                try:
                    # Look for classData string
                    cd_match = re.search(r'classData:\s*("{\\"installed_meter\\":.*?}")', script_text)
                    if cd_match:
                        raw_json_str = json.loads(cd_match.group(1))
                        inner = json.loads(raw_json_str).get("installed_meter", {})
                        class_data_parsed = inner
                        for k, v in inner.items():
                            raw_parameters[k] = str(v)
                except Exception:
                    pass

                try:
                    # Look for hierarchy object
                    h_match = re.search(r'hierarchy:\s*({.*?}),(?:\s*form:|\s*error:|\s*uses:)', script_text)
                    if h_match:
                        # Attempt to parse or extract hierarchy keys
                        pass
                except Exception:
                    pass

        # Also attempt SvelteKit data endpoint if raw_parameters is sparse
        if len(raw_parameters) < 3:
            try:
                data_resp = self._request_with_retry(
                    "GET",
                    f"/meters/{meter_id}/__data.json",
                    headers={"x-sveltekit-invalidated": "01"}
                )
                if data_resp.status_code == 200:
                    d_json = data_resp.json()
                    # Parse SvelteKit data tree
                    for node in d_json.get("nodes", []):
                        if node and isinstance(node, dict) and "data" in node:
                            d_list = node["data"]
                            # Search for strings and keys
                            for idx, item in enumerate(d_list):
                                if isinstance(item, dict) and "parameterName" in item:
                                    pname = d_list[item["parameterName"]] if isinstance(item["parameterName"], int) else item["parameterName"]
                                    pval = d_list[item["parameterValue"]] if isinstance(item["parameterValue"], int) else item["parameterValue"]
                                    raw_parameters[str(pname)] = str(pval)
            except Exception:
                pass

        # 4. Fetch coordinates from geo endpoint
        geo = self.get_meter_geo(meter_id)

        # 5. Normalize attributes across both legacy formats
        # Legacy Format A: "Meter ID", "Serial No", "Make", "Phase Type", "Installation Status", "Installation Type"
        # Legacy Format B: "MeterId", "SerialNo", "Make", "PhaseType", "InstallationStatus", "InstallationType"
        serial_no = (
            raw_parameters.get("Serial No")
            or raw_parameters.get("SerialNo")
            or raw_parameters.get("serialNo")
            or "UNKNOWN"
        )
        make = raw_parameters.get("Make") or raw_parameters.get("make") or "UNKNOWN"
        phase_type = raw_parameters.get("Phase Type") or raw_parameters.get("PhaseType") or raw_parameters.get("phaseType") or "UNKNOWN"
        install_status = (
            raw_parameters.get("Installation Status")
            or raw_parameters.get("InstallationStatus")
            or raw_parameters.get("installStatus")
            or "UNKNOWN"
        )
        install_type = (
            raw_parameters.get("Installation Type")
            or raw_parameters.get("InstallationType")
            or raw_parameters.get("installType")
        )

        # Build hierarchy structure from breadcrumbs
        # Breadcrumbs order: Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> DT
        hierarchy_model: Dict[str, Any] = {"breadcrumbs": breadcrumbs}
        levels = ["zone", "circle", "division", "subdivision", "substation", "feeder", "dt"]
        for idx, lvl in enumerate(levels):
            if idx < len(breadcrumbs):
                val = breadcrumbs[idx]
                # parse "Name (CODE)" pattern
                code_match = re.search(r'\(([^)]+)\)', val)
                code = code_match.group(1) if code_match else None
                name = re.sub(r'\s*\([^)]+\)', '', val).strip()
                hierarchy_model[lvl] = {"name": name, "code": code}

        dt_code = hierarchy_model.get("dt", {}).get("code")

        return {
            "meter_id": meter_id,
            "serial_number": serial_no,
            "make": make,
            "phase_type": phase_type,
            "install_status": install_status,
            "install_type": install_type,
            "dt_code": dt_code,
            "location": geo,
            "hierarchy": hierarchy_model,
            "raw_parameters": raw_parameters,
        }

    def get_meter_consumption(self, meter_id: str) -> Dict[str, Any]:
        """Retrieve and normalize consumption data for a meter from /portal/meters/{id}/energy."""
        resp = self._request_with_retry("GET", f"/portal/meters/{meter_id}/energy")
        if resp.status_code == 404:
            raise UrjaNotFoundError(f"Meter '{meter_id}' not found or has no consumption records")
        if resp.status_code != 200:
            raise UrjaPortalClientError(f"Failed to fetch consumption: {resp.status_code} - {resp.text}")

        raw_readings = resp.json().get("data", [])

        normalized_readings: List[Dict[str, Any]] = []
        kwh_values: List[float] = []
        volt_values: List[float] = []

        for item in raw_readings:
            raw_ts = item.get("timestamp", "")
            iso_ts = None
            if raw_ts:
                try:
                    # Raw format is "DD/MM/YYYY HH:MM"
                    dt = datetime.strptime(raw_ts.strip(), "%d/%m/%Y %H:%M")
                    iso_ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    iso_ts = None

            # Parse numeric fields safely
            kwh = None
            if item.get("kwh") is not None:
                try:
                    kwh = round(float(item["kwh"]), 2)
                    kwh_values.append(kwh)
                except (ValueError, TypeError):
                    pass

            kvah = None
            if item.get("kvah") is not None:
                try:
                    kvah = round(float(item["kvah"]), 2)
                except (ValueError, TypeError):
                    pass

            volt_r = None
            if item.get("voltR") is not None:
                try:
                    volt_r = round(float(item["voltR"]), 1)
                    volt_values.append(volt_r)
                except (ValueError, TypeError):
                    pass

            normalized_readings.append({
                "timestamp": raw_ts,
                "iso_timestamp": iso_ts,
                "kwh": kwh,
                "kvah": kvah,
                "voltage_r": volt_r,
            })

        # Calculate consumption metrics
        reading_count = len(normalized_readings)
        earliest_ts = normalized_readings[0]["iso_timestamp"] if normalized_readings else None
        latest_ts = normalized_readings[-1]["iso_timestamp"] if normalized_readings else None
        latest_kwh = kwh_values[-1] if kwh_values else None
        kwh_delta = round(kwh_values[-1] - kwh_values[0], 2) if len(kwh_values) >= 2 else 0.0
        avg_volt = round(sum(volt_values) / len(volt_values), 1) if volt_values else None
        min_volt = min(volt_values) if volt_values else None
        max_volt = max(volt_values) if volt_values else None

        summary = {
            "reading_count": reading_count,
            "earliest_timestamp": earliest_ts,
            "latest_timestamp": latest_ts,
            "latest_kwh": latest_kwh,
            "kwh_delta": kwh_delta,
            "avg_voltage_r": avg_volt,
            "min_voltage_r": min_volt,
            "max_voltage_r": max_volt,
        }

        return {
            "meter_id": meter_id,
            "summary": summary,
            "readings": normalized_readings,
        }

    def get_dts(self, page: int = 1) -> Dict[str, Any]:
        """Fetch Distribution Transformers page from /portal/dts."""
        resp = self._request_with_retry("GET", "/portal/dts", params={"page": page})
        if resp.status_code != 200:
            raise UrjaPortalClientError(f"Failed to fetch DTs: {resp.status_code} - {resp.text}")
        return resp.json()

    def get_signing_secret(self) -> str:
        """Fetch cryptographic HMAC signing secret from /portal/keys."""
        if self._cached_signing_secret:
            return self._cached_signing_secret

        resp = self._request_with_retry("GET", "/portal/keys")
        if resp.status_code != 200:
            raise UrjaPortalClientError(f"Failed to fetch keys: {resp.status_code}")
        secret = resp.json().get("data", {}).get("signingSecret")
        if not secret:
            raise UrjaPortalClientError("Signing secret not found in keys response")
        self._cached_signing_secret = secret
        return secret

    def export_all_meters(self) -> List[Dict[str, Any]]:
        """Fetch the complete meter dataset in bulk via HMAC-authenticated export.

        Discovered signature algorithm:
        HMAC-SHA256(secret, "GET\n/portal/export\npage=1\n{timestamp}")
        """
        secret = self.get_signing_secret()
        method = "GET"
        path = "/portal/export"
        query = "page=1"
        timestamp = str(int(time.time()))

        message = f"{method}\n{path}\n{query}\n{timestamp}".encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

        headers = {
            "x-timestamp": timestamp,
            "x-signature": signature,
        }

        resp = self._request_with_retry(
            "GET",
            f"/portal/export?{query}",
            headers=headers,
        )

        if resp.status_code != 200:
            raise UrjaPortalClientError(f"Bulk export failed: {resp.status_code} - {resp.text}")

        return resp.json().get("data", [])

    def build_network_hierarchy(self, meters: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Reconstruct the distribution utility hierarchy tree from meters."""
        if meters is None:
            meters = self.export_all_meters()

        # Build tree: Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> DT -> meters
        zones: Dict[str, Dict[str, Any]] = {}
        all_dts: set = set()

        for m in meters:
            h = m.get("hierarchy", {})
            z = h.get("zone", {})
            c = h.get("circle", {})
            d = h.get("division", {})
            sd = h.get("subdivision", {})
            ss = h.get("substation", {})
            f = h.get("feeder", {})
            dt = h.get("dt", {})

            z_code = z.get("code") or "Z-UNKNOWN"
            z_name = z.get("name") or "Unknown Zone"

            if z_code not in zones:
                zones[z_code] = {"level": "zone", "code": z_code, "name": z_name, "children": {}, "meter_count": 0}
            zones[z_code]["meter_count"] += 1

            # Circle
            c_code = c.get("code") or "C-UNKNOWN"
            c_name = c.get("name") or "Unknown Circle"
            if c_code not in zones[z_code]["children"]:
                zones[z_code]["children"][c_code] = {"level": "circle", "code": c_code, "name": c_name, "children": {}, "meter_count": 0}
            zones[z_code]["children"][c_code]["meter_count"] += 1

            # Division
            d_code = d.get("code") or "D-UNKNOWN"
            d_name = d.get("name") or "Unknown Division"
            c_dict = zones[z_code]["children"][c_code]
            if d_code not in c_dict["children"]:
                c_dict["children"][d_code] = {"level": "division", "code": d_code, "name": d_name, "children": {}, "meter_count": 0}
            c_dict["children"][d_code]["meter_count"] += 1

            # Subdivision
            sd_code = sd.get("code") or "SD-UNKNOWN"
            sd_name = sd.get("name") or "Unknown Subdivision"
            d_dict = c_dict["children"][d_code]
            if sd_code not in d_dict["children"]:
                d_dict["children"][sd_code] = {"level": "subdivision", "code": sd_code, "name": sd_name, "children": {}, "meter_count": 0}
            d_dict["children"][sd_code]["meter_count"] += 1

            # Substation
            ss_code = ss.get("code") or "SS-UNKNOWN"
            ss_name = ss.get("name") or "Unknown Substation"
            sd_dict = d_dict["children"][sd_code]
            if ss_code not in sd_dict["children"]:
                sd_dict["children"][ss_code] = {"level": "substation", "code": ss_code, "name": ss_name, "children": {}, "meter_count": 0}
            sd_dict["children"][ss_code]["meter_count"] += 1

            # Feeder
            f_code = f.get("code") or "F-UNKNOWN"
            f_name = f.get("name") or "Unknown Feeder"
            ss_dict = sd_dict["children"][ss_code]
            if f_code not in ss_dict["children"]:
                ss_dict["children"][f_code] = {"level": "feeder", "code": f_code, "name": f_name, "children": {}, "meter_count": 0}
            ss_dict["children"][f_code]["meter_count"] += 1

            # DT
            dt_code = dt.get("code") or m.get("dtCode") or "DT-UNKNOWN"
            dt_name = dt.get("name") or f"Transformer {dt_code}"
            all_dts.add(dt_code)
            f_dict = ss_dict["children"][f_code]
            if dt_code not in f_dict["children"]:
                f_dict["children"][dt_code] = {"level": "dt", "code": dt_code, "name": dt_name, "children": {}, "meter_count": 0}
            f_dict["children"][dt_code]["meter_count"] += 1

        def convert_dict_to_list(node: Dict[str, Any]) -> Dict[str, Any]:
            children_list = [convert_dict_to_list(child) for child in node["children"].values()]
            return {
                "level": node["level"],
                "code": node["code"],
                "name": node["name"],
                "meter_count": node["meter_count"],
                "children": children_list,
            }

        tree = [convert_dict_to_list(z) for z in zones.values()]

        return {
            "total_zones": len(zones),
            "total_meters": len(meters),
            "total_dts": len(all_dts),
            "tree": tree,
        }
