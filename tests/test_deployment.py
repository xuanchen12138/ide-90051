import base64

import pytest
from fastapi.testclient import TestClient

from api.deployment import validate_deployment
from api.main import create_app
from api.runtime import UnavailableTransport

DEMO_PASSWORD = "test-only-demo-password"
ADMIN_TOKEN = "test-only-admin-token"
SENSOR_TOKEN = "test-only-sensor-token"


@pytest.fixture
def shared_client(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEPLOYMENT", "true")
    monkeypatch.setenv("DEMO_ACCESS_USERNAME", "demo")
    monkeypatch.setenv("DEMO_ACCESS_PASSWORD", DEMO_PASSWORD)
    monkeypatch.setenv("ADMIN_API_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("SENSOR_INGEST_TOKEN", SENSOR_TOKEN)
    monkeypatch.setenv("SENSOR_PROVIDER", "mock")
    with TestClient(create_app(":memory:", start_background=False, transport=UnavailableTransport())) as client:
        yield client


def test_cloud_health_is_public_but_map_api_exports_and_docs_are_protected(shared_client):
    assert shared_client.get("/health/live").status_code == 200
    assert shared_client.get("/health/ready").status_code == 200
    for path in ("/", "/api/v1/snapshot", "/api/v1/site/basemap", "/api/v1/events", "/api/v1/events/export", "/docs"):
        response = shared_client.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Basic")
        assert DEMO_PASSWORD not in response.text


@pytest.mark.parametrize("header", ["Basic !!!!", "Bearer wrong", "Basic " + base64.b64encode(b"demo:wrong").decode(), "Basic /w=="])
def test_malformed_or_wrong_credentials_are_rejected(shared_client, header):
    assert shared_client.get("/api/v1/site", headers={"Authorization": header}).status_code == 401


def test_demo_login_can_use_browser_controls_without_frontend_admin_secret(shared_client):
    assert shared_client.get("/api/v1/snapshot", auth=("demo", DEMO_PASSWORD)).status_code == 200
    assert shared_client.post("/api/v1/scenarios/manual", json={"level": 60}, auth=("demo", DEMO_PASSWORD)).status_code == 200
    assert shared_client.post("/api/v1/settings", json={"mode": "normal"}, auth=("demo", DEMO_PASSWORD)).status_code == 200
    from uuid import uuid4
    from domain.models import utc_now
    body = {"readingId": str(uuid4()), "sensorId": "device", "siteId": "city-rd-kings-way-116", "observedAt": utc_now().isoformat(), "scenarioLevel": 12, "quality": "valid", "source": "physical"}
    assert shared_client.post("/api/v1/sensors/readings", json=body, auth=("demo", DEMO_PASSWORD)).status_code == 401
    assert shared_client.post("/api/v1/sensors/readings", json=body, headers={"Authorization": f"Bearer {SENSOR_TOKEN}"}).status_code == 201


def test_admin_bearer_is_supported_and_sensor_token_cannot_control_scenarios(shared_client):
    assert shared_client.post("/api/v1/scenarios/reset", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}).status_code == 200
    assert shared_client.post("/api/v1/scenarios/reset", headers={"Authorization": f"Bearer {SENSOR_TOKEN}"}).status_code == 401
    assert shared_client.post("/api/v1/scenarios/reset", auth=("demo", DEMO_PASSWORD), headers={"Origin": "https://unrelated.example"}).status_code == 403


@pytest.mark.parametrize("missing", ["DEMO_ACCESS_PASSWORD", "ADMIN_API_TOKEN", "SENSOR_INGEST_TOKEN"])
def test_public_deployment_fails_closed_without_required_secrets(monkeypatch, missing):
    monkeypatch.setenv("PUBLIC_DEPLOYMENT", "true")
    for name in ("DEMO_ACCESS_PASSWORD", "ADMIN_API_TOKEN", "SENSOR_INGEST_TOKEN"):
        monkeypatch.setenv(name, "a-long-test-value-only")
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match=missing):
        validate_deployment()
