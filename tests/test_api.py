import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "portal_connected" in data
    assert "version" in data


def test_dashboard_ui():
    response = client.get("/")
    assert response.status_code == 200
    assert "Flock Energy" in response.text
    assert "Urja" in response.text


def test_auth_login():
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "operator@urja.local", "password": "urja-ops-2026"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "authenticated"


def test_auth_bad_credentials():
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "operator@urja.local", "password": "incorrect-password"}
    )
    assert response.status_code == 401


def test_list_meters():
    response = client.get("/api/v1/meters?page=1&page_size=10")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert data["total"] >= 400
    assert len(data["data"]) > 0
    first = data["data"][0]
    assert "meter_id" in first
    assert "serial_number" in first
    assert "make" in first
    assert "phase_type" in first


def test_get_meter_detail():
    # Retrieve a known meter
    response = client.get("/api/v1/meters/J100000")
    assert response.status_code == 200
    data = response.json()
    assert data["meter_id"] == "J100000"
    assert data["serial_number"] == "SE33962"
    assert data["make"] == "HPL"
    assert data["phase_type"] == "single"
    assert data["location"] is not None
    assert "hierarchy" in data


def test_get_meter_consumption():
    response = client.get("/api/v1/meters/J100000/consumption")
    assert response.status_code == 200
    data = response.json()
    assert data["meter_id"] == "J100000"
    assert "summary" in data
    assert data["summary"]["reading_count"] > 0
    assert "readings" in data
    assert len(data["readings"]) > 0
    reading0 = data["readings"][0]
    assert "iso_timestamp" in reading0
    assert isinstance(reading0["kwh"], float)


def test_get_transformers():
    response = client.get("/api/v1/transformers?page=1")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert data["total"] == 40
    assert len(data["data"]) > 0
    dt0 = data["data"][0]
    assert "code" in dt0
    assert "capacity_kva" in dt0


def test_meter_not_found():
    response = client.get("/api/v1/meters/NON_EXISTENT_999999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_network_hierarchy():
    response = client.get("/api/v1/hierarchy")
    assert response.status_code == 200
    data = response.json()
    assert "tree" in data
    assert data["total_meters"] >= 400
    assert data["total_dts"] >= 35
    assert len(data["tree"]) > 0
