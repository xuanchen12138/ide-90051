"""Clearly labelled, deterministic demo trams on verified local Route 58 geometry.

Only unavailable or stale live feeds are replaced. An empty healthy feed is a
successful observation, never a reason to invent a tram or official alert.
"""
from __future__ import annotations

import copy
import json
import math
from bisect import bisect_right
from datetime import datetime, timedelta
from pathlib import Path

from domain.models import iso

FEED_ARRAYS = {"vehiclePositions": "vehicles", "tripUpdates": "tripUpdates", "serviceAlerts": "alerts"}


def distance_metres(first, second):
    mean_lat = math.radians((first[1] + second[1]) / 2)
    return math.hypot((second[0] - first[0]) * math.cos(mean_lat), second[1] - first[1]) * 111320


def offset_for_position(points, lengths, target):
    """Project a stop onto its GTFS polyline and return distance along that line."""
    best_distance, best_offset = float("inf"), 0.0
    aspect = math.cos(math.radians(target[1]))
    for index, (first, second) in enumerate(zip(points, points[1:])):
        dx, dy = (second[0] - first[0]) * aspect, second[1] - first[1]
        squared_length = dx * dx + dy * dy
        if squared_length == 0:
            continue
        tx, ty = (target[0] - first[0]) * aspect, target[1] - first[1]
        fraction = min(1, max(0, (tx * dx + ty * dy) / squared_length))
        squared_distance = (tx - fraction * dx) ** 2 + (ty - fraction * dy) ** 2
        if squared_distance < best_distance:
            best_distance = squared_distance
            best_offset = lengths[index] + fraction * (lengths[index + 1] - lengths[index])
    return best_offset


class MockTransportProvider:
    """Two demonstration vehicles circulate along the actual local GTFS shapes.

    The positions follow the geometry at 8 m/s. The ends wrap for repeatable demo
    playback; times are illustrative predictions, not actual scheduled trips.
    """

    def __init__(self, site: dict, geometry: dict | None = None):
        if geometry is None:
            path = Path(__file__).resolve().parents[1] / "config/route-58.geojson"
            geometry = json.loads(path.read_text(encoding="utf-8"))
        self.site = site
        self.paths = []
        for feature in geometry["features"]:
            if feature["properties"].get("kind") != "local_segment" or feature["geometry"]["type"] != "LineString":
                continue
            points = feature["geometry"]["coordinates"]
            if len(points) < 2:
                continue
            lengths = [0.0]
            for first, second in zip(points, points[1:]):
                lengths.append(lengths[-1] + distance_metres(first, second))
            if lengths[-1] > 0:
                self.paths.append((points, lengths, feature["properties"].get("directionId", str(len(self.paths)))))
        if not self.paths:
            raise ValueError("Verified local Route 58 geometry is required for demo transport")

    def snapshot(self, now: datetime) -> dict:
        vehicles, updates = [], []
        for index, (points, lengths, direction) in enumerate(self.paths):
            offset = (now.timestamp() * 8 + index * lengths[-1] / 2) % lengths[-1]
            segment = min(len(points) - 2, bisect_right(lengths, offset) - 1)
            first, second = points[segment:segment + 2]
            fraction = (offset - lengths[segment]) / (lengths[segment + 1] - lengths[segment])
            longitude = first[0] + (second[0] - first[0]) * fraction
            latitude = first[1] + (second[1] - first[1]) * fraction
            bearing = math.degrees(math.atan2((second[0] - first[0]) * math.cos(math.radians(latitude)), second[1] - first[1])) % 360
            trip_id = f"DEMO-58-{direction}-TRIP"
            vehicles.append({"vehicleId": f"DEMO-58-{direction}", "tripId": trip_id,
                             "latitude": latitude, "longitude": longitude, "bearing": round(bearing, 1),
                             "observedAt": iso(now), "freshness": "fresh", "source": "mock",
                             "demo": True, "label": f"DEMO tram 58 · direction {direction}"})
            stops = self.site.get("stops", [])
            stop = next((stop for stop in stops if any(str(item.get("directionId")) == str(direction)
                         for item in stop.get("directions", []))), None)
            if stop and "latitude" in stop and "longitude" in stop:
                target = [stop["longitude"], stop["latitude"]]
                target_offset = offset_for_position(points, lengths, target)
                stop_id = stop["stopId"]
            else:
                target_offset = lengths[-1] / 2
                stop_ids = self.site.get("gtfsStopIds", [])
                stop_id = stop_ids[index % len(stop_ids)] if stop_ids else None
            seconds = max(5, round(((target_offset - offset) % lengths[-1]) / 8))
            updates.append({"tripId": trip_id, "stopId": stop_id,
                            "observedAt": iso(now), "arrivalAt": iso(now + timedelta(seconds=seconds)),
                            "departureAt": iso(now + timedelta(seconds=seconds + 20)),
                            "arrivalDelaySeconds": 0, "departureDelaySeconds": 0, "tripDelaySeconds": 0,
                            "scheduleRelationship": "SCHEDULED", "stopScheduleRelationship": "SCHEDULED",
                            "timestampSource": "demonstration", "freshness": "fresh", "source": "mock", "demo": True})
        return {"routeShortName": "58", "source": "mock", "freshness": "fresh", "fetchedAt": iso(now), "feedTimestamp": iso(now),
                "vehicles": vehicles, "tripUpdates": updates, "alerts": [],
                "feeds": {name: {"freshness": "fresh", "source": "mock", "fetchedAt": iso(now), "feedTimestamp": iso(now),
                                 "error": None, "entityCount": len(vehicles) if name != "serviceAlerts" else 0}
                          for name in FEED_ARRAYS}}


def apply_fallback(live: dict, mock: dict, *, force_mock: bool = False) -> dict:
    """Return a public effective snapshot without mutating/caching mock as live."""
    result = copy.deepcopy(live)
    live_feeds = {}
    for name in FEED_ARRAYS:
        health = copy.deepcopy(live.get("feeds", {}).get(name, {"freshness": live.get("freshness", "unavailable")}))
        health.setdefault("source", "transport-victoria")
        live_feeds[name] = health
    result["liveFeeds"] = copy.deepcopy(live_feeds)
    result["liveFetchedAt"] = live.get("fetchedAt")
    result["liveFeedTimestamp"] = live.get("feedTimestamp")
    result["feeds"] = live_feeds
    replaced = []
    for name, array in FEED_ARRAYS.items():
        if force_mock or live_feeds[name].get("freshness") != "fresh":
            replaced.append(name)
            result["feeds"][name] = copy.deepcopy(mock["feeds"][name])
            result[array] = copy.deepcopy(mock[array])
        else:
            # Some test/custom adapters omit provenance; the original provider is live.
            result[array] = [{**record, "source": "transport-victoria"} for record in result.get(array, [])]
    result["source"] = "mock" if len(replaced) == len(FEED_ARRAYS) else "mixed" if replaced else "transport-victoria"
    result["fallback"] = bool(replaced) and not force_mock
    result["mockFeeds"] = replaced
    result["fallbackReason"] = ("Live feeds stale or unavailable: " + ", ".join(replaced)) if result["fallback"] else None
    result["freshness"] = "fresh"  # Every effective feed is either fresh live or explicitly marked mock.
    health = list(result["feeds"].values())
    result["fetchedAt"] = max((feed["fetchedAt"] for feed in health if feed.get("fetchedAt")), default=None)
    result["feedTimestamp"] = min((feed["feedTimestamp"] for feed in health if feed.get("feedTimestamp")), default=None)
    return result
