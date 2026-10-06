from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class SensorReading(BaseModel):
    """Stable ingestion contract. receivedAt is overwritten by the server."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    readingId: UUID
    sensorId: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:-]+$")
    siteId: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:-]+$")
    observedAt: datetime
    receivedAt: datetime | None = None
    scenarioLevel: float = Field(ge=0, le=100, strict=True)
    waterDepthMm: float | None = Field(default=None, ge=0, le=10000, strict=True)
    rainfallIntensityMmPerHour: float | None = Field(default=None, ge=0, le=1000, strict=True)
    trend: Literal["rising", "falling", "steady", "unknown"] = "unknown"
    trendPerMinute: float | None = Field(default=None, strict=True)
    batteryPercent: float | None = Field(default=None, ge=0, le=100, strict=True)
    quality: Literal["valid", "stale", "fault", "unknown"] = "valid"
    source: Literal["mock", "physical"]

    @field_validator("observedAt", "receivedAt", mode="before")
    @classmethod
    def reject_epoch_numbers(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("timestamp must be an ISO-8601 string")
        return value

    @field_validator("observedAt", "receivedAt")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamp requires an explicit timezone")
        return value


class ManualControl(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    level: float = Field(ge=0, le=100, strict=True)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["simulation", "normal"] | None = None
    impactScope: Literal["local_segment", "full_route_demo"] | None = None


class RenderTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    readingId: UUID
    renderedAt: datetime

    @field_validator("renderedAt", mode="before")
    @classmethod
    def reject_epoch_numbers(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("timestamp must be an ISO-8601 string")
        return value

    @field_validator("renderedAt")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp requires an explicit timezone")
        return value
