"""Reproducible official GTFS discovery; no third-party Python dependencies.

Run ``python -m adapters.gtfs_static --help``. Generated route coordinates are
unaltered GTFS shape vertices. The explicitly conceptual water mask is separate.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Iterator
import urllib.request
import zipfile

DATASET_PAGE = "https://opendata.transport.vic.gov.au/dataset/gtfs-schedule"
METADATA_URL = "https://opendata.transport.vic.gov.au/api/3/action/package_show?id=gtfs-schedule"
TRAM_MEMBER = "3/google_transit.zip"
STOP_NAME = "City Rd/Kings Way #116"
ROUTE_SHORT_NAME = "58"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RemoteZipFile(io.RawIOBase):
    """Read only selected ZIP members using HTTP ranges, with entity validation.

    No archive is extracted to arbitrary paths. If the publisher does not support
    ranges, download its ZIP separately and use --input instead.
    """

    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self.position = 0
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=45) as response:
            self.size = int(response.headers["Content-Length"])
            self.last_modified = response.headers.get("Last-Modified")
            self.etag = response.headers.get("ETag")

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = 0) -> int:
        target = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if target < 0:
            raise ValueError("Cannot seek before start of remote ZIP")
        self.position = target
        return target

    def read(self, size: int = -1) -> bytes:
        size = min(self.size - self.position, size if size >= 0 else self.size - self.position)
        if size <= 0:
            return b""
        headers = {"Range": f"bytes={self.position}-{self.position + size - 1}"}
        if self.etag:
            headers["If-Match"] = self.etag
        request = urllib.request.Request(self.url, headers=headers)
        with urllib.request.urlopen(request, timeout=120) as response:
            expected = f"bytes {self.position}-{self.position + size - 1}/{self.size}"
            if response.status != 206 or response.headers.get("Content-Range") != expected:
                raise ValueError("Publisher did not return the requested ZIP byte range")
            data = response.read(size + 1)
        if len(data) != size:
            raise ValueError("Incomplete remote ZIP byte range")
        self.position += len(data)
        return data


def download_current(destination: Path) -> tuple[Path, dict[str, Any]]:
    """Resolve the current official portal resource and save the tram member."""
    with urllib.request.urlopen(METADATA_URL, timeout=45) as response:
        metadata = json.load(response)
    resources = [r for r in metadata["result"]["resources"] if r.get("format", "").upper() == "ZIP"]
    if len(resources) != 1:
        raise ValueError("Expected one official ZIP resource; inspect portal before proceeding")
    resource = resources[0]
    source_url = resource["url"]
    if not source_url.startswith("https://opendata.transport.vic.gov.au/"):
        raise ValueError("Dataset resource moved off the official portal; review its new provenance")
    version = (resource.get("last_modified") or "").split("T")[0]
    if not version:
        raise ValueError("Official resource has no dataset version date")
    with RemoteZipFile(source_url) as remote:
        with zipfile.ZipFile(remote) as archive:
            tram_bytes = archive.read(TRAM_MEMBER)  # ZIP CRC is checked by read().
        provenance = {
            "sourceUrl": source_url,
            "datasetPage": DATASET_PAGE,
            "datasetVersion": version,
            "retrievedAt": utc_now(),
            "sourceLastModified": remote.last_modified,
            "sourceArchiveSizeBytes": remote.size,
            "archiveMember": TRAM_MEMBER,
            "tramArchiveSha256": hashlib.sha256(tram_bytes).hexdigest(),
            "downloadMethod": "HTTP byte ranges; nested ZIP CRC validated",
            "licence": "Creative Commons Attribution 4.0",
            "licenceUrl": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": "Department of Transport and Planning, Victoria — GTFS Schedule",
        }
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"gtfs-tram-{version}.zip"
    path.write_bytes(tram_bytes)
    (destination / "gtfs-download-metadata.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return path, provenance


def rows(archive: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with archive.open(name) as raw:
        with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
            yield from csv.DictReader(stream)


def distance_m(a: list[float], b: list[float]) -> float:
    """Small-distance haversine; inputs use GeoJSON longitude, latitude order."""
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    delta_lat = lat2 - lat1
    delta_lon = math.radians(b[0] - a[0])
    h = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 6_371_008.8 * 2 * math.asin(min(1, math.sqrt(h)))


def local_segment(coordinates: list[list[float]], center: list[float], half_length_m: float) -> list[list[float]]:
    """Retain original vertices around the nearest point, within an arc-length window."""
    nearest = min(range(len(coordinates)), key=lambda i: distance_m(coordinates[i], center))
    if distance_m(coordinates[nearest], center) > 150:
        raise ValueError("Selected GTFS shape does not pass near the resolved stop")
    start = end = nearest
    total = 0.0
    while start > 0 and total < half_length_m:
        total += distance_m(coordinates[start], coordinates[start - 1])
        start -= 1
    total = 0.0
    while end < len(coordinates) - 1 and total < half_length_m:
        total += distance_m(coordinates[end], coordinates[end + 1])
        end += 1
    return coordinates[start : end + 1]


def conceptual_polygon(center: list[float], east_west_m: float = 180, north_south_m: float = 120) -> dict[str, Any]:
    """Configured illustration only: an ellipse around the verified stop midpoint."""
    lon_delta = east_west_m / (111_320 * math.cos(math.radians(center[1])))
    lat_delta = north_south_m / 111_320
    ring = [[round(center[0] + lon_delta * math.cos(i * math.tau / 32), 8),
             round(center[1] + lat_delta * math.sin(i * math.tau / 32), 8)] for i in range(32)]
    ring.append(ring[0][:])
    return {"type": "Polygon", "coordinates": [ring]}


def discover(archive_path: Path, provenance: dict[str, Any], half_length_m: float = 600) -> tuple[dict, dict, dict]:
    """Derive site, route features and trip lookup from an official tram archive.

    Discovery fails closed if the supplied identity cannot be joined through all
    five source tables. No web-search coordinates or inferred direction labels.
    """
    actual_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if provenance.get("tramArchiveSha256") not in (None, actual_sha):
        raise ValueError("Tram archive does not match the supplied provenance SHA-256")
    provenance = {**provenance, "tramArchiveSha256": actual_sha, "datasetPage": DATASET_PAGE}
    with zipfile.ZipFile(archive_path) as archive:
        route_records = [r for r in rows(archive, "routes.txt") if r["route_short_name"] == ROUTE_SHORT_NAME and r["route_type"] == "0"]
        if not route_records:
            raise ValueError("No Route 58 tram record in supplied dataset")
        route_ids = {r["route_id"] for r in route_records}
        agencies = list(rows(archive, "agency.txt")) if "agency.txt" in archive.namelist() else []
        agency_ids = {r.get("agency_id", "") for r in route_records if r.get("agency_id")}
        if any(not r.get("agency_id") for r in route_records):
            if len(agencies) == 1 and agencies[0].get("agency_id"):
                agency_ids.add(agencies[0]["agency_id"])
                agency_resolution = "Blank routes.agency_id; resolved to the sole agency.txt record per GTFS"
            else:
                agency_resolution = "No unambiguous agency ID; agency-only alert matching is unavailable"
        else:
            agency_resolution = "Explicit routes.agency_id"
        stops = [r for r in rows(archive, "stops.txt") if r["stop_name"].casefold().strip() == STOP_NAME.casefold()]
        if not stops:
            raise ValueError("No matching passenger stop records in supplied dataset")
        stop_ids = {s["stop_id"] for s in stops}
        trips = {r["trip_id"]: r for r in rows(archive, "trips.txt") if r["route_id"] in route_ids}
        connections: dict[str, list[dict[str, str]]] = defaultdict(list)
        for record in rows(archive, "stop_times.txt"):
            if record["stop_id"] in stop_ids and record["trip_id"] in trips:
                connections[record["stop_id"]].append(record)
        if set(connections) != stop_ids:
            raise ValueError("A matching stop is not served by Route 58 in stop_times.txt")
        shape_ids = {t["shape_id"] for t in trips.values()}
        shape_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
        for record in rows(archive, "shapes.txt"):
            if record["shape_id"] in shape_ids:
                shape_rows[record["shape_id"]].append(record)
        if set(shape_rows) != shape_ids:
            raise ValueError("A Route 58 trip references a missing shape")
        table_hashes = {}
        for name in ("agency.txt", "routes.txt", "stops.txt", "trips.txt", "stop_times.txt", "shapes.txt"):
            if name not in archive.namelist():
                continue
            digest = hashlib.sha256()
            with archive.open(name) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            table_hashes[name] = digest.hexdigest()
        calendars = list(rows(archive, "calendar.txt")) if "calendar.txt" in archive.namelist() else []
    center = [sum(float(s["stop_lon"]) for s in stops) / len(stops), sum(float(s["stop_lat"]) for s in stops) / len(stops)]
    if any(distance_m(center, [float(s["stop_lon"]), float(s["stop_lat"])]) > 250 for s in stops):
        raise ValueError("Matching stop records are not in one local cluster")
    # Most frequently scheduled shape serving the site in each GTFS direction.
    # Preserve every shape ID in evidence; two representative paths avoid 42 overlapping lines.
    shape_counts: dict[str, Counter] = defaultdict(Counter)
    for stop_connections in connections.values():
        for record in stop_connections:
            trip = trips[record["trip_id"]]
            shape_counts[trip["direction_id"]][trip["shape_id"]] += 1
    selected = {direction: sorted(counts, key=lambda shape: (-counts[shape], shape))[0] for direction, counts in shape_counts.items()}
    features = []
    for direction, shape_id in sorted(selected.items()):
        coordinates = [[float(r["shape_pt_lon"]), float(r["shape_pt_lat"])] for r in sorted(shape_rows[shape_id], key=lambda r: int(r["shape_pt_sequence"]))]
        example = next(t for t in trips.values() if t["shape_id"] == shape_id)
        properties = {"shapeId": shape_id, "routeId": example["route_id"], "routeShortName": ROUTE_SHORT_NAME,
                      "directionId": direction, "source": "Transport Victoria GTFS Schedule", "datasetVersion": provenance["datasetVersion"]}
        for kind, points in (("route", coordinates), ("local_segment", local_segment(coordinates, center, half_length_m))):
            features.append({"type": "Feature", "id": f"{kind}-{direction}", "properties": {**properties, "kind": kind}, "geometry": {"type": "LineString", "coordinates": points}})
    resolved_stops = []
    for stop in sorted(stops, key=lambda s: s["stop_id"]):
        links = connections[stop["stop_id"]]
        directions = []
        for direction in sorted({trips[r["trip_id"]]["direction_id"] for r in links}):
            linked_trips = [trips[r["trip_id"]] for r in links if trips[r["trip_id"]]["direction_id"] == direction]
            directions.append({"directionId": direction, "headsigns": sorted({t["trip_headsign"] for t in linked_trips}),
                               "tripCount": len(linked_trips), "shapeIds": sorted({t["shape_id"] for t in linked_trips})})
        example_stop_time = links[0]
        example_trip = trips[example_stop_time["trip_id"]]
        resolved = {"stopId": stop["stop_id"], "name": stop["stop_name"], "latitude": float(stop["stop_lat"]),
                    "longitude": float(stop["stop_lon"]), "directions": directions, "stopUrl": stop.get("stop_url"),
                    "verificationExample": {"tripId": example_trip["trip_id"], "routeId": example_trip["route_id"],
                                            "directionId": example_trip["direction_id"], "shapeId": example_trip["shape_id"],
                                            "stopSequence": int(example_stop_time["stop_sequence"])}}
        resolved_stops.append(resolved)
        features.append({"type": "Feature", "id": f"stop-{stop['stop_id']}",
                         "properties": {"kind": "stop", "stopId": stop["stop_id"], "name": stop["stop_name"], "directionId": directions[0]["directionId"]},
                         "geometry": {"type": "Point", "coordinates": [resolved["longitude"], resolved["latitude"]]}})
    service_ids = {t["service_id"] for t in trips.values()}
    route_calendars = [r for r in calendars if r["service_id"] in service_ids]
    provenance["tableSha256"] = table_hashes
    provenance["licence"] = "Creative Commons Attribution 4.0"
    provenance["licenceUrl"] = "https://creativecommons.org/licenses/by/4.0/"
    provenance["attribution"] = "Department of Transport and Planning, Victoria — GTFS Schedule"
    site = {
        "siteId": "city-rd-kings-way-116", "displayName": "City Rd/Kings Way — Stop 116", "passengerStopNumber": "116",
        "routeShortName": ROUTE_SHORT_NAME, "routeLongName": route_records[0]["route_long_name"],
        "gtfsRouteIds": sorted(route_ids), "gtfsStopIds": sorted(stop_ids), "gtfsShapeIds": sorted(shape_ids),
        "gtfsAgencyIds": sorted(agency_ids), "agencyIdResolution": agency_resolution,
        "displayGtfsShapeIds": [shape for _, shape in sorted(selected.items())], "gtfsDatasetVersion": provenance["datasetVersion"],
        "center": {"latitude": round(center[1], 8), "longitude": round(center[0], 8)},
        "focusBounds": {"north": round(center[1] + 0.0048, 8), "south": round(center[1] - 0.0048, 8),
                        "east": round(center[0] + 0.0065, 8), "west": round(center[0] - 0.0065, 8)},
        "stops": resolved_stops, "geometryUrl": "/api/v1/site/geometry", "provenance": provenance,
        "routeTripCount": len(trips), "shapeSelectionMethod": "Most frequently scheduled shape serving the site in each direction",
        "localSegmentHalfLengthMeters": half_length_m,
        "conceptualFlood": conceptual_polygon(center),
        "conceptualFloodDescription": "Illustrative ellipse centred on the verified GTFS stop midpoint; 180 m east/west and 120 m north/south radii. Not an observed or modelled flood boundary.",
        "impactScope": "local_segment",
        "serviceCalendarRange": {"start": min((r["start_date"] for r in route_calendars), default=None),
                                 "end": max((r["end_date"] for r in route_calendars), default=None)},
    }
    index = {trip_id: {"routeId": t["route_id"], "directionId": t["direction_id"], "shapeId": t["shape_id"], "headsign": t["trip_headsign"]} for trip_id, t in sorted(trips.items())}
    return site, {"type": "FeatureCollection", "features": features}, index


def validate_config(archive_path: Path, site: dict[str, Any]) -> None:
    """Re-import to verify every configured ID and each source table fingerprint."""
    imported, _, _ = discover(archive_path, site["provenance"], site["localSegmentHalfLengthMeters"])
    for key in ("gtfsRouteIds", "gtfsStopIds", "gtfsShapeIds", "gtfsAgencyIds", "displayGtfsShapeIds", "stops", "center"):
        if imported[key] != site[key]:
            raise ValueError(f"Configured {key} does not match the imported official dataset")
    if imported["provenance"]["tableSha256"] != site["provenance"]["tableSha256"]:
        raise ValueError("Source table fingerprint mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Resolve and download current official metropolitan tram GTFS")
    parser.add_argument("--input", type=Path, help="Previously downloaded metropolitan tram ZIP (3/google_transit.zip)")
    parser.add_argument("--metadata", type=Path, default=Path("data/gtfs-download-metadata.json"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("config"))
    parser.add_argument("--local-half-length-m", type=float, default=600)
    parser.add_argument("--validate", action="store_true", help="Validate existing config only; do not overwrite it")
    args = parser.parse_args()
    if args.local_half_length_m <= 0:
        parser.error("--local-half-length-m must be positive")
    if args.download:
        archive_path, provenance = download_current(args.data_dir)
    elif args.input:
        archive_path = args.input
        provenance = json.loads(args.metadata.read_text(encoding="utf-8"))
    else:
        parser.error("Supply --download or --input")
    if args.validate:
        site = json.loads((args.output_dir / "site.json").read_text(encoding="utf-8"))
        validate_config(archive_path, site)
        print("Verified configured stops, routes, directions, shapes and table SHA-256 fingerprints.")
        return
    site, geometry, index = discover(archive_path, provenance, args.local_half_length_m)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in (("site.json", site), ("route-58.geojson", geometry), ("gtfs-trip-index.json", index)):
        (args.output_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"datasetVersion": site["gtfsDatasetVersion"], "routeIds": site["gtfsRouteIds"], "stopIds": site["gtfsStopIds"],
                      "displayShapeIds": site["displayGtfsShapeIds"], "tripCount": len(index)}, indent=2))


if __name__ == "__main__":
    main()
