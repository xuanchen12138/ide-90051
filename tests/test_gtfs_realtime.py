from datetime import datetime, timezone, timedelta

import httpx
import pytest
from google.transit import gtfs_realtime_pb2 as pb

from adapters.gtfs_realtime import TransportAdapter, decode_feed, selector_matches

SITE = {"gtfsRouteIds": ["route-58"], "gtfsStopIds": ["stop-116"], "gtfsAgencyIds": ["tram"]}
INDEX = {"trip-58": {"routeId": "route-58"}}
NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


def feed(timestamp=None):
    f = pb.FeedMessage()
    f.header.gtfs_realtime_version = "2.0"
    f.header.timestamp = int((timestamp or datetime.now(timezone.utc)).timestamp())
    return f


def test_vehicle_matching_and_coordinates():
    f = feed()
    for n, route in enumerate(["route-58", "unrelated", ""]):
        e = f.entity.add(id=str(n))
        e.vehicle.trip.route_id = route
        e.vehicle.trip.trip_id = "trip-58"
        e.vehicle.position.latitude = -37.82
        e.vehicle.position.longitude = 144.96
        e.vehicle.timestamp = int(NOW.timestamp())
    invalid = f.entity.add(id="bad")
    invalid.vehicle.trip.route_id = "route-58"
    invalid.vehicle.position.latitude = float("nan")
    invalid.vehicle.position.longitude = 144.96
    result = decode_feed(f.SerializeToString(), "vehiclePositions", SITE, INDEX)
    assert len(result["records"]) == 2
    assert result["records"][0]["bearing"] is None


def test_delay_missing_is_not_zero_and_negative_is_preserved():
    f = feed()
    update = f.entity.add(id="a").trip_update
    update.trip.trip_id = "trip-58"
    s = update.stop_time_update.add(stop_id="stop-116")
    s.arrival.delay = -12
    s.departure.time = int(NOW.timestamp())
    values = decode_feed(f.SerializeToString(), "tripUpdates", SITE, INDEX)["records"][0]
    assert values["arrivalDelaySeconds"] == -12
    assert values["departureDelaySeconds"] is None
    assert values["departureAt"]


def test_selector_fields_intersect_and_agency_wide_alerts():
    s = pb.EntitySelector(route_id="other", stop_id="stop-116")
    assert not selector_matches(s, SITE, INDEX)
    assert selector_matches(pb.EntitySelector(agency_id="tram"), SITE, INDEX)
    assert not selector_matches(pb.EntitySelector(agency_id="other"), SITE, INDEX)
    assert not selector_matches(pb.EntitySelector(), SITE, INDEX)


@pytest.mark.parametrize("data", [b"bad protobuf", b"", b"\n\x00"])
def test_malformed_rejected(data):
    with pytest.raises(ValueError):
        decode_feed(data, "serviceAlerts", SITE, INDEX)


def test_differential_not_silently_treated_as_complete():
    f = feed()
    f.header.incrementality = pb.FeedHeader.DIFFERENTIAL
    with pytest.raises(ValueError):
        decode_feed(f.SerializeToString(), "vehiclePositions", SITE, INDEX)


@pytest.mark.asyncio
async def test_cache_retained_and_only_failed_feed_marked_stale():
    broken = False
    observed_headers = []
    def handler(request):
        observed_headers.append(request.headers["KeyID"])
        if broken and request.url.path.endswith("service-alerts"):
            return httpx.Response(503)
        return httpx.Response(200, content=feed().SerializeToString())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        a = TransportAdapter(SITE, INDEX, "test-only-sentinel", client=client, retry_delay=0)
        result = await a.refresh()
        assert result["freshness"] == "fresh"
        assert all(f["lastHttpStatus"] == 200 for f in result["feeds"].values())
        broken = True
        result = await a.refresh()
        assert result["feeds"]["serviceAlerts"]["freshness"] == "stale"
        assert result["feeds"]["serviceAlerts"]["lastHttpStatus"] == 503
        assert result["feeds"]["vehiclePositions"]["freshness"] == "fresh"
        assert "test-only-sentinel" not in str(result)
        assert len(observed_headers) == 7  # three initial + three refresh + one retry
        broken = False
        assert (await a.refresh())["freshness"] == "fresh"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["malformed", "timeout", "unauthorized", "rate-limit"])
async def test_failure_is_honest_and_sanitized(failure):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-in-exception", request=request)
        if failure == "malformed":
            return httpx.Response(200, content=b"invalid")
        return httpx.Response(403 if failure == "unauthorized" else 429, text="secret-in-body")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        a = TransportAdapter(SITE, INDEX, "test-secret", client=client, retry_delay=0)
        result = await a.refresh()
        assert result["freshness"] == "unavailable"
        assert "secret" not in str(result)
        expected_status = {"malformed": 200, "timeout": None, "unauthorized": 403, "rate-limit": 429}[failure]
        assert all(f["lastHttpStatus"] == expected_status for f in result["feeds"].values())
        assert calls == (6 if failure in ["timeout", "rate-limit"] else 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [-181, 31])
async def test_timestamp_old_or_future_is_not_fresh(offset):
    def handler(request):
        return httpx.Response(200, content=feed(NOW + timedelta(seconds=offset)).SerializeToString())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        a = TransportAdapter(SITE, INDEX, "test-key", client=client)
        await a.refresh()
        assert a.snapshot(NOW)["freshness"] == "stale"


@pytest.mark.asyncio
async def test_alert_periods_keep_only_current_alerts():
    f = feed(NOW)
    for name, offset in [("current", -100), ("future", 100), ("expired", -500)]:
        a = f.entity.add(id=name).alert
        a.header_text.translation.add(text=name, language="en")
        a.informed_entity.add(route_id="route-58")
        a.effect = pb.Alert.NO_SERVICE
        p = a.active_period.add()
        p.start, p.end = int(NOW.timestamp()) + offset, int(NOW.timestamp()) + offset + 200
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=f.SerializeToString()))) as client:
        a = TransportAdapter(SITE, INDEX, "test-key", client=client)
        await a.refresh()
        assert [x["id"] for x in a.snapshot(NOW)["alerts"]] == ["current"]


@pytest.mark.asyncio
async def test_no_key_does_not_make_network_request():
    def handler(request):
        raise AssertionError("No key must not contact upstream")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        a = TransportAdapter(SITE, INDEX, client=client)
        assert (await a.refresh())["freshness"] == "unavailable"


def test_restart_cached_records_are_stale():
    a = TransportAdapter(SITE, INDEX)
    a.restore({"feeds": {"vehiclePositions": {"fetchedAt": NOW.isoformat(), "feedTimestamp": NOW.isoformat()}},
               "vehicles": [{"latitude": -37, "longitude": 144, "observedAt": NOW.isoformat()}]})
    assert a.snapshot(NOW)["feeds"]["vehiclePositions"]["freshness"] == "stale"


@pytest.mark.asyncio
@pytest.mark.parametrize("observation_offset,expected", [(-181, "stale"), (31, "stale"), (-30, "fresh"), (None, "fresh")])
async def test_trip_observation_freshness_is_independent_from_feed_age(observation_offset, expected):
    now = datetime.now(timezone.utc)
    f = feed(now)
    update = f.entity.add(id="trip").trip_update
    update.trip.trip_id = "trip-58"
    if observation_offset is not None:
        update.timestamp = int(now.timestamp()) + observation_offset
    update.stop_time_update.add(stop_id="stop-116").arrival.delay = 300
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=f.SerializeToString()))) as client:
        adapter = TransportAdapter(SITE, INDEX, "test-key", client=client)
        await adapter.refresh()
        snapshot = adapter.snapshot(now)
    assert snapshot["feeds"]["tripUpdates"]["freshness"] == "fresh"
    assert snapshot["tripUpdates"][0]["freshness"] == expected
    assert snapshot["tripUpdates"][0]["timestampSource"] == ("feed" if observation_offset is None else "observation")


def test_trip_cancellation_and_trip_level_delay_survive_normalization():
    f = feed()
    cancelled = f.entity.add(id="cancelled").trip_update
    cancelled.trip.trip_id = "trip-58"
    cancelled.trip.schedule_relationship = pb.TripDescriptor.CANCELED
    cancelled.timestamp = int(NOW.timestamp())
    delayed = f.entity.add(id="delayed").trip_update
    delayed.trip.trip_id = "trip-58"
    delayed.delay = 180
    delayed.stop_time_update.add(stop_id="stop-116").arrival.delay = 0
    records = decode_feed(f.SerializeToString(), "tripUpdates", SITE, INDEX)["records"]
    assert records[0]["scheduleRelationship"] == "CANCELED"
    assert records[0]["tripDelaySeconds"] is None
    assert records[1]["tripDelaySeconds"] == 180
    assert records[1]["arrivalDelaySeconds"] == 0  # Preserve explicit stop override separately.


@pytest.mark.parametrize("relationship", [pb.TripUpdate.StopTimeUpdate.NO_DATA, pb.TripUpdate.StopTimeUpdate.SKIPPED])
def test_unavailable_stop_predictions_do_not_become_delay_evidence(relationship):
    f = feed()
    update = f.entity.add(id="trip").trip_update
    update.trip.trip_id = "trip-58"
    stop = update.stop_time_update.add(stop_id="stop-116", schedule_relationship=relationship)
    stop.arrival.delay = 300  # Invalid publisher data must not override NO_DATA/SKIPPED.
    record = decode_feed(f.SerializeToString(), "tripUpdates", SITE, INDEX)["records"][0]
    assert record["arrivalDelaySeconds"] is None
    assert record["stopScheduleRelationship"] in ("NO_DATA", "SKIPPED")
