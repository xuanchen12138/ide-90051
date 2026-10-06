"""Serial protocol regression checks; no physical hardware is used by these tests."""
from datetime import datetime, timedelta, timezone
import json
import queue
import sys
import threading
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from adapters.serial_sensor import (
    FrameError, FloatFrame, LineDecoder, ReadingTracker, UINT32,
    ingestion_url, parse_frame, post_reading,
)

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def wire(level=0, sequence=0, uptime_ms=100, **changes):
    value = {"type": "flood_reading", "protocolVersion": 1, "sequence": sequence,
             "uptimeMs": uptime_ms, "lowerFloat": level in (1, 2),
             "upperFloat": level in (-1, 2), "floodLevel": level, **changes}
    return json.dumps(value).encode()


@pytest.mark.parametrize("level,scenario,quality", [(0, 0, "valid"), (1, 60, "valid"), (2, 90, "valid"), (-1, 0, "fault")])
def test_float_level_maps_to_demonstration_risk_not_measured_mm(level, scenario, quality):
    frame = parse_frame(wire(level))
    reading = ReadingTracker("site-116", "usb-001").observation(frame, NOW)
    assert reading["scenarioLevel"] == scenario
    assert reading["floatLevel"] == level
    assert reading["quality"] == quality
    assert reading["source"] == "physical"
    assert reading["waterDepthMm"] is None
    assert reading["rainfallIntensityMmPerHour"] is None
    assert reading["sensorUptimeMs"] == 100
    assert UUID(reading["readingId"])


@pytest.mark.parametrize("changes", [
    {"lowerFloat": 0}, {"upperFloat": "false"}, {"floodLevel": True},
    {"floodLevel": 2}, {"sequence": -1}, {"sequence": UINT32},
    {"sequence": 1.5}, {"uptimeMs": True}, {"uptimeMs": None},
    {"protocolVersion": True}, {"protocolVersion": 2}, {"type": "other"},
    {"unexpected": "field"},
])
def test_reject_malformed_or_inconsistent_json(changes):
    with pytest.raises(FrameError):
        parse_frame(wire(**changes))


@pytest.mark.parametrize("line", [b'{"type":', b"{\xff}", b"{" + b"a" * 2000])
def test_invalid_json_encoding_and_length_are_rejected(line):
    with pytest.raises(FrameError):
        parse_frame(line)


def test_diagnostics_are_not_observations():
    for line in (b"", b"Flood monitoring system started", b"Lower float changed after 101 ms", b"LEVEL 2"):
        assert parse_frame(line) is None


@pytest.mark.parametrize("text,level", [("LEVEL 0", 0), ("LEVEL 1", 1), ("LEVEL 2", 2), ("INVALID SENSOR STATE", -1)])
def test_original_sketch_exact_level_events_are_supported(text, level):
    frame = parse_frame(f"Flood level changed to: {text}\r\n")
    assert frame.legacy and frame.level == level and frame.uptime_ms is None


def test_partial_lines_wait_for_newline_and_oversize_discards_to_boundary():
    decoder = LineDecoder(limit=4)
    assert decoder.feed(b"ab") == []
    assert decoder.feed(b"c\r\n") == [b"abc"]
    assert decoder.feed(b"123456789") == []
    assert not decoder.buffer and decoder.dropping
    assert decoder.feed(b"xyz\nok\n") == [b"ok"]
    assert decoder.feed(b"") == []


def test_heartbeat_is_new_observation_but_duplicate_never_refreshes_liveness():
    tracker = ReadingTracker("s", "d")
    first = tracker.observation(parse_frame(wire(sequence=5, uptime_ms=5000)), NOW)
    duplicate = tracker.observation(parse_frame(wire(sequence=5, uptime_ms=5000)), NOW + timedelta(seconds=10))
    conflicting_sequence = tracker.observation(parse_frame(wire(level=2, sequence=5, uptime_ms=5001)), NOW + timedelta(seconds=11))
    next_reading = tracker.observation(parse_frame(wire(sequence=6, uptime_ms=6000)), NOW + timedelta(seconds=1))
    assert duplicate is None and conflicting_sequence is None
    assert first["observedAt"] == NOW.isoformat()
    assert next_reading["readingId"] != first["readingId"]
    assert next_reading["floatLevel"] == first["floatLevel"]


def test_out_of_order_frames_rejected_and_reset_starts_new_epoch():
    tracker = ReadingTracker("s", "d")
    old = tracker.observation(parse_frame(wire(sequence=50, uptime_ms=50000)), NOW)
    assert tracker.observation(parse_frame(wire(sequence=49, uptime_ms=49000)), NOW) is None
    reset = tracker.observation(parse_frame(wire(sequence=0, uptime_ms=100)), NOW + timedelta(seconds=1))
    assert reset and reset["readingId"] != old["readingId"] and tracker.epoch == 1
    assert tracker.observation(parse_frame(wire(sequence=1, uptime_ms=1100)), NOW + timedelta(seconds=2))


def test_reset_after_only_first_frame_is_not_mistaken_for_duplicate():
    tracker = ReadingTracker("s", "d")
    old = tracker.observation(parse_frame(wire(sequence=0, uptime_ms=200)), NOW)
    reset = tracker.observation(parse_frame(wire(sequence=0, uptime_ms=100)), NOW + timedelta(seconds=1))
    assert reset and reset["readingId"] != old["readingId"]


def test_millis_and_sequence_wrap_without_reboot():
    tracker = ReadingTracker("s", "d")
    tracker.observation(parse_frame(wire(sequence=UINT32 - 1, uptime_ms=UINT32 - 500)), NOW)
    assert tracker.observation(parse_frame(wire(sequence=0, uptime_ms=500)), NOW + timedelta(seconds=1))
    assert tracker.epoch == 0


@pytest.mark.parametrize("url", ["http://192.168.1.3:8000", "http://example.org", "file:///tmp/a", "https://user:secret@example.org", "https://example.org/?token=secret"])
def test_api_url_refuses_unsafe_token_destinations(url):
    with pytest.raises(ValueError):
        ingestion_url(url)


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8001/", "http://[::1]:8000", "https://example.org"])
def test_loopback_http_and_explicit_https_are_allowed(url):
    assert ingestion_url(url).endswith("/api/v1/sensors/readings")


def test_http_retry_preserves_reading_identity_timestamp_and_does_not_follow_redirects():
    requests = []
    statuses = iter([503, 201, 302, 401, 422])
    def send(request):
        requests.append(json.loads(request.content))
        return httpx.Response(next(statuses), headers={"Location": "https://other.invalid"})
    reading = ReadingTracker("s", "d").observation(parse_frame(wire()), NOW)
    with httpx.Client(transport=httpx.MockTransport(send)) as client:
        assert [post_reading(client, "http://localhost/api/v1/sensors/readings", reading, "test-token") for _ in range(5)] == ["retry", "accepted", "rejected", "unauthorized", "rejected"]
    assert all(value == reading for value in requests)


def test_network_timeout_is_retryable():
    def send(request):
        raise httpx.ReadTimeout("timeout", request=request)
    with httpx.Client(transport=httpx.MockTransport(send)) as client:
        assert post_reading(client, "http://localhost/api/v1/sensors/readings", {}) == "retry"


def test_serial_silence_does_not_replay_state_and_disconnect_does_not_create_reading(monkeypatch):
    from scripts.collect_sensor import read_serial
    stop = threading.Event()
    observations = queue.Queue(maxsize=1)
    class FakeSerialError(OSError):
        pass
    class Device:
        in_waiting = 512
        def __init__(self, *args, **kwargs): self.calls = 0
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def reset_input_buffer(self): pass
        def read(self, count):
            self.calls += 1
            if self.calls == 1: return wire(level=1) + b"\n"
            if self.calls < 5: return b""
            stop.set()
            raise FakeSerialError("unplugged")
    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Device, SerialException=FakeSerialError))
    read_serial("TEST", 9600, "s", "d", observations, stop)
    assert observations.qsize() == 1
    assert observations.get()[1]["floatLevel"] == 1


def test_serial_queue_is_bounded_and_keeps_latest_observation(monkeypatch):
    from scripts.collect_sensor import read_serial
    stop = threading.Event()
    observations = queue.Queue(maxsize=1)
    class Device:
        in_waiting = 512
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def reset_input_buffer(self): pass
        def read(self, count):
            stop.set()
            return b"\n".join(wire(level=level, sequence=level, uptime_ms=1000*level) for level in (0, 1, 2)) + b"\n"
    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Device, SerialException=OSError))
    read_serial("TEST", 9600, "s", "d", observations, stop)
    assert observations.qsize() == 1
    assert observations.get()[1]["floatLevel"] == 2
