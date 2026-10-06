"""Strict device protocol and bounded buffering for USB float-switch readings."""
from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4, uuid5

from domain.models import FLOAT_SCENARIO_LEVELS, FLOAT_SWITCH_LEVELS

UINT32 = 2**32
MAX_LINE_BYTES = 1024
LEGACY_LEVEL = re.compile(r"Flood level changed to: (LEVEL [012]|INVALID SENSOR STATE)")
SCENARIO_LEVELS = FLOAT_SCENARIO_LEVELS


class FrameError(ValueError):
    """Malformed/inconsistent device message; do not turn it into an observation."""


@dataclass(frozen=True)
class FloatFrame:
    level: int
    lower: bool
    upper: bool
    sequence: int | None = None
    uptime_ms: int | None = None
    legacy: bool = False


def _uint32(value: object, name: str) -> int:
    if type(value) is not int or not 0 <= value < UINT32:
        raise FrameError(f"{name} must be a uint32")
    return value


def parse_frame(line: bytes | str) -> FloatFrame | None:
    """Accept JSON v1 or the original sketch's exact level-change output.

    Diagnostic text/blank lines return None. Malformed JSON and inconsistent
    switches raise FrameError. Legacy messages represent events, not heartbeats.
    """
    if isinstance(line, bytes):
        if len(line) > MAX_LINE_BYTES:
            raise FrameError("line too long")
        try:
            line = line.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise FrameError("invalid UTF-8") from error
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        raise FrameError("line too long")
    line = line.strip()
    legacy = LEGACY_LEVEL.fullmatch(line)
    if legacy:
        level = -1 if legacy[1] == "INVALID SENSOR STATE" else int(legacy[1][-1])
        return FloatFrame(level, level in (1, 2), level in (-1, 2), legacy=True)
    if not line.startswith("{"):
        return None
    try:
        data = json.loads(line)
    except (ValueError, RecursionError) as error:
        raise FrameError("invalid JSON") from error
    if not isinstance(data, dict) or data.get("type") != "flood_reading":
        raise FrameError("unsupported message type")
    if type(data.get("protocolVersion")) is not int or data["protocolVersion"] != 1:
        raise FrameError("unsupported protocol version")
    required = {"type", "protocolVersion", "sequence", "uptimeMs", "lowerFloat", "upperFloat", "floodLevel"}
    if set(data) != required:
        raise FrameError("unexpected or missing protocol fields")
    if type(data["lowerFloat"]) is not bool or type(data["upperFloat"]) is not bool:
        raise FrameError("float switches must be booleans")
    level = data["floodLevel"]
    if type(level) is not int or level not in SCENARIO_LEVELS:
        raise FrameError("unsupported flood level")
    if FLOAT_SWITCH_LEVELS[data["lowerFloat"], data["upperFloat"]] != level:
        raise FrameError("float switches and flood level disagree")
    return FloatFrame(level, data["lowerFloat"], data["upperFloat"],
                      _uint32(data["sequence"], "sequence"), _uint32(data["uptimeMs"], "uptimeMs"))


class LineDecoder:
    """Keep split USB packets until newline; discard overlong lines to newline."""
    def __init__(self, limit: int = MAX_LINE_BYTES):
        self.limit = limit
        self.buffer = bytearray()
        self.dropping = False

    def feed(self, chunk: bytes) -> list[bytes]:
        lines = []
        for byte in chunk:
            if byte == 10:
                if not self.dropping:
                    lines.append(bytes(self.buffer).rstrip(b"\r"))
                self.buffer.clear()
                self.dropping = False
            elif not self.dropping:
                self.buffer.append(byte)
                if len(self.buffer) > self.limit:
                    self.buffer.clear()
                    self.dropping = True
        return lines


def _forward(current: int, previous: int) -> bool:
    return 0 < ((current - previous) % UINT32) < UINT32 // 2


class ReadingTracker:
    """One connection-independent identity/order tracker, with constant memory.

    A reset of both counters near boot starts a new epoch. Native uint32 wrap
    remains in the same epoch. Port reconnect alone does not refresh a duplicate.
    JSON v1 cannot cryptographically distinguish replay from a genuine reboot.
    """
    def __init__(self, site_id: str, sensor_id: str, session_id: UUID | None = None):
        self.site_id = site_id
        self.sensor_id = sensor_id
        self.session_id = session_id or uuid4()
        self.epoch = 0
        self.last_frame: FloatFrame | None = None
        self.legacy_sequence = 0

    def observation(self, frame: FloatFrame, observed_at: datetime | None = None) -> dict | None:
        now = observed_at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("observed_at requires a timezone")
        previous = self.last_frame
        if not frame.legacy and previous is not None and not previous.legacy:
            assert frame.sequence is not None and previous.sequence is not None
            assert frame.uptime_ms is not None and previous.uptime_ms is not None
            forward_sequence = _forward(frame.sequence, previous.sequence)
            forward_time = frame.uptime_ms == previous.uptime_ms or _forward(frame.uptime_ms, previous.uptime_ms)
            reboot = (frame.sequence <= previous.sequence and frame.sequence <= 10 and
                      frame.uptime_ms < previous.uptime_ms and frame.uptime_ms <= 15_000 and
                      not (forward_sequence and forward_time))
            if reboot:
                self.epoch += 1
            elif not (forward_sequence and forward_time):
                return None
        if frame.legacy:
            # Each complete original text event is one observation; no idle replay.
            self.legacy_sequence += 1
        identity = f"{self.epoch}:{self.legacy_sequence if frame.legacy else frame.sequence}:{frame.uptime_ms}"
        self.last_frame = frame
        return {
            "readingId": str(uuid5(self.session_id, identity)),
            "sensorId": self.sensor_id,
            "siteId": self.site_id,
            "observedAt": now.astimezone(timezone.utc).isoformat(),
            "scenarioLevel": SCENARIO_LEVELS[frame.level],
            "waterDepthMm": None,
            "rainfallIntensityMmPerHour": None,
            "trend": "unknown",
            "quality": "fault" if frame.level == -1 else "valid",
            "source": "physical",
            "floatLevel": frame.level,
            "lowerFloat": frame.lower,
            "upperFloat": frame.upper,
            "sensorUptimeMs": frame.uptime_ms,
        }


def ingestion_url(base_url: str) -> str:
    """Never send the ingestion token over non-loopback plaintext HTTP."""
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("API URL must use http or https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API URL cannot contain credentials, query or fragment")
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname.lower() == "localhost"
    if parsed.scheme == "http" and not loopback:
        raise ValueError("Non-loopback API URLs require HTTPS")
    return base_url.rstrip("/") + "/api/v1/sensors/readings"


def post_reading(client, endpoint: str, payload: dict, token: str = "") -> str:
    """One attempt only: callers retain this exact payload on retry.

    Never follow redirects or print exceptions/response bodies containing secrets.
    """
    import httpx
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = client.post(endpoint, json=payload, headers=headers, follow_redirects=False)
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
        return "retry"
    if response.status_code in (200, 201):
        return "accepted"
    if response.status_code == 429 or response.status_code >= 500:
        return "retry"
    if response.status_code in (401, 403):
        return "unauthorized"
    return "rejected"
