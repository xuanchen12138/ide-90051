"""Import one bounded, attributed OSM snapshot; normal app startup is fully offline.

Run with --fetch once, then rebuild from the unchanged cache without that flag.
Coordinates and names always come from source elements. Complete source rings
are retained (including holes); the map viewport clips them for presentation.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOUNDS = {"south": -37.839, "west": 144.944, "north": -37.811, "east": 144.978}
SOURCE_URL = "https://overpass-api.de/api/interpreter"
LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
ATTRIBUTION = "© OpenStreetMap contributors"
CACHE = ROOT / "data/basemap"
AREA_KINDS = {"water", "park", "building"}
SELECTORS = [
    'way[building]', 'relation[building][type=multipolygon]',
    'way[highway]', 'way[railway~"^(rail|tram|light_rail)$"]',
    'way[natural=water]', 'relation[natural=water][type=multipolygon]', 'way[waterway=river]',
    'way[waterway=riverbank]', 'relation[waterway=riverbank][type=multipolygon]',
    'way[leisure~"^(park|garden)$"]',
    'relation[leisure~"^(park|garden)$"][type=multipolygon]',
    'way[landuse~"^(grass|recreation_ground|forest)$"]',
    'way[man_made=bridge]', 'relation[man_made=bridge][type=multipolygon]',
    'nwr[tourism][name]',
    'nwr[amenity~"^(arts_centre|theatre|casino|events_venue|conference_centre)$"][name]',
    'node[place~"^(city|suburb|quarter|neighbourhood)$"][name]',
    'nwr[railway=station][name]',
]


def make_query() -> str:
    bbox = ",".join(str(BOUNDS[key]) for key in ("south", "west", "north", "east"))
    return "[out:json][timeout:45];\n(\n" + "".join(
        f"  {selector}({bbox});\n" for selector in SELECTORS
    ) + ");\nout geom;\n"


def json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       indent=2 if pretty else None,
                       separators=None if pretty else (",", ":")) + "\n").encode("utf-8")


def fetch_snapshot(cache: Path = CACHE) -> None:
    """No refresh loops: one explicit bounded request, never app/runtime traffic."""
    import httpx

    path = cache / "southbank-overpass.json"
    if path.exists():
        raise FileExistsError(f"Snapshot already exists: {path}; use a separate --cache for a new snapshot")
    query = make_query()
    response = httpx.post(SOURCE_URL, data={"data": query}, timeout=60,
                          headers={"User-Agent": "SouthbankFloodWatchPrototype/1.0 (bounded educational import)"})
    response.raise_for_status()
    raw = response.content
    payload = json.loads(raw)
    if payload.get("remark") or not payload.get("elements"):
        raise ValueError(f"Incomplete Overpass result: {payload.get('remark', 'no elements')}")
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    (cache / "snapshot.json").write_bytes(json_bytes({
        "sourceUrl": str(response.url), "query": query,
        "retrievedAt": datetime.now(timezone.utc).isoformat(),
        "rawSha256": hashlib.sha256(raw).hexdigest(),
    }, pretty=True))


def coordinates(geometry: list[dict]) -> list[list[float]]:
    """Reject incomplete geometry instead of joining across missing source nodes."""
    if any(point is None or "lon" not in point or "lat" not in point for point in geometry):
        raise ValueError("Missing coordinates in source geometry")
    return [[point["lon"], point["lat"]] for point in geometry]


def signed_area(ring: list[list[float]]) -> float:
    # Translate first to avoid catastrophic cancellation at longitude 145.
    x0, y0 = ring[0]
    return sum((a[0] - x0) * (b[1] - y0) - (b[0] - x0) * (a[1] - y0)
               for a, b in zip(ring, ring[1:])) / 2


def orient(ring: list[list[float]], *, outer: bool) -> list[list[float]]:
    if len(ring) < 4 or ring[0] != ring[-1] or signed_area(ring) == 0:
        raise ValueError("An OSM area must contain a nonzero closed ring")
    return ring if (signed_area(ring) > 0) == outer else list(reversed(ring))


def stitch_rings(parts: list[list[list[float]]]) -> list[list[list[float]]]:
    """Stitch relation member ways in either direction, without invented edges."""
    if any(len(part) < 2 for part in parts):
        raise ValueError("OSM multipolygon contains an incomplete member way")
    remaining = [list(part) for part in parts]
    rings = []
    while remaining:
        ring = remaining.pop(0)
        while ring[0] != ring[-1]:
            for index, part in enumerate(remaining):
                if ring[-1] == part[0]:
                    ring.extend(part[1:])
                elif ring[-1] == part[-1]:
                    ring.extend(reversed(part[:-1]))
                elif ring[0] == part[-1]:
                    ring = part[:-1] + ring
                elif ring[0] == part[0]:
                    ring = list(reversed(part[1:])) + ring
                else:
                    continue
                remaining.pop(index)
                break
            else:
                raise ValueError("OSM multipolygon has an unclosed member ring")
        if len(ring) < 4:
            raise ValueError("OSM multipolygon has a degenerate ring")
        rings.append(ring)
    return rings


def point_in_ring(point: list[float], ring: list[list[float]]) -> bool:
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:]):
        if (a[1] > y) != (b[1] > y):
            crossing = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < crossing:
                inside = not inside
    return inside


def relation_geometry(element: dict) -> dict:
    outer_parts, inner_parts = [], []
    for member in element.get("members", []):
        if member["type"] != "way":
            if member.get("role") in {"outer", "inner"}:
                raise ValueError("Nested area members require explicit support")
            continue
        if member.get("role", "") in {"outer", ""}:
            outer_parts.append(coordinates(member.get("geometry", [])))
        elif member.get("role") == "inner":
            inner_parts.append(coordinates(member.get("geometry", [])))
    polygons = [[orient(ring, outer=True)] for ring in stitch_rings(outer_parts)]
    if not polygons:
        raise ValueError("OSM area relation has no outer ring")
    for inner in stitch_rings(inner_parts):
        candidates = [p for p in polygons if point_in_ring(inner[0], p[0])]
        if not candidates:
            raise ValueError("OSM inner ring has no containing outer ring")
        min(candidates, key=lambda p: abs(signed_area(p[0]))).append(orient(inner, outer=False))
    return {"type": "Polygon", "coordinates": polygons[0]} if len(polygons) == 1 else {
        "type": "MultiPolygon", "coordinates": polygons}


def classify(tags: dict) -> str | None:
    if tags.get("natural") == "water" or tags.get("waterway") in {"riverbank", "river"}:
        return "water"
    if tags.get("building") and tags["building"] not in {"no", "construction"}:
        return "building"
    if tags.get("leisure") in {"park", "garden"} or tags.get("landuse") in {"grass", "recreation_ground", "forest"}:
        return "park"
    if tags.get("man_made") == "bridge":
        return "bridge"
    if tags.get("railway") in {"rail", "tram", "light_rail"}:
        return "rail"
    if tags.get("highway") and tags["highway"] not in {"proposed", "construction"}:
        return "bridge" if tags.get("bridge", "no") != "no" else "road"
    return None


def landmark_type(tags: dict) -> str | None:
    if not tags.get("name"):
        return None
    if tags.get("place") in {"city", "suburb", "quarter", "neighbourhood"}:
        return "place"
    if tags.get("railway") == "station":
        return "station"
    if tags.get("amenity") in {"arts_centre", "theatre", "casino", "events_venue", "conference_centre"}:
        return tags["amenity"]
    if tags.get("tourism") in {"museum", "attraction", "gallery", "aquarium", "artwork", "hotel"}:
        return tags["tourism"]
    if tags.get("building") and tags["building"] != "no":
        return "building"
    return None


def source_geometry(element: dict, kind: str | None) -> dict | None:
    if element["type"] == "node":
        return {"type": "Point", "coordinates": [element["lon"], element["lat"]]}
    if element["type"] == "relation":
        if element.get("tags", {}).get("type") != "multipolygon":
            return None
        return relation_geometry(element)
    points = coordinates(element.get("geometry", []))
    if len(points) < 2:
        return None
    tags = element.get("tags", {})
    is_area = (kind in AREA_KINDS and tags.get("waterway") != "river") or tags.get("man_made") == "bridge"
    if points[0] == points[-1] and (is_area or kind is None):
        return {"type": "Polygon", "coordinates": [orient(points, outer=True)]}
    if is_area:
        raise ValueError("Area source way is not a closed ring")
    return {"type": "LineString", "coordinates": points}


def label_position(geometry: dict) -> list[float]:
    """Use the source point or a deterministic point inside the largest polygon."""
    if geometry["type"] == "Point":
        return geometry["coordinates"]
    if geometry["type"] == "LineString":
        return geometry["coordinates"][len(geometry["coordinates"]) // 2]
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    polygon = max(polygons, key=lambda p: abs(signed_area(p[0])))
    outer = polygon[0]
    # A scanline midway between two adjacent distinct latitudes avoids vertices.
    values = sorted({point[1] for point in outer})
    index = max(0, (len(values) - 1) // 2)
    y = (values[index] + values[index + 1]) / 2
    xs = sorted(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                for ring in polygon for a, b in zip(ring, ring[1:])
                if (a[1] > y) != (b[1] > y))
    segments = list(zip(xs[::2], xs[1::2]))
    if not segments:
        raise ValueError("Unable to place label inside OSM polygon")
    left, right = max(segments, key=lambda pair: pair[1] - pair[0])
    return [round((left + right) / 2, 7), round(y, 7)]


def in_bounds(point: list[float]) -> bool:
    return BOUNDS["west"] <= point[0] <= BOUNDS["east"] and BOUNDS["south"] <= point[1] <= BOUNDS["north"]


def properties(element: dict, kind: str) -> dict:
    tags = element.get("tags", {})
    result = {"kind": kind, "osmId": f"{element['type']}/{element['id']}",
              "layer": 0, "bridge": tags.get("bridge", "no") != "no" or tags.get("man_made") == "bridge",
              "tunnel": tags.get("tunnel", "no") != "no"}
    try:
        result["layer"] = int(tags.get("layer", "0"))
    except ValueError:
        pass
    for source, target in {"name": "name", "highway": "roadClass", "railway": "railway",
                           "water": "waterType", "building": "buildingType", "height": "height",
                           "building:levels": "levels", "wikidata": "wikidata"}.items():
        if source in tags:
            result[target] = tags[source]
    if tags.get("waterway") == "river":
        result["waterType"] = "river"
    return result


def convert(payload: dict, snapshot: dict) -> tuple[dict, dict]:
    features, excluded = [], []
    area_member_ids = set()
    elements = sorted(payload["elements"], key=lambda e: (e["type"], e["id"]))
    # Avoid painting individually tagged member areas over their relation's holes.
    for element in elements:
        if element["type"] == "relation" and classify(element.get("tags", {})) in AREA_KINDS:
            area_member_ids.update(member["ref"] for member in element.get("members", []) if member["type"] == "way")
    for element in elements:
        tags = element.get("tags", {})
        kind, label_type = classify(tags), landmark_type(tags)
        if not kind and not label_type:
            continue
        try:
            geometry = source_geometry(element, kind)
            if geometry is None:
                continue
            props = properties(element, kind or "landmark")
            if kind and geometry["type"] != "Point" and not (element["type"] == "way" and element["id"] in area_member_ids and kind in AREA_KINDS):
                features.append({"type": "Feature", "geometry": geometry, "properties": props})
            if label_type:
                point = label_position(geometry)
                if in_bounds(point):
                    features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": point},
                                     "properties": {**props, "kind": "landmark", "landmarkType": label_type,
                                                    "labelPositionMethod": "source-node" if geometry["type"] == "Point" else "derived-from-source-geometry"}})
        except ValueError as error:
            excluded.append({"osmId": f"{element['type']}/{element['id']}", "reason": str(error)})
    # Stable paint ordering; renderer may further separate bridge decks and rails.
    order = {"water": 0, "park": 1, "building": 2, "road": 3, "rail": 4, "bridge": 5, "landmark": 6}
    features.sort(key=lambda f: (order[f["properties"]["kind"]], f["properties"]["layer"], f["properties"]["osmId"]))
    metadata = {"bounds": BOUNDS, "attribution": ATTRIBUTION,
                "attributionUrl": "https://www.openstreetmap.org/copyright", "license": "ODbL-1.0",
                "licenseUrl": LICENSE_URL, "sourceUrl": snapshot["sourceUrl"],
                "retrievedAt": snapshot["retrievedAt"], "osmBaseTimestamp": payload.get("osm3s", {}).get("timestamp_osm_base")}
    collection = {"type": "FeatureCollection", "metadata": metadata, "features": features}
    provenance = {**metadata, "query": snapshot["query"], "rawSha256": snapshot["rawSha256"],
                  "geojsonSha256": hashlib.sha256(json_bytes(collection)).hexdigest(),
                  "sourceElementCount": len(elements), "featureCount": len(features),
                  "countsByKind": dict(sorted(Counter(f["properties"]["kind"] for f in features).items())),
                  "excluded": excluded, "transform": "OSM ways and multipolygon member rings to GeoJSON; preserve complete rings and holes; names copied verbatim; label points derived from source geometry; no positional simplification or invented geometry."}
    return collection, provenance


def build(cache: Path = CACHE, output: Path = ROOT / "config") -> tuple[dict, dict]:
    raw = (cache / "southbank-overpass.json").read_bytes()
    snapshot = json.loads((cache / "snapshot.json").read_text(encoding="utf-8"))
    if hashlib.sha256(raw).hexdigest() != snapshot["rawSha256"]:
        raise ValueError("Cached OSM snapshot SHA-256 does not match provenance")
    payload = json.loads(raw)
    supplements = []
    # The first snapshot needed a tiny source-name supplement for the unnamed
    # river polygons. New --fetch imports include river centerlines in one query.
    river_path = cache / "river-overpass.json"
    if river_path.exists():
        river_raw = river_path.read_bytes()
        river_snapshot = json.loads((cache / "river-snapshot.json").read_text(encoding="utf-8"))
        if hashlib.sha256(river_raw).hexdigest() != river_snapshot["rawSha256"]:
            raise ValueError("Cached river snapshot SHA-256 does not match provenance")
        river_payload = json.loads(river_raw)
        by_id = {(element["type"], element["id"]): element for element in payload["elements"]}
        by_id.update({(element["type"], element["id"]): element for element in river_payload["elements"]})
        payload["elements"] = list(by_id.values())
        supplements.append({**river_snapshot, "osmBaseTimestamp": river_payload.get("osm3s", {}).get("timestamp_osm_base")})
    collection, provenance = convert(payload, snapshot)
    if supplements:
        provenance["supplements"] = supplements
    output.mkdir(parents=True, exist_ok=True)
    (output / "southbank-basemap.geojson").write_bytes(json_bytes(collection))
    (output / "basemap-provenance.json").write_bytes(json_bytes(provenance, pretty=True))
    return collection, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Explicit one-time network import; refuses to overwrite a snapshot")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--output", type=Path, default=ROOT / "config")
    args = parser.parse_args()
    if args.fetch:
        fetch_snapshot(args.cache)
    _, provenance = build(args.cache, args.output)
    print(json.dumps({key: provenance[key] for key in ("featureCount", "countsByKind", "excluded", "osmBaseTimestamp")}, indent=2))


if __name__ == "__main__":
    main()
