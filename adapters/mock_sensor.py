"""Deterministic scenario values; clock, IDs and receive time are injected."""
from datetime import datetime, timedelta
from uuid import uuid4

from domain.models import SensorReading, utc_now


SCENARIOS = [
    {"id": "normal-steady", "name": "Normal steady", "description": "Dry weather and a stable simulated water level of 12."},
    {"id": "water-rising", "name": "Water rising", "description": "Rain increases from 2 to 80 mm/h while scripted water rises through all four hazard levels in 48 seconds."},
    {"id": "critical-rise", "name": "Critical rise", "description": "Intense simulated rain (30 to 140 mm/h) and a scripted rise to critical in 16 seconds."},
    {"id": "recovery", "name": "Recovery", "description": "Rain eases from 80 to 0 mm/h while scripted water falls over 36 seconds, with controlled recovery."},
    {"id": "sensor-stale", "name": "Stale sensor", "description": "An old observation produces unknown hazard."},
    {"id": "sensor-fault", "name": "Sensor fault", "description": "A reported sensor fault produces unknown hazard."},
    {"id": "transport-feed-unavailable", "name": "Transport feed unavailable", "description": "Fixture outage: service state unknown, hazard remains independent."},
    {"id": "official-alert-present", "name": "Official alert fixture", "description": "Clearly labelled demonstration NO_SERVICE alert; not a live official report."},
]
SCENARIO_IDS = {scenario["id"] for scenario in SCENARIOS}
KEYFRAMES = {
    "normal-steady": [(0, 12)],
    "water-rising": [(0, 10), (12, 30), (24, 55), (36, 80), (48, 90)],
    "critical-rise": [(0, 15), (8, 55), (16, 88)],
    "recovery": [(0, 90), (12, 65), (24, 40), (36, 10)],
    "sensor-stale": [(0, 40)],
    "sensor-fault": [(0, 40)],
    "transport-feed-unavailable": [(0, 12)],
    "official-alert-present": [(0, 12)],
}


# Independent demonstration profiles: these are not a calibrated rainfall/runoff model.
RAINFALL_KEYFRAMES = {
    "normal-steady": [(0, 0)],
    "water-rising": [(0, 2), (12, 15), (24, 35), (36, 65), (48, 80)],
    "critical-rise": [(0, 30), (8, 80), (16, 140)],
    "recovery": [(0, 80), (12, 30), (24, 5), (36, 0)],
    "sensor-stale": [(0, 12)],
    "sensor-fault": [(0, 12)],
    "transport-feed-unavailable": [(0, 0)],
    "official-alert-present": [(0, 0)],
}


def interpolate(frames, elapsed: float) -> tuple[float, str]:
    elapsed = max(0, elapsed)
    for index in range(1, len(frames)):
        start, first = frames[index - 1]
        end, last = frames[index]
        if elapsed < end:
            level = first + (last - first) * (elapsed - start) / (end - start)
            return round(level, 3), "rising" if last > first else "falling" if last < first else "steady"
    return float(frames[-1][1]), "steady"


def rainfall_value(scenario_id: str, elapsed: float) -> float:
    return interpolate(RAINFALL_KEYFRAMES[scenario_id], elapsed)[0]


def scenario_value(scenario_id: str, elapsed: float) -> tuple[float, str]:
    return interpolate(KEYFRAMES[scenario_id], elapsed)


class MockSensorProvider:
    def reading(self, site_id: str, scenario_id: str, elapsed: float, now: datetime, manual_level: float | None = None, manual_rainfall: float | None = None) -> SensorReading:
        level, trend = scenario_value(scenario_id, elapsed)
        if manual_level is not None:
            level, trend = manual_level, "steady"
        rainfall = rainfall_value(scenario_id, elapsed) if manual_rainfall is None else manual_rainfall
        quality = "stale" if scenario_id == "sensor-stale" else "fault" if scenario_id == "sensor-fault" else "valid"
        observed = now - timedelta(seconds=61) if quality == "stale" else now
        return SensorReading(readingId=uuid4(), sensorId="southbank-water-001", siteId=site_id,
                             observedAt=observed, receivedAt=now, scenarioLevel=level, rainfallIntensityMmPerHour=rainfall,
                             trend=trend, batteryPercent=88, quality=quality, source="mock")

    async def get_latest(self, site_id: str, **kwargs) -> SensorReading:
        options = {"scenario_id": "normal-steady", "elapsed": 0, "now": utc_now(), **kwargs}
        return self.reading(site_id, **options)
