import pytest
from app.client import UrjaPortalClient, UrjaNotFoundError
from app.cache import haversine_distance_km, TTLCache, MeterIndex


def test_haversine_distance():
    # Same point distance should be 0
    d = haversine_distance_km(26.9389, 75.8309, 26.9389, 75.8309)
    assert round(d, 3) == 0.0

    # Known distance Jaipur center to Malviya Nagar ~ 5-10 km
    d2 = haversine_distance_km(26.9124, 75.7873, 26.8530, 75.8052)
    assert 6.0 < d2 < 10.0


def test_ttl_cache():
    cache = TTLCache(default_ttl=1)
    cache.set("foo", "bar")
    assert cache.get("foo") == "bar"
    cache.delete("foo")
    assert cache.get("foo") is None


def test_meter_index_filtering():
    index = MeterIndex()
    sample_meters = [
        {
            "meterId": "J100000",
            "serialNo": "SE33962",
            "make": "HPL",
            "phaseType": "single",
            "installStatus": "Decommissioned",
            "dtCode": "DT-001",
            "geo": {"lat": 26.9389, "lng": 75.8309}
        },
        {
            "meterId": "J100004",
            "serialNo": "SE65293",
            "make": "Genus",
            "phaseType": "three",
            "installStatus": "Faulty",
            "dtCode": "DT-005",
            "geo": {"lat": 26.9400, "lng": 75.8350}
        },
        {
            "meterId": "J100008",
            "serialNo": "SE99999",
            "make": "Secure",
            "phaseType": "single",
            "installStatus": "Active",
            "dtCode": "DT-001",
            "geo": {"lat": 27.5000, "lng": 76.5000}
        }
    ]
    index.load(sample_meters)
    assert index.count() == 3

    # Filter by make
    res_make = index.query(make="Genus")
    assert len(res_make) == 1
    assert res_make[0]["meterId"] == "J100004"

    # Filter by status
    res_status = index.query(install_status="Active")
    assert len(res_status) == 1
    assert res_status[0]["meterId"] == "J100008"

    # Filter by spatial proximity
    res_geo = index.query(lat=26.9389, lng=75.8309, radius_km=2.0)
    assert len(res_geo) == 2  # J100000 and J100004 are within 2km, J100008 is far away
    assert res_geo[0]["meterId"] == "J100000"


def test_live_portal_client_auth_and_search():
    client = UrjaPortalClient()
    # Test login
    auth_ok = client.login()
    assert auth_ok is True
    assert client.is_authenticated is True

    # Test search meters
    search_res = client.search_meters(q="", page=1)
    assert "data" in search_res
    assert search_res["total"] >= 400
    assert len(search_res["data"]) == 20

    # Test meter detail
    first_id = search_res["data"][0]["meterId"]
    detail = client.get_meter_details(first_id)
    assert detail["meter_id"] == first_id
    assert detail["serial_number"] != "UNKNOWN"
    assert detail["make"] != "UNKNOWN"
    assert "hierarchy" in detail

    # Test consumption
    consumption = client.get_meter_consumption(first_id)
    assert consumption["meter_id"] == first_id
    assert "summary" in consumption
    assert consumption["summary"]["reading_count"] > 0
    assert len(consumption["readings"]) > 0

    first_reading = consumption["readings"][0]
    assert first_reading["iso_timestamp"] is not None
    assert isinstance(first_reading["kwh"], float)
    assert isinstance(first_reading["voltage_r"], float)


def test_live_portal_not_found():
    client = UrjaPortalClient()
    with pytest.raises(UrjaNotFoundError):
        client.get_meter_details("INVALID_METER_999999")
