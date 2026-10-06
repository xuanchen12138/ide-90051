import asyncio
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.runtime import ROOT, Runtime, UnavailableTransport, source_build_id
from domain.models import utc_now

SITE = {"siteId": "city-rd-kings-way-116", "gtfsDatasetVersion": "fixture-2026-09-22", "gtfsRouteIds": ["route58"], "gtfsStopIds": ["s116"]}
CONFIG = {"thresholds": {"WATCH": 25, "WARNING": 50, "CRITICAL": 75}, "hysteresis": 3,
          "riseDwellSeconds": 0, "recoveryDwellSeconds": 0, "sensorStaleSeconds": 30, "futureToleranceSeconds": 5}


@pytest.fixture
def client(monkeypatch):
    for variable in ("SENSOR_INGEST_TOKEN", "ADMIN_API_TOKEN"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("SENSOR_PROVIDER", "mock")
    app = create_app(":memory:", start_background=False, transport=UnavailableTransport(), site=SITE, config=CONFIG)
    with TestClient(app) as session:
        yield session


def body(**updates):
    return {"readingId": str(uuid4()), "sensorId": "hardware-001", "siteId": SITE["siteId"], "observedAt": utc_now().isoformat(), "scenarioLevel": 12, "quality": "valid", "source": "physical", **updates}


def test_endpoint_contract_and_ready_degraded(client):
    snapshot = client.get("/api/v1/snapshot").json()
    assert set(snapshot) == {"status", "sensor", "transport", "scenario", "timeline", "serverTime"}
    assert snapshot["status"]["hazardState"] == "NORMAL"
    assert snapshot["status"]["serviceState"] == "UNKNOWN"
    assert client.get("/api/v1/status").json()["hazardState"] == "NORMAL"
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json()["status"] == "degraded"
    assert client.get("/api/v1/site").json() == SITE
    assert len(client.get("/api/v1/scenarios").json()) == 8


@pytest.mark.parametrize("scenario,hazard,service", [("normal-steady", "NORMAL", "UNKNOWN"), ("water-rising", "NORMAL", "UNKNOWN"), ("critical-rise", "NORMAL", "UNKNOWN"), ("recovery", "CRITICAL", "UNKNOWN"), ("sensor-stale", "UNKNOWN", "UNKNOWN"), ("sensor-fault", "UNKNOWN", "UNKNOWN"), ("transport-feed-unavailable", "NORMAL", "UNKNOWN"), ("official-alert-present", "NORMAL", "SUSPENDED")])
def test_each_named_scenario_start(client, scenario, hazard, service):
    response = client.post(f"/api/v1/scenarios/{scenario}/start")
    assert response.status_code == 200
    assert response.json()["status"]["hazardState"] == hazard
    assert response.json()["status"]["serviceState"] == service


def test_controls_and_manual_levels(client):
    assert client.post("/api/v1/scenarios/missing/start").status_code == 404
    assert client.post("/api/v1/scenarios/pause").json()["scenario"]["paused"]
    assert not client.post("/api/v1/scenarios/resume").json()["scenario"]["paused"]
    for level, expected in [(25, "WATCH"), (50, "WARNING"), (75, "CRITICAL")]:
        snapshot = client.post("/api/v1/scenarios/manual", json={"level": level}).json()
        assert snapshot["status"]["hazardState"] == expected
        assert snapshot["scenario"]["paused"]
    snapshot = client.post("/api/v1/settings", json={"impactScope": "full_route_demo"}).json()
    assert snapshot["status"]["impactScope"] == "full_route_demo"
    snapshot = client.post("/api/v1/scenarios/reset").json()
    assert snapshot["scenario"]["impactScope"] == "local_segment"
    assert snapshot["status"]["hazardState"] == "NORMAL"
    assert client.post("/api/v1/scenarios/manual", json={"level": 101}).status_code == 422


def test_basemap_endpoint_serves_auditable_local_geojson(client):
    response = client.get("/api/v1/site/basemap")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/geo+json"
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert data["metadata"]["license"] == "ODbL-1.0"
    kinds = {feature["properties"]["kind"] for feature in data["features"]}
    assert {"water", "bridge", "building", "road", "park"} <= kinds
    assert any(feature["properties"].get("name") == "Crown Melbourne" for feature in data["features"])


def test_fixture_removed_by_reset_and_normal_mode(client):
    fixture = client.post("/api/v1/scenarios/official-alert-present/start").json()
    assert fixture["transport"]["source"] == fixture["status"]["serviceSource"] == "fixture"
    reset = client.post("/api/v1/scenarios/reset").json()
    assert reset["transport"]["source"] == "transport-victoria" and not reset["transport"]["alerts"]
    client.post("/api/v1/scenarios/official-alert-present/start")
    normal = client.post("/api/v1/settings", json={"mode": "normal"}).json()
    assert normal["sensor"] is None
    assert normal["status"]["hazardState"] == normal["status"]["serviceState"] == "UNKNOWN"
    assert not normal["status"]["simulated"]
    assert normal["transport"]["source"] == "transport-victoria"
    assert client.post("/api/v1/scenarios/manual", json={"level": 80}).status_code == 409


def test_normal_mode_controls_cannot_silently_restore_mock(client):
    client.post("/api/v1/settings", json={"mode": "normal"})
    for route in ("water-rising/start", "pause", "resume"):
        assert client.post(f"/api/v1/scenarios/{route}").status_code == 409
    snapshot = client.post("/api/v1/scenarios/reset").json()
    assert snapshot["scenario"]["mode"] == "normal"
    assert snapshot["sensor"] is None
    assert not snapshot["status"]["simulated"]


def test_http_ingestion_idempotence_conflict_and_out_of_order(client):
    client.post("/api/v1/settings", json={"mode": "normal"})
    payload = body(scenarioLevel=80)
    first = client.post("/api/v1/sensors/readings", json=payload)
    assert first.status_code == 201
    assert client.get("/api/v1/status").json()["hazardState"] == "CRITICAL"
    assert client.post("/api/v1/sensors/readings", json=payload).json()["result"] == "duplicate"
    assert client.post("/api/v1/sensors/readings", json={**payload, "scenarioLevel": 5}).status_code == 409
    older = body(observedAt=(utc_now()-timedelta(seconds=10)).isoformat(), scenarioLevel=1)
    response = client.post("/api/v1/sensors/readings", json=older)
    assert response.status_code == 201 and not response.json()["latest"]
    assert client.get("/api/v1/sensors/latest").json()["readingId"] == payload["readingId"]
    assert client.get("/api/v1/status").json()["hazardState"] == "CRITICAL"


@pytest.mark.parametrize("updates", [{"source": "mock"}, {"siteId": "other-site"}, {"observedAt": (utc_now()+timedelta(days=1)).isoformat()}])
def test_ingestion_semantic_rejections(client, updates):
    assert client.post("/api/v1/sensors/readings", json=body(**updates)).status_code == 422


def test_received_timestamp_is_server_authoritative(client):
    client.post("/api/v1/settings", json={"mode": "normal"})
    payload = body(receivedAt="2000-01-01T00:00:00Z")
    client.post("/api/v1/sensors/readings", json=payload)
    assert client.get("/api/v1/sensors/latest").json()["receivedAt"] != payload["receivedAt"]


def test_validation_diagnostics_never_echo_payload(client):
    private = "private-test-value-do-not-echo"
    response = client.post("/api/v1/sensors/readings", json=body(scenarioLevel=private, unexpected=private))
    assert response.status_code == 422
    assert private not in response.text
    exported = client.get("/api/v1/events/export").text
    assert private not in exported and "invalid_payload" in exported


def test_origin_and_optional_credentials(client, monkeypatch):
    assert client.post("/api/v1/scenarios/reset", headers={"Origin": "https://attacker.example"}).status_code == 403
    assert client.post("/api/v1/scenarios/reset", headers={"Origin": "http://testserver"}).status_code == 200
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-admin-token")
    assert client.post("/api/v1/scenarios/reset").status_code == 401
    assert client.post("/api/v1/scenarios/reset", headers={"Authorization": "Bearer test-admin-token"}).status_code == 200
    monkeypatch.setenv("SENSOR_INGEST_TOKEN", "test-sensor-token")
    assert client.post("/api/v1/sensors/readings", json=body()).status_code == 401
    assert client.post("/api/v1/sensors/readings", json=body(), headers={"Authorization": "Bearer test-sensor-token"}).status_code == 201


def test_browser_render_telemetry_keeps_real_client_times_and_deduplicates(client):
    snapshot = client.get("/api/v1/snapshot").json()
    payload = {"readingId": snapshot["sensor"]["readingId"], "renderedAt": utc_now().isoformat()}
    assert client.post("/api/v1/telemetry/render", json=payload).json()["result"] == "accepted"
    assert client.post("/api/v1/telemetry/render", json=payload).json()["result"] == "duplicate"
    exported = client.get("/api/v1/events/export").json()
    assert len(exported["latencySamplesMs"]) == 1
    assert exported["renderSamples"][0]["evaluatedAt"]
    assert exported["configurationHash"] and exported["gtfsDatasetVersion"] == SITE["gtfsDatasetVersion"]


def test_late_browser_render_is_attached_to_the_original_run(client):
    snapshot = client.get("/api/v1/snapshot").json()
    original_run = client.get("/api/v1/events/export").json()["runId"]
    client.post("/api/v1/scenarios/reset")
    payload = {"readingId": snapshot["sensor"]["readingId"], "renderedAt": utc_now().isoformat()}
    assert client.post("/api/v1/telemetry/render", json=payload).json()["result"] == "accepted"
    assert client.get("/api/v1/events/export").json()["latencySamplesMs"] == []
    original_events = client.app.state.runtime.store.events(original_run)
    assert len([event for event in original_events if event["type"] == "browser-render"]) == 1


def test_timeline_keeps_last_state_after_many_observations(client):
    current = client.app.state.runtime
    for _ in range(200):
        current.store.event(current.run_id, "sensor-ingested", {"readingId": str(uuid4())})
    assert any(event["type"] == "state-transition" for event in current.snapshot()["timeline"])


def test_outage_fixture_keeps_real_transport_snapshot_separate(client):
    client.post("/api/v1/scenarios/transport-feed-unavailable/start")
    assert client.get("/api/v1/snapshot").json()["transport"]["source"] == "fixture"
    assert client.app.state.runtime.real_transport["source"] == "transport-victoria"


def test_polling_env_consumed_and_invalid_values_rejected(monkeypatch):
    monkeypatch.setenv("TRANSPORT_POLL_SECONDS", "75")
    current = Runtime(":memory:", UnavailableTransport(), SITE, CONFIG)
    assert current.config["transportPollSeconds"] == 75
    assert "transportPollSeconds" not in CONFIG
    asyncio.run(current.close())
    for value in ("NaN", "inf", "0", "-1", "bad"):
        monkeypatch.setenv("TRANSPORT_POLL_SECONDS", value)
        with pytest.raises(ValueError):
            Runtime(":memory:", UnavailableTransport(), SITE, CONFIG)


def test_fallback_build_hash_is_deterministic_and_excludes_secrets(tmp_path):
    directory = tmp_path / "api"
    directory.mkdir()
    source = directory / "main.py"
    source.write_text("example=1")
    initial = source_build_id(tmp_path)
    assert initial.startswith("source-") and initial == source_build_id(tmp_path)
    (tmp_path / ".env").write_text("TRANSPORT_VIC_API_KEY=private-test-value")
    (directory / ".env").write_text("private-test-value")
    assert source_build_id(tmp_path) == initial
    source.write_text("example=2")
    assert source_build_id(tmp_path) != initial


def test_unexpected_transport_refresh_exception_degrades_cached_health(monkeypatch):
    class FailingTransport(UnavailableTransport):
        def snapshot(self, now=None):
            return {**super().snapshot(now), "freshness": "fresh", "feeds": {"serviceAlerts": {"freshness": "fresh"}}}

        async def refresh(self):
            raise RuntimeError("private-test-secret-do-not-log")

    async def run():
        current = Runtime(":memory:", FailingTransport(), SITE, CONFIG)
        await current.tick()
        assert current.status["serviceState"] == "NORMAL"
        await current.refresh_transport()
        await current.tick(generate=False)
        assert current.status["serviceState"] == "UNKNOWN"
        assert "private-test-secret-do-not-log" not in json.dumps(current.export())
        await current.close()
    asyncio.run(run())


def test_physical_configuration_and_database_restore(monkeypatch, tmp_path):
    monkeypatch.setenv("SENSOR_PROVIDER", "physical")
    monkeypatch.delenv("SENSOR_INGEST_TOKEN", raising=False)
    path = str(tmp_path / "readings.db")
    with TestClient(create_app(path, False, UnavailableTransport(), site=SITE, config=CONFIG)) as client:
        assert client.get("/api/v1/snapshot").json()["scenario"]["mode"] == "normal"
        assert client.get("/api/v1/status").json()["hazardState"] == "UNKNOWN"
        payload = body(scenarioLevel=55)
        assert client.post("/api/v1/sensors/readings", json=payload).status_code == 201
    with TestClient(create_app(path, False, UnavailableTransport(), site=SITE, config=CONFIG)) as client:
        assert client.get("/api/v1/sensors/latest").json()["readingId"] == payload["readingId"]
        assert client.get("/api/v1/status").json()["hazardState"] == "WARNING"


def test_configuration_rejects_invalid_thresholds():
    with pytest.raises(ValueError):
        Runtime(":memory:", UnavailableTransport(), SITE, {**CONFIG, "thresholds": {"WATCH": 50, "WARNING": 25, "CRITICAL": 75}})


def test_scenario_runtime_recovery_and_pause_clock():
    async def run():
        current = Runtime(":memory:", UnavailableTransport(), SITE, CONFIG)
        await current.start_scenario("water-rising")
        start = current.last_tick
        levels = []
        for second in (0, 12, 24, 36):
            value = await current.tick(start + timedelta(seconds=second))
            levels.append(value["status"]["hazardState"])
        assert levels == ["NORMAL", "WATCH", "WARNING", "CRITICAL"]
        current.paused = True
        before = current.elapsed
        await current.tick(start + timedelta(seconds=38))
        assert current.elapsed == before
        await current.start_scenario("recovery")
        start = current.last_tick
        recovered = []
        for second in (0, 12, 24, 36):
            value = await current.tick(start + timedelta(seconds=second))
            recovered.append(value["status"]["hazardState"])
        assert recovered == ["CRITICAL", "WARNING", "WATCH", "NORMAL"]
        assert len(current.export()["transitionChecks"]) == 4
        await current.close()
    asyncio.run(run())
