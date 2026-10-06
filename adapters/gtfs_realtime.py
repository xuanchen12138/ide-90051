"""Backend-only GTFS-RT cache. No requests originate in the browser.

Each feed retains its own timestamps and failure state. In particular, a working
vehicle endpoint cannot make a failed service-alert endpoint appear healthy.
"""
from __future__ import annotations

import asyncio
import copy
import math
from datetime import datetime, timezone
from typing import Any

import httpx
from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2 as pb

BASE_URL = "https://api.opendata.transport.vic.gov.au/opendata/public-transport/gtfs/realtime/v1/tram"
FEEDS = {"vehiclePositions": "vehicle-positions", "tripUpdates": "trip-updates", "serviceAlerts": "service-alerts"}
ARRAYS = {"vehiclePositions": "vehicles", "tripUpdates": "tripUpdates", "serviceAlerts": "alerts"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(timestamp: int | float | None) -> str | None:
    if not timestamp:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def age_seconds(value: str | None, now: datetime) -> float | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
        return (now - parsed).total_seconds() if parsed and parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def translated(value: Any) -> str:
    entries = list(value.translation)
    preferred = next((item for item in entries if item.language.lower().startswith("en")), None)
    return (preferred or (entries[0] if entries else None)).text if entries else "No description supplied"


def matches_trip(trip: Any, site: dict, trip_index: dict) -> bool:
    # A supplied route ID takes precedence: never accept a conflicting trip ID.
    if trip.route_id:
        return trip.route_id in site["gtfsRouteIds"]
    return trip.trip_id in trip_index


def selector_matches(selector: Any, site: dict, trip_index: dict) -> bool:
    """GTFS fields within one EntitySelector are AND, selectors are OR."""
    matched = False
    if selector.route_id:
        if selector.route_id not in site["gtfsRouteIds"]:
            return False
        matched = True
    if selector.stop_id:
        if selector.stop_id not in site["gtfsStopIds"]:
            return False
        matched = True
    if selector.HasField("trip"):
        if not matches_trip(selector.trip, site, trip_index):
            return False
        matched = True
    if selector.HasField("route_type"):
        if selector.route_type != 0:
            return False
        matched = True
    if selector.agency_id:
        if selector.agency_id not in site.get("gtfsAgencyIds", []):
            return False
        matched = True
    return matched  # An empty selector is not evidence of Route 58 applicability.


def decode_feed(payload: bytes, feed_name: str, site: dict, trip_index: dict) -> dict:
    feed = pb.FeedMessage()
    try:
        feed.ParseFromString(payload)
    except DecodeError as exc:
        raise ValueError("Malformed GTFS-Realtime response") from exc
    if not feed.IsInitialized() or not feed.header.gtfs_realtime_version:
        raise ValueError("Incomplete GTFS-Realtime response")
    if feed.header.incrementality != pb.FeedHeader.FULL_DATASET:
        raise ValueError("Differential GTFS-Realtime feeds are not supported")
    records: list[dict] = []
    for entity in feed.entity:
        if entity.is_deleted:
            continue
        if feed_name == "vehiclePositions" and entity.HasField("vehicle"):
            v = entity.vehicle
            if not matches_trip(v.trip, site, trip_index) or not v.HasField("position"):
                continue
            lat, lon = v.position.latitude, v.position.longitude
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            records.append({"vehicleId": v.vehicle.id or entity.id, "tripId": v.trip.trip_id or None,
                            "latitude": lat, "longitude": lon,
                            "bearing": v.position.bearing if v.position.HasField("bearing") else None,
                            "observedAt": iso(v.timestamp), "source": "transport-victoria"})
        elif feed_name == "tripUpdates" and entity.HasField("trip_update"):
            update = entity.trip_update
            if not matches_trip(update.trip, site, trip_index):
                continue
            common = {"tripId": update.trip.trip_id or None, "observedAt": iso(update.timestamp),
                      "scheduleRelationship": pb.TripDescriptor.ScheduleRelationship.Name(update.trip.schedule_relationship),
                      "tripDelaySeconds": update.delay if update.HasField("delay") else None,
                      "source": "transport-victoria"}
            if not update.stop_time_update:
                records.append(common)
            for stop in update.stop_time_update:
                result = {**common, "stopId": stop.stop_id or None, "stopSequence": stop.stop_sequence,
                          "stopScheduleRelationship": pb.TripUpdate.StopTimeUpdate.ScheduleRelationship.Name(stop.schedule_relationship),
                          "arrivalDelaySeconds": None, "departureDelaySeconds": None}
                for field in ("arrival", "departure"):
                    event = getattr(stop, field)
                    if stop.HasField(field) and stop.schedule_relationship not in (
                            pb.TripUpdate.StopTimeUpdate.NO_DATA, pb.TripUpdate.StopTimeUpdate.SKIPPED):
                        if event.HasField("delay"):
                            result[field + "DelaySeconds"] = event.delay
                        if event.HasField("time"):
                            result[field + "At"] = iso(event.time)
                records.append(result)
        elif feed_name == "serviceAlerts" and entity.HasField("alert"):
            alert = entity.alert
            if not any(selector_matches(s, site, trip_index) for s in alert.informed_entity):
                continue
            periods = [{"start": iso(p.start), "end": iso(p.end)} for p in alert.active_period]
            records.append({"id": entity.id, "header": translated(alert.header_text),
                            "description": translated(alert.description_text) if alert.HasField("description_text") else None,
                            "effect": pb.Alert.Effect.Name(alert.effect), "activePeriods": periods,
                            "activeFrom": periods[0]["start"] if len(periods) == 1 else None,
                            "activeUntil": periods[0]["end"] if len(periods) == 1 else None,
                            "source": "transport-victoria"})
    return {"feedTimestamp": iso(feed.header.timestamp), "records": records, "entityCount": len(feed.entity)}


def alert_active(alert: dict, now: datetime) -> bool:
    periods = alert.get("activePeriods") or []
    if not periods:
        return True
    for period in periods:
        start_age, end_age = age_seconds(period.get("start"), now), age_seconds(period.get("end"), now)
        if (start_age is None or start_age >= 0) and (end_age is None or end_age < 0):
            return True
    return False


class TransportAdapter:
    def __init__(self, site: dict, trip_index: dict, api_key: str = "", stale_seconds: int = 180,
                 timeout_seconds: float = 8, client: httpx.AsyncClient | None = None,
                 retries: int = 1, retry_delay: float = 0.5):
        self.site, self.trip_index = site, trip_index
        self._key = api_key.strip()
        self.stale_seconds, self.retries, self.retry_delay = stale_seconds, retries, retry_delay
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)
        self._lock = asyncio.Lock()
        self._cache = {key: {"feedTimestamp": None, "fetchedAt": None, "lastAttemptAt": None,
                             "lastHttpStatus": None,
                             "records": [], "entityCount": 0,
                             "error": "Not fetched" if self._key else "Transport API key not configured"} for key in FEEDS}

    def restore(self, snapshot: dict) -> None:
        """Restore persisted public records only; a restart must revalidate each feed."""
        for name, array in ARRAYS.items():
            health = snapshot.get("feeds", {}).get(name, {})
            self._cache[name].update({"feedTimestamp": health.get("feedTimestamp"),
                                     "fetchedAt": health.get("fetchedAt"),
                                     "records": copy.deepcopy(snapshot.get(array, [])),
                                     "error": "Cached before restart; awaiting refresh"})

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def refresh(self) -> dict:
        async with self._lock:
            if self._key:
                await asyncio.gather(*(self._fetch(name, path) for name, path in FEEDS.items()))
            return self.snapshot()

    async def _fetch(self, name: str, path: str) -> None:
        cache = self._cache[name]
        cache["lastAttemptAt"] = utcnow().isoformat()
        for attempt in range(self.retries + 1):
            try:
                async with self._client.stream("GET", f"{BASE_URL}/{path}", headers={
                    "KeyID": self._key, "Accept": "application/x-protobuf, application/octet-stream",
                    "User-Agent": "SouthbankFloodPrototype/1.0"}) as response:
                    cache["lastHttpStatus"] = response.status_code
                    if response.status_code != 200:
                        code = response.status_code
                        cache["error"] = {401: "HTTP 401: transport subscription key rejected",
                                          403: "HTTP 403: transport access denied; verify subscription",
                                          429: "HTTP 429: transport rate limit reached"}.get(code, f"Transport API HTTP {code}")
                        if code in (429, 500, 502, 503, 504) and attempt < self.retries:
                            await asyncio.sleep(self.retry_delay * 2 ** attempt)
                            continue
                        return
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 20 * 1024 * 1024:
                            raise ValueError("Transport response exceeded size limit")
                decoded = decode_feed(bytes(payload), name, self.site, self.trip_index)
                cache.update(decoded)
                cache.update(fetchedAt=utcnow().isoformat(), error=None)
                return
            except httpx.TimeoutException:
                cache["lastHttpStatus"] = None
                cache["error"] = "Transport API timed out"
            except httpx.HTTPError:
                cache["lastHttpStatus"] = None
                cache["error"] = "Transport API connection failed"
            except ValueError:
                cache["error"] = "Malformed or unsupported GTFS-Realtime feed"
                return
            if attempt < self.retries:
                await asyncio.sleep(self.retry_delay * 2 ** attempt)

    def snapshot(self, now: datetime | None = None) -> dict:
        now = now or utcnow()
        result: dict = {"routeShortName": "58", "source": "transport-victoria", "feeds": {},
                        "vehicles": [], "tripUpdates": [], "alerts": []}
        for name, array in ARRAYS.items():
            cache = self._cache[name]
            age = age_seconds(cache["feedTimestamp"], now)
            fetch_age = age_seconds(cache["fetchedAt"], now)
            freshness = "unavailable" if not cache["fetchedAt"] else "stale"
            if (not cache["error"] and age is not None and -30 <= age <= self.stale_seconds
                    and fetch_age is not None and -30 <= fetch_age <= self.stale_seconds):
                freshness = "fresh"
            result["feeds"][name] = {"freshness": freshness, "feedTimestamp": cache["feedTimestamp"],
                                     "fetchedAt": cache["fetchedAt"], "lastAttemptAt": cache["lastAttemptAt"],
                                     "lastHttpStatus": cache["lastHttpStatus"],
                                     "error": cache["error"], "entityCount": cache["entityCount"],
                                     "source": "transport-victoria"}
            records = copy.deepcopy(cache["records"])
            if name == "serviceAlerts":
                records = [a for a in records if alert_active(a, now)]
            if name == "vehiclePositions":
                for v in records:
                    observed_age = age_seconds(v.get("observedAt"), now)
                    v["freshness"] = "fresh" if freshness == "fresh" and observed_age is not None and -30 <= observed_age <= self.stale_seconds else "stale"
            if name == "tripUpdates":
                for update in records:
                    # TripUpdate.timestamp is optional. If absent, explicitly
                    # qualify that freshness relies on the feed creation time.
                    observed_at = update.get("observedAt")
                    update["timestampSource"] = "observation" if observed_at else "feed"
                    observed_age = age_seconds(observed_at or cache["feedTimestamp"], now)
                    update["freshness"] = "fresh" if freshness == "fresh" and observed_age is not None and -30 <= observed_age <= self.stale_seconds else "stale"
            result[array] = records
        health = list(result["feeds"].values())
        result["freshness"] = "fresh" if all(f["freshness"] == "fresh" for f in health) else (
            "unavailable" if all(f["freshness"] == "unavailable" for f in health) else "stale")
        result["fetchedAt"] = max((f["fetchedAt"] for f in health if f["fetchedAt"]), default=None)
        result["feedTimestamp"] = min((f["feedTimestamp"] for f in health if f["feedTimestamp"]), default=None)
        return result
