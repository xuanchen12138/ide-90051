"""Deterministic scenario values; clock, IDs and receive time are injected."""
from datetime import datetime, timedelta
from uuid import uuid4

from domain.models import SensorReading, utc_now


SCENARIOS = [
    {"id": "normal-steady", "name": "Normal steady", "description": "Stable simulated level of 12."},
    {"id": "water-rising", "name": "Water rising", "description": "Rise through all four hazard levels in 48 seconds."},
    {"id": "critical-rise", "name": "Critical rise", "description": "Rapid simulated rise to critical in 16 seconds."},
    {"id": "recovery", "name": "Recovery", "description": "Fall from critical to normal over 36 seconds, with controlled recovery."},
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


def scenario_value(scenario_id: str, elapsed: float) -> tuple[float, str]:
    frames = KEYFRAMES[scenario_id]
    elapsed = max(0, elapsed)
    for index in range(1, len(frames)):
        start, first = frames[index - 1]
        end, last = frames[index]
        if elapsed < end:
            level = first + (last - first) * (elapsed - start) / (end - start)
            return round(level, 3), "rising" if last > first else "falling" if last < first else "steady"
    return float(frames[-1][1]), "steady"


class MockSensorProvider:
    def reading(self, site_id: str, scenario_id: str, elapsed: float, now: datetime, manual_level: float | None = None) -> SensorReading:
        level, trend = scenario_value(scenario_id, elapsed)
        if manual_level is not None:
            level, trend = manual_level, "steady"
        quality = "stale" if scenario_id == "sensor-stale" else "fault" if scenario_id == "sensor-fault" else "valid"
        observed = now - timedelta(seconds=61) if quality == "stale" else now
        return SensorReading(readingId=uuid4(), sensorId="southbank-water-001", siteId=site_id,
                             observedAt=observed, receivedAt=now, scenarioLevel=level,
                             trend=trend, batteryPercent=88, quality=quality, source="mock")

    async def get_latest(self, site_id: str, **kwargs) -> SensorReading:
        options = {"scenario_id": "normal-steady", "elapsed": 0, "now": utc_now(), **kwargs}
        return self.reading(site_id, **options)
