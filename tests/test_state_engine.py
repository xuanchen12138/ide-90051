from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from domain.models import SensorReading
from domain.state_engine import TransitionState, evaluate_status

NOW = datetime(2026, 9, 22, 0, 0, tzinfo=timezone.utc)
CONFIG = {"thresholds": {"WATCH": 25, "WARNING": 50, "CRITICAL": 75}, "hysteresis": 3,
          "riseDwellSeconds": 3, "recoveryDwellSeconds": 5, "sensorStaleSeconds": 30, "futureToleranceSeconds": 5}
TRANSPORT = {"source": "transport-victoria", "freshness": "fresh", "alerts": [], "vehicles": [], "tripUpdates": [],
             "feeds": {"serviceAlerts": {"freshness": "fresh"}, "tripUpdates": {"freshness": "fresh"}}}


def reading(level=12, observed=NOW, quality="valid", **kwargs):
    return SensorReading(readingId=uuid4(), sensorId="test", siteId="city-rd-kings-way-116", observedAt=observed,
                         scenarioLevel=level, source="mock", quality=quality, **kwargs)


@pytest.mark.parametrize("level,expected", [(0, "NORMAL"), (24.999, "NORMAL"), (25, "WATCH"), (49.999, "WATCH"), (50, "WARNING"), (74.999, "WARNING"), (75, "CRITICAL"), (100, "CRITICAL")])
def test_every_initial_boundary(level, expected):
    result, _ = evaluate_status(reading(level), TRANSPORT, CONFIG, NOW)
    assert result["hazardState"] == result["displayState"] == expected
    assert result["serviceState"] == "NORMAL"
    assert result["simulated"]
    assert f"HAZARD_{expected}" in result["reasonCodes"]


@pytest.mark.parametrize("state,limit,lower", [("WATCH", 22, "NORMAL"), ("WARNING", 47, "WATCH"), ("CRITICAL", 72, "WARNING")])
def test_all_recovery_boundaries_and_exact_dwell(state, limit, lower):
    _, memory = evaluate_status(reading(limit), TRANSPORT, CONFIG, NOW, TransitionState(state))
    assert memory.hazard == state and memory.candidate is None
    _, memory = evaluate_status(reading(limit - .001), TRANSPORT, CONFIG, NOW, memory)
    assert memory.candidate == lower
    status, memory = evaluate_status(reading(limit - .001), TRANSPORT, CONFIG, NOW + timedelta(seconds=4.99), memory)
    assert status["hazardState"] == state
    status, memory = evaluate_status(reading(limit - .001), TRANSPORT, CONFIG, NOW + timedelta(seconds=5), memory)
    assert status["hazardState"] == lower


def test_rise_dwell_resets_when_boundary_crossing_is_not_continuous():
    _, memory = evaluate_status(reading(25), TRANSPORT, CONFIG, NOW, TransitionState("NORMAL"))
    assert memory.candidate == "WATCH"
    _, memory = evaluate_status(reading(24), TRANSPORT, CONFIG, NOW + timedelta(seconds=2), memory)
    assert memory.candidate is None
    _, memory = evaluate_status(reading(25), TRANSPORT, CONFIG, NOW + timedelta(seconds=3), memory)
    status, memory = evaluate_status(reading(25), TRANSPORT, CONFIG, NOW + timedelta(seconds=5), memory)
    assert status["hazardState"] == "NORMAL"
    status, memory = evaluate_status(reading(25), TRANSPORT, CONFIG, NOW + timedelta(seconds=6), memory)
    assert status["hazardState"] == "WATCH"


@pytest.mark.parametrize("age,quality,expected,code", [(30, "valid", "NORMAL", "HAZARD_NORMAL"), (30.001, "valid", "UNKNOWN", "SENSOR_STALE"), (-5, "valid", "NORMAL", "HAZARD_NORMAL"), (-5.001, "valid", "UNKNOWN", "SENSOR_FUTURE"), (0, "stale", "UNKNOWN", "SENSOR_STALE"), (0, "fault", "UNKNOWN", "SENSOR_FAULT"), (0, "unknown", "UNKNOWN", "SENSOR_QUALITY_UNKNOWN")])
def test_sensor_freshness_quality_and_future_boundaries(age, quality, expected, code):
    result, memory = evaluate_status(reading(observed=NOW-timedelta(seconds=age), quality=quality), TRANSPORT, CONFIG, NOW, TransitionState("CRITICAL"))
    if expected == "NORMAL":
        # Existing critical memory intentionally recovers only after dwell.
        assert result["dataFreshness"]["sensor"] == "fresh"
    else:
        assert result["hazardState"] == expected
        assert code in result["reasonCodes"]
        assert memory == TransitionState()


@pytest.mark.parametrize("sensor,code", [(None, "SENSOR_MISSING"), ({"observedAt": "2026-09-22T00:00:00", "quality": "valid"}, "SENSOR_TIMESTAMP_INVALID"), ({"quality": "valid"}, "SENSOR_TIMESTAMP_INVALID")])
def test_missing_or_naive_timestamp_is_unknown(sensor, code):
    status, _ = evaluate_status(sensor, TRANSPORT, CONFIG, NOW)
    assert status["hazardState"] == "UNKNOWN"
    assert code in status["reasonCodes"]


def test_critical_hazard_never_infers_suspension_and_transport_outage_independent():
    status, _ = evaluate_status(reading(100), {**TRANSPORT, "freshness": "unavailable", "feeds": {}}, CONFIG, NOW)
    assert status["hazardState"] == "CRITICAL"
    assert status["serviceState"] == "UNKNOWN"


@pytest.mark.parametrize("effect,expected", [("NO_SERVICE", "SUSPENDED"), ("DETOUR", "DISRUPTED"), ("REDUCED_SERVICE", "DISRUPTED"), ("MODIFIED_SERVICE", "DISRUPTED"), ("SIGNIFICANT_DELAYS", "DISRUPTED"), ("OTHER_EFFECT", "NORMAL")])
def test_official_alert_classification_preserves_hazard(effect, expected):
    transport = {**TRANSPORT, "alerts": [{"effect": effect}]}
    result, _ = evaluate_status(reading(quality="fault"), transport, CONFIG, NOW)
    assert result["hazardState"] == "UNKNOWN" and result["serviceState"] == expected


def test_service_alert_freshness_not_masked_by_vehicles():
    transport = {**TRANSPORT, "feeds": {"serviceAlerts": {"freshness": "stale"}}, "alerts": [{"effect": "NO_SERVICE"}]}
    status, _ = evaluate_status(reading(), transport, CONFIG, NOW)
    assert status["serviceState"] == "UNKNOWN"


def test_expired_and_future_alerts_ignored():
    for alert in [{"effect": "NO_SERVICE", "activeUntil": NOW.isoformat()}, {"effect": "NO_SERVICE", "activeFrom": (NOW+timedelta(seconds=1)).isoformat()}, {"effect": "NO_SERVICE", "activePeriods": [{"start": (NOW+timedelta(days=1)).isoformat()}]}]:
        result, _ = evaluate_status(reading(), {**TRANSPORT, "alerts": [alert]}, CONFIG, NOW)
        assert result["serviceState"] == "NORMAL"


def test_cancelled_trip_is_disruption_not_route_suspension():
    status, _ = evaluate_status(reading(), {**TRANSPORT, "tripUpdates": [{"scheduleRelationship": "CANCELED"}]}, CONFIG, NOW)
    assert status["serviceState"] == "DISRUPTED"


def test_stale_trip_records_and_missing_stop_data_do_not_determine_service():
    for update in [{"scheduleRelationship": "CANCELED", "freshness": "stale"},
                   {"arrivalDelaySeconds": 500, "freshness": "stale"},
                   {"tripDelaySeconds": 500, "stopScheduleRelationship": "NO_DATA"},
                   {"tripDelaySeconds": 500, "stopScheduleRelationship": "SKIPPED"},
                   {"tripDelaySeconds": 500, "arrivalDelaySeconds": 0}]:
        status, _ = evaluate_status(reading(), {**TRANSPORT, "tripUpdates": [update]}, CONFIG, NOW)
        assert status["serviceState"] == "NORMAL"
    status, _ = evaluate_status(reading(), {**TRANSPORT, "tripUpdates": [{"tripDelaySeconds": 70, "freshness": "fresh"}]}, CONFIG, NOW)
    assert status["serviceState"] == "DELAYED"


def test_delays_only_count_from_fresh_trip_feed():
    transport = {**TRANSPORT, "tripUpdates": [{"arrivalDelaySeconds": 60}]}
    assert evaluate_status(reading(), transport, CONFIG, NOW)[0]["serviceState"] == "DELAYED"
    transport["feeds"] = {**TRANSPORT["feeds"], "tripUpdates": {"freshness": "stale"}}
    assert evaluate_status(reading(), transport, CONFIG, NOW)[0]["serviceState"] == "NORMAL"


def test_full_route_fixture_provenance_and_input_purity():
    import copy
    transport = {**TRANSPORT, "source": "fixture", "alerts": [{"effect": "NO_SERVICE"}]}
    initial = copy.deepcopy(transport)
    status, _ = evaluate_status(reading(100), transport, CONFIG, NOW, impact_scope="full_route_demo")
    assert status["serviceSource"] == "fixture"
    assert "FIXTURE_NO_SERVICE" in status["reasonCodes"]
    assert "SIMULATED_FULL_ROUTE_IMPACT" in status["reasonCodes"]
    assert transport == initial
