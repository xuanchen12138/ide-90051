from datetime import datetime, timezone
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# One shared, immutable demonstration mapping for the serial bridge and API.
# These normalized risk levels are not measured millimetres of water depth.
FLOAT_SCENARIO_LEVELS = MappingProxyType({-1: 0.0, 0: 0.0, 1: 60.0, 2: 90.0})
FLOAT_SWITCH_LEVELS = MappingProxyType({(False, False): 0, (True, False): 1,
                                      (True, True): 2, (False, True): -1})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class SensorReading(BaseModel):
    """Stable ingestion contract; receivedAt is overwritten by the server.

    If supplied, floatLevel/lowerFloat/upperFloat must form a complete and
    consistent trio. Physical float levels 0/1/2 map to demonstration levels
    0/60/90. Invalid switches (floatLevel=-1) require quality=fault and level 0.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    readingId: UUID
    sensorId: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:-]+$")
    siteId: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:-]+$")
    observedAt: datetime
    receivedAt: datetime | None = None
    scenarioLevel: float = Field(ge=0, le=100, strict=True)
    waterDepthMm: float | None = Field(default=None, ge=0, le=10000, strict=True)
    rainfallIntensityMmPerHour: float | None = Field(default=None, ge=0, le=1000, strict=True)
    # Float switches are discrete states, not a measured water depth.
    floatLevel: Literal[-1, 0, 1, 2] | None = None
    lowerFloat: bool | None = Field(default=None, strict=True)
    upperFloat: bool | None = Field(default=None, strict=True)
    sensorUptimeMs: int | None = Field(default=None, ge=0, le=4294967295, strict=True)
    trend: Literal["rising", "falling", "steady", "unknown"] = "unknown"

    trendPerMinute: float | None = Field(default=None, strict=True)
    batteryPercent: float | None = Field(default=None, ge=0, le=100, strict=True)
    quality: Literal["valid", "stale", "fault", "unknown"] = "valid"
    source: Literal["mock", "physical"]

    @field_validator("floatLevel", mode="before")
    @classmethod
    def strict_float_level(cls, value):
        if value is not None and type(value) is not int:
            raise ValueError("floatLevel must be an integer")
        return value

    @model_validator(mode="after")
    def consistent_float_metadata(self):
        metadata = (self.floatLevel, self.lowerFloat, self.upperFloat)
        if not any(value is not None for value in metadata):
            return self
        if any(value is None for value in metadata):
            raise ValueError("floatLevel, lowerFloat and upperFloat must be supplied together")
        if FLOAT_SWITCH_LEVELS[self.lowerFloat, self.upperFloat] != self.floatLevel:
            raise ValueError("float switches and floatLevel disagree")
        if self.floatLevel == -1 and (self.quality != "fault" or self.scenarioLevel != 0):
            raise ValueError("invalid float state requires fault quality and zero demonstration level")
        if self.source == "physical" and self.scenarioLevel != FLOAT_SCENARIO_LEVELS[self.floatLevel]:
            raise ValueError("physical float state and demonstration level disagree")
        return self

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


class RainfallControl(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    intensityMmPerHour: float = Field(ge=0, le=200, strict=True)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["simulation", "normal"] | None = None
    impactScope: Literal["local_segment", "full_route_demo"] | None = None
    transportMode: Literal["auto", "mock"] | None = None


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
