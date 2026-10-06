"""Push-based HTTP provider, filled exclusively through validated ingestion."""
from typing import Protocol

from domain.models import SensorReading


class SensorProvider(Protocol):
    async def get_latest(self, site_id: str) -> SensorReading | None: ...


class HttpSensorProvider:
    """A future device POSTs the canonical contract to /api/v1/sensors/readings.

    Keep credentials in SENSOR_INGEST_TOKEN. Never label mock data as physical.
    Mode switches select this provider without changing the frontend contract.
    """

    def __init__(self) -> None:
        self.latest: dict[str, SensorReading] = {}

    def accept(self, reading: SensorReading) -> bool:
        if reading.source != "physical":
            raise ValueError("HTTP sensor provider accepts physical observations only")
        previous = self.latest.get(reading.siteId)
        if previous and reading.observedAt <= previous.observedAt:
            return False
        self.latest[reading.siteId] = reading
        return True

    async def get_latest(self, site_id: str) -> SensorReading | None:
        return self.latest.get(site_id)
