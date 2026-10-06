"""Simulation and source isolation, tested without network or real hardware."""
import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from adapters.mock_sensor import MockSensorProvider, rainfall_value
from adapters.mock_transport import MockTransportProvider, apply_fallback, distance_metres
from api.main import create_app
from api.runtime import ROOT, Runtime, UnavailableTransport
from domain.models import SensorReading, utc_now
from domain.state_engine import classify_service

NOW = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
SITE = {"siteId": "city-rd-kings-way-116", "gtfsRouteIds": ["route58"], "gtfsStopIds": ["18233", "22612"]}
CONFIG = {"thresholds": {"WATCH": 25, "WARNING": 50, "CRITICAL": 75}, "hysteresis": 3,
          "riseDwellSeconds": 0, "recoveryDwellSeconds": 0, "sensorStaleSeconds": 30, "futureToleranceSeconds": 5}
FEEDS = ("vehiclePositions", "tripUpdates", "serviceAlerts")


def live_snapshot(**health):
    return {"routeShortName": "58", "source": "transport-victoria", "freshness": "fresh", "fetchedAt": NOW.isoformat(),
            "feedTimestamp": NOW.isoformat(), "vehicles": [], "tripUpdates": [], "alerts": [],
            "feeds": {name: {"source": "transport-victoria", "freshness": health.get(name, "fresh"),
                             "fetchedAt": NOW.isoformat(), "feedTimestamp": NOW.isoformat(), "error": None}
                      for name in FEEDS}}


class SwitchableTransport(UnavailableTransport):
    def __init__(self, value):
        self.value = value

    def snapshot(self, now=None):
        return copy.deepcopy(self.value)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SENSOR_PROVIDER", "mock")
    for name in ("ADMIN_API_TOKEN", "SENSOR_INGEST_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    app = create_app(":memory:", False, UnavailableTransport(), site=SITE, config=CONFIG)
    with TestClient(app) as session:
        yield session


def test_rain_profiles_are_repeatable_and_independent_of_water():
    assert [rainfall_value("water-rising", second) for second in (0, 12, 24, 36, 48)] == [2, 15, 35, 65, 80]
    assert [rainfall_value("recovery", second) for second in (0, 12, 24, 36)] == [80, 30, 5, 0]
    provider = MockSensorProvider()
    dry = provider.reading(SITE["siteId"], "normal-steady", 0, NOW)
    wet = provider.reading(SITE["siteId"], "normal-steady", 0, NOW, manual_rainfall=150)
    assert dry.scenarioLevel == wet.scenarioLevel == 12
    assert dry.rainfallIntensityMmPerHour == 0 and wet.rainfallIntensityMmPerHour == 150


def test_mock_vehicles_move_on_verified_geometry_and_have_demo_predictions():
    provider = MockTransportProvider(SITE)
    start = provider.snapshot(NOW)
    later = provider.snapshot(NOW + timedelta(seconds=2))
    assert start == provider.snapshot(NOW)
    assert len(start["vehicles"]) == len(provider.paths) == 2
    for index, vehicle in enumerate(start["vehicles"]):
        assert vehicle["vehicleId"].startswith("DEMO-") and vehicle["tripId"].startswith("DEMO-")
        assert vehicle["source"] == "mock"
        point = [vehicle["longitude"], vehicle["latitude"]]
        points, _, _ = provider.paths[index]
        # A point on one polyline segment satisfies the distance-addition identity.
        assert min(abs(distance_metres(first, point) + distance_metres(point, second) - distance_metres(first, second))
                   for first, second in zip(points, points[1:])) < 0.02
        assert vehicle["latitude"] != later["vehicles"][index]["latitude"] or vehicle["longitude"] != later["vehicles"][index]["longitude"]
    assert all(update["tripId"].startswith("DEMO-") and datetime.fromisoformat(update["arrivalAt"]) > NOW for update in start["tripUpdates"])
    assert not start["alerts"]


def test_healthy_empty_live_feeds_do_not_trigger_mock():
    live = live_snapshot()
    effective = apply_fallback(live, MockTransportProvider(SITE).snapshot(NOW))
    assert effective["source"] == "transport-victoria" and not effective["fallback"]
    assert effective["vehicles"] == effective["tripUpdates"] == effective["alerts"] == []
    assert effective["liveFeeds"] == live["feeds"]


def test_partial_feed_fallback_preserves_official_alert_and_original_health():
    live = live_snapshot(vehiclePositions="stale", tripUpdates="unavailable")
    live["vehicles"] = [{"vehicleId": "old-live-tram", "source": "transport-victoria", "freshness": "stale"}]
    live["alerts"] = [{"id": "official", "effect": "NO_SERVICE", "source": "transport-victoria"}]
    original = copy.deepcopy(live)
    effective = apply_fallback(live, MockTransportProvider(SITE).snapshot(NOW))
    assert live == original
    assert effective["source"] == "mixed" and effective["fallback"]
    assert effective["feeds"]["vehiclePositions"]["source"] == "mock"
    assert effective["liveFeeds"]["vehiclePositions"]["freshness"] == "stale"
    assert effective["liveFeeds"]["tripUpdates"]["freshness"] == "unavailable"
    assert effective["alerts"] == live["alerts"]
    service, source, _, _ = classify_service(effective, NOW)
    assert service == "SUSPENDED" and source == "transport-victoria"


def test_mock_alert_feed_does_not_claim_normal_official_service():
    effective = apply_fallback(live_snapshot(serviceAlerts="unavailable"), MockTransportProvider(SITE).snapshot(NOW))
    assert effective["source"] == "mixed" and effective["alerts"] == []
    assert classify_service(effective, NOW)[:2] == ("UNKNOWN", "mock")


def test_auto_recovers_each_feed_without_manual_switch():
    async def check():
        adapter = SwitchableTransport(live_snapshot(vehiclePositions="unavailable", tripUpdates="unavailable", serviceAlerts="unavailable"))
        current = Runtime(":memory:", adapter, SITE, CONFIG)
        try:
            unavailable = await current.tick(NOW)
            assert unavailable["transport"]["source"] == "mock" and unavailable["transport"]["fallback"]
            adapter.value = live_snapshot(tripUpdates="stale")
            partial = await current.tick(NOW + timedelta(seconds=1))
            assert partial["transport"]["source"] == "mixed"
            assert partial["transport"]["vehicles"] == []
            adapter.value = live_snapshot()
            recovered = await current.tick(NOW + timedelta(seconds=2))
            assert recovered["transport"]["source"] == "transport-victoria"
            assert not recovered["transport"]["fallback"] and recovered["transport"]["vehicles"] == []
        finally:
            await current.close()
    asyncio.run(check())


def test_no_credentials_fallback_is_explicit_and_ready_stays_degraded(client):
    snapshot = client.get("/api/v1/snapshot").json()
    transport = snapshot["transport"]
    assert transport["source"] == "mock" and transport["fallback"]
    assert all(feed["freshness"] == "unavailable" for feed in transport["liveFeeds"].values())
    assert len(transport["vehicles"]) == 2 and transport["fallbackReason"]
    assert snapshot["status"]["serviceState"] == "UNKNOWN"
    assert client.get("/health/ready").json()["status"] == "degraded"


def test_rain_slider_survives_water_slider_and_clears_reset_start_mode(client):
    rain = client.post("/api/v1/scenarios/rainfall", json={"intensityMmPerHour": 75}).json()
    assert rain["weather"]["intensityMmPerHour"] == 75 and rain["weather"]["source"] == "mock"
    water = client.post("/api/v1/scenarios/manual", json={"level": 60}).json()
    assert water["weather"]["intensityMmPerHour"] == 75 and water["status"]["hazardState"] == "WARNING"
    assert client.post("/api/v1/scenarios/reset").json()["weather"]["intensityMmPerHour"] == 0
    client.post("/api/v1/scenarios/rainfall", json={"intensityMmPerHour": 100})
    rising = client.post("/api/v1/scenarios/water-rising/start").json()
    assert rising["scenario"]["manualRainfall"] is None and rising["weather"]["intensityMmPerHour"] == 2
    client.post("/api/v1/scenarios/rainfall", json={"intensityMmPerHour": 100})
    physical = client.post("/api/v1/settings", json={"mode": "normal"}).json()
    assert physical["scenario"]["manualRainfall"] is None and physical["weather"]["source"] == "unavailable"
    assert client.post("/api/v1/scenarios/rainfall", json={"intensityMmPerHour": 100}).status_code == 409
    back = client.post("/api/v1/settings", json={"mode": "simulation"}).json()
    assert back["weather"]["intensityMmPerHour"] == 0


@pytest.mark.parametrize("value", [-1, 201, True, "42", None])
def test_invalid_rain_slider(client, value):
    assert client.post("/api/v1/scenarios/rainfall", json={"intensityMmPerHour": value}).status_code == 422


def test_explicit_mock_selection_and_normal_mode_reset_are_atomic(client):
    explicit = client.post("/api/v1/settings", json={"transportMode": "mock"}).json()
    assert explicit["scenario"]["transportMode"] == "mock" and not explicit["transport"]["fallback"]
    rejected = client.post("/api/v1/settings", json={"mode": "normal", "transportMode": "mock"})
    assert rejected.status_code == 409
    assert client.get("/api/v1/snapshot").json()["scenario"]["mode"] == "simulation"
    physical = client.post("/api/v1/settings", json={"mode": "normal"}).json()
    assert physical["scenario"]["transportMode"] == "auto" and physical["transport"]["fallback"]
    assert client.post("/api/v1/settings", json={"transportMode": "mock"}).status_code == 409
    assert client.post("/api/v1/settings", json={"transportMode": "auto"}).status_code == 200


def physical_payload(**updates):
    return {"readingId": str(uuid4()), "sensorId": "arduino-uno", "siteId": SITE["siteId"], "observedAt": utc_now().isoformat(),
            "scenarioLevel": 60, "quality": "valid", "source": "physical", "floatLevel": 1, "lowerFloat": True,
            "upperFloat": False, "sensorUptimeMs": 12345, **updates}


def test_physical_float_input_does_not_invent_rain_or_depth_and_transport_is_independent(client):
    client.post("/api/v1/settings", json={"mode": "normal"})
    assert client.post("/api/v1/sensors/readings", json=physical_payload()).status_code == 201
    snapshot = client.get("/api/v1/snapshot").json()
    assert snapshot["sensor"]["floatLevel"] == 1 and snapshot["sensor"]["lowerFloat"] is True
    assert snapshot["sensor"]["waterDepthMm"] is None
    assert snapshot["weather"] == {"intensityMmPerHour": None, "source": "unavailable", "freshness": "unavailable", "observedAt": None}
    assert snapshot["status"]["hazardState"] == "WARNING" and not snapshot["status"]["simulated"]
    assert snapshot["transport"]["source"] == "mock" and snapshot["transport"]["fallback"]
    client.post("/api/v1/settings", json={"mode": "simulation"})
    assert client.get("/api/v1/snapshot").json()["sensor"]["source"] == "mock"
    restored = client.post("/api/v1/settings", json={"mode": "normal"}).json()
    assert restored["sensor"]["source"] == "physical" and restored["sensor"]["floatLevel"] == 1
    assert restored["weather"]["source"] == "unavailable"


def test_weather_freshness_follows_observation_not_transport(client):
    stale = client.post("/api/v1/scenarios/sensor-stale/start").json()
    assert stale["weather"]["source"] == "mock" and stale["weather"]["freshness"] == "stale"
    assert stale["transport"]["freshness"] == "fresh"
    fault = client.post("/api/v1/scenarios/sensor-fault/start").json()
    assert fault["weather"]["freshness"] == "unavailable"
    client.post("/api/v1/settings", json={"mode": "normal"})
    client.post("/api/v1/sensors/readings", json=physical_payload(rainfallIntensityMmPerHour=3.5))
    assert client.get("/api/v1/snapshot").json()["weather"]["source"] == "physical"


@pytest.mark.parametrize("updates", [{"floatLevel": True}, {"floatLevel": "1"}, {"floatLevel": 1.0}, {"floatLevel": 3},
                                     {"lowerFloat": 1}, {"upperFloat": "false"}, {"sensorUptimeMs": -1},
                                     {"sensorUptimeMs": 4294967296}, {"sensorUptimeMs": True}])
def test_strict_physical_float_contract(updates):
    with pytest.raises(ValidationError):
        SensorReading.model_validate(physical_payload(**updates))


def test_explicit_mock_can_override_healthy_live_without_losing_original_health():
    live = live_snapshot()
    live["vehicles"] = [{"vehicleId": "LIVE-TRAM", "source": "transport-victoria"}]
    provider = MockTransportProvider(SITE)
    explicit = apply_fallback(live, provider.snapshot(NOW), force_mock=True)
    assert explicit["source"] == "mock" and not explicit["fallback"]
    assert all(feed["freshness"] == "fresh" and feed["source"] == "transport-victoria" for feed in explicit["liveFeeds"].values())
    restored = apply_fallback(live, provider.snapshot(NOW))
    assert restored["vehicles"] == live["vehicles"] and restored["source"] == "transport-victoria"


def test_persisted_transport_cache_never_contains_generated_mock():
    class RefreshableTransport(SwitchableTransport):
        async def refresh(self):
            return self.snapshot()

    async def check():
        live = live_snapshot(vehiclePositions="stale")
        live["vehicles"] = [{"vehicleId": "LAST-LIVE", "source": "transport-victoria", "freshness": "stale"}]
        current = Runtime(":memory:", RefreshableTransport(live), SITE, CONFIG)
        try:
            await current.refresh_transport()
            effective = await current.tick(NOW)
            assert effective["transport"]["vehicles"][0]["vehicleId"].startswith("DEMO-")
            cached = current.store.cache("transport")
            assert cached["vehicles"] == live["vehicles"]
            assert cached["source"] == "transport-victoria" and "liveFeeds" not in cached
        finally:
            await current.close()
    asyncio.run(check())



def test_predictions_match_nested_gtfs_stop_directions_not_array_order():
    site = json.loads((ROOT / "config/site.json").read_text(encoding="utf-8"))
    # Both lists are reversed: matching their array index produces wrong platforms.
    site["stops"].reverse()
    site["gtfsStopIds"].reverse()
    snapshot = MockTransportProvider(site).snapshot(NOW)
    by_direction = {str(direction["directionId"]): stop["stopId"]
                    for stop in site["stops"] for direction in stop["directions"]}
    assert {update["tripId"]: update["stopId"] for update in snapshot["tripUpdates"]} == {
        f"DEMO-58-{direction}-TRIP": stop_id for direction, stop_id in by_direction.items()}


def test_prediction_eta_projects_actual_stop_between_gtfs_vertices():
    first, middle, last = [144.960, -37.82], [144.961, -37.82], [144.964, -37.82]
    target = [144.9615, -37.82]
    geometry = {"features": [{"properties": {"kind": "local_segment", "directionId": "0"},
                              "geometry": {"type": "LineString", "coordinates": [first, middle, middle, last]}}]}
    site = {"gtfsStopIds": ["wrong-array-fallback"], "stops": [{"stopId": "correct-stop", "longitude": target[0],
            "latitude": target[1], "directions": [{"directionId": "0"}]}]}
    # At the epoch the first demo vehicle is at the start of its polyline.
    start = datetime(1970, 1, 1, tzinfo=timezone.utc)
    update = MockTransportProvider(site, geometry).snapshot(start)["tripUpdates"][0]
    actual_seconds = (datetime.fromisoformat(update["arrivalAt"]) - start).total_seconds()
    assert update["stopId"] == "correct-stop"
    assert actual_seconds == max(5, round(distance_metres(first, target) / 8))
    assert actual_seconds != round(distance_metres(first, last) / 2 / 8)



@pytest.mark.parametrize("level,lower,upper,scenario,hazard", [
    (0, False, False, 0, "NORMAL"), (1, True, False, 60, "WARNING"),
    (2, True, True, 90, "CRITICAL"), (-1, False, True, 0, "UNKNOWN"),
])
def test_api_accepts_consistent_float_states_and_invalid_switches_are_unknown(client, level, lower, upper, scenario, hazard):
    client.post("/api/v1/settings", json={"mode": "normal"})
    payload = physical_payload(floatLevel=level, lowerFloat=lower, upperFloat=upper,
                               scenarioLevel=scenario, quality="fault" if level == -1 else "valid")
    assert client.post("/api/v1/sensors/readings", json=payload).status_code == 201
    assert client.get("/api/v1/snapshot").json()["status"]["hazardState"] == hazard


@pytest.mark.parametrize("lower,upper,level", [
    (lower, upper, level)
    for lower, upper, expected in [(False, False, 0), (True, False, 1), (True, True, 2), (False, True, -1)]
    for level in [-1, 0, 1, 2] if level != expected
])
def test_api_rejects_every_inconsistent_float_pair(client, lower, upper, level):
    scenario = {-1: 0, 0: 0, 1: 60, 2: 90}[level]
    payload = physical_payload(floatLevel=level, lowerFloat=lower, upperFloat=upper,
                               scenarioLevel=scenario, quality="fault" if level == -1 else "valid")
    assert client.post("/api/v1/sensors/readings", json=payload).status_code == 422


@pytest.mark.parametrize("quality", ["valid", "unknown", "stale"])
def test_api_invalid_float_state_cannot_be_reported_as_nonfault(client, quality):
    payload = physical_payload(floatLevel=-1, lowerFloat=False, upperFloat=True, scenarioLevel=0, quality=quality)
    assert client.post("/api/v1/sensors/readings", json=payload).status_code == 422


@pytest.mark.parametrize("level,lower,upper,wrong_scenario", [(0, False, False, 90), (1, True, False, 0),
                                                          (2, True, True, 0), (-1, False, True, 90)])
def test_api_rejects_physical_float_hazard_mapping_conflicts(client, level, lower, upper, wrong_scenario):
    payload = physical_payload(floatLevel=level, lowerFloat=lower, upperFloat=upper,
                               scenarioLevel=wrong_scenario, quality="fault" if level == -1 else "valid")
    assert client.post("/api/v1/sensors/readings", json=payload).status_code == 422


@pytest.mark.parametrize("present", [("floatLevel",), ("lowerFloat",), ("upperFloat",),
                                     ("floatLevel", "lowerFloat"), ("floatLevel", "upperFloat"), ("lowerFloat", "upperFloat")])
def test_api_requires_complete_float_metadata(client, present):
    payload = physical_payload()
    for field in ("floatLevel", "lowerFloat", "upperFloat"):
        if field not in present:
            payload.pop(field)
    assert client.post("/api/v1/sensors/readings", json=payload).status_code == 422


@pytest.mark.parametrize("quality,expected_hazard", [("stale", "UNKNOWN"), ("fault", "UNKNOWN"), ("unknown", "UNKNOWN")])
def test_valid_float_states_can_still_report_unhealthy_device_quality(client, quality, expected_hazard):
    client.post("/api/v1/settings", json={"mode": "normal"})
    assert client.post("/api/v1/sensors/readings", json=physical_payload(quality=quality)).status_code == 201
    assert client.get("/api/v1/status").json()["hazardState"] == expected_hazard


def test_generic_physical_reading_without_float_metadata_remains_supported(client):
    payload = physical_payload(scenarioLevel=37)
    for field in ("floatLevel", "lowerFloat", "upperFloat", "sensorUptimeMs"):
        payload.pop(field)
    assert client.post("/api/v1/sensors/readings", json=payload).status_code == 201
