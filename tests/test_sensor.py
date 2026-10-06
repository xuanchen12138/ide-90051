from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from adapters.mock_sensor import MockSensorProvider, SCENARIO_IDS, scenario_value
from adapters.physical_sensor import HttpSensorProvider
from api.store import Store
from domain.models import SensorReading

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


def payload(**kwargs):
    return {"readingId": str(uuid4()), "sensorId": "test", "siteId": "city-rd-kings-way-116", "observedAt": NOW.isoformat(), "source": "physical", "scenarioLevel": 10, **kwargs}


@pytest.mark.parametrize("kwargs", [{"scenarioLevel": -1}, {"scenarioLevel": 101}, {"scenarioLevel": float("nan")}, {"scenarioLevel": True}, {"scenarioLevel": "45"}, {"waterDepthMm": -1}, {"waterDepthMm": float("inf")}, {"rainfallIntensityMmPerHour": -1}, {"batteryPercent": 101}, {"batteryPercent": -1}, {"trendPerMinute": float("inf")}, {"observedAt": "2026-09-22T00:00:00"}, {"receivedAt": "2026-09-22T00:00:00"}, {"observedAt": 0}, {"readingId": "not-uuid"}, {"source": "live"}, {"quality": "good"}, {"unexpected": "value"}])
def test_invalid_contract(kwargs):
    with pytest.raises(ValidationError):
        SensorReading.model_validate(payload(**kwargs))


def test_idempotence_and_conflicting_reading():
    store = Store(":memory:")
    reading = SensorReading.model_validate(payload())
    assert store.put_reading(reading) == "accepted"
    assert store.put_reading(reading.model_copy(update={"receivedAt": NOW})) == "duplicate"
    assert store.put_reading(reading.model_copy(update={"scenarioLevel": 99})) == "conflict"
    assert store.get_reading(str(reading.readingId))["scenarioLevel"] == 10
    store.close()


@pytest.mark.parametrize("scenario", sorted(SCENARIO_IDS))
def test_scenarios_are_repeatable_and_use_stable_contract(scenario):
    provider = MockSensorProvider()
    first = provider.reading("city-rd-kings-way-116", scenario, 18, NOW)
    second = provider.reading("city-rd-kings-way-116", scenario, 18, NOW)
    assert first.scenarioLevel == second.scenarioLevel
    assert first.source == "mock"
    assert first.readingId != second.readingId
    assert SensorReading.model_validate(first.model_dump()) == first


def test_rise_and_recovery_endpoints():
    assert [scenario_value("water-rising", second)[0] for second in (0,12,24,36,48)] == [10,30,55,80,90]
    assert [scenario_value("recovery", second)[0] for second in (0,12,24,36)] == [90,65,40,10]


def test_physical_provider_rejects_mock_and_out_of_order():
    provider = HttpSensorProvider()
    reading = SensorReading.model_validate(payload())
    assert provider.accept(reading)
    assert not provider.accept(reading)
    with pytest.raises(ValueError):
        provider.accept(reading.model_copy(update={"source": "mock"}))
