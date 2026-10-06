"""Real local map identity, multipolygon topology and reproducible import checks."""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import pytest

from scripts.build_basemap import (
    BOUNDS, CACHE, build, classify, convert, label_position, point_in_ring,
    relation_geometry, signed_area, source_geometry, stitch_rings,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def basemap():
    return json.loads((ROOT / "config/southbank-basemap.geojson").read_text(encoding="utf-8"))


def polygons(feature):
    geometry = feature["geometry"]
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    return []


def test_committed_map_identifies_actual_melbourne_buildings_roads_and_bridges(basemap):
    features = basemap["features"]
    names = {feature["properties"].get("name") for feature in features}
    assert {"Crown Melbourne", "Melbourne Convention Centre", "Melbourne Exhibition Centre",
            "Kings Bridge", "Queens Bridge", "Spencer Street Bridge", "Sandridge Bridge",
            "Flinders Street", "Southbank", "City Road", "Kings Way", "Yarra River"} <= names
    counts = Counter(feature["properties"]["kind"] for feature in features)
    assert counts["building"] > 500
    assert counts["road"] > 500
    assert counts["bridge"] > 10
    assert counts["rail"] > 10
    assert counts["park"] > 10
    crown = next(f for f in features if f["properties"]["osmId"] == "way/13306836" and f["properties"]["kind"] == "building")
    assert crown["properties"]["name"] == "Crown Melbourne"
    assert crown["geometry"]["type"] == "Polygon"


def test_yarra_has_real_surface_polygon_and_separate_named_source_centerline(basemap):
    features = basemap["features"]
    river = next(f for f in features if f["properties"]["osmId"] == "relation/954522")
    assert river["properties"]["kind"] == "water"
    assert len(river["geometry"]["coordinates"][0]) > 100
    # This exact source river centerline vertex lies by Kings Bridge.
    assert point_in_ring([144.9604387, -37.8208842], river["geometry"]["coordinates"][0])
    centerlines = [f for f in features if f["properties"]["kind"] == "water" and f["geometry"]["type"] == "LineString"]
    assert any(f["properties"].get("name") == "Yarra River" for f in centerlines)
    assert any([144.9604387, -37.8208842] in f["geometry"]["coordinates"] for f in centerlines)


def test_real_rings_are_closed_with_holes_and_multipolygons_preserved(basemap):
    hole_count = multipolygon_count = 0
    for feature in basemap["features"]:
        multipolygon_count += feature["geometry"]["type"] == "MultiPolygon"
        for polygon in polygons(feature):
            hole_count += len(polygon) - 1
            for index, ring in enumerate(polygon):
                assert len(ring) >= 4 and ring[0] == ring[-1]
                assert (signed_area(ring) > 0) == (index == 0)
                assert all(math.isfinite(value) for point in ring for value in point)
                if index:
                    assert point_in_ring(ring[0], polygon[0])
    assert hole_count >= 20
    assert multipolygon_count >= 2


def test_layer_tunnel_bridge_and_road_class_are_preserved(basemap):
    bridges = [f for f in basemap["features"] if f["properties"]["kind"] == "bridge"]
    assert all(f["properties"]["bridge"] for f in bridges)
    assert any(f["geometry"]["type"] == "Polygon" for f in bridges)
    assert any(f["properties"]["layer"] > 0 for f in bridges)
    assert any(f["properties"]["tunnel"] and f["properties"]["layer"] < 0 for f in basemap["features"])
    roads = [f for f in basemap["features"] if f["properties"]["kind"] == "road"]
    assert {"footway", "service", "primary", "secondary"} <= {f["properties"]["roadClass"] for f in roads}


def test_provenance_hash_counts_license_and_source_times_match(basemap):
    provenance = json.loads((ROOT / "config/basemap-provenance.json").read_text(encoding="utf-8"))
    assert provenance["geojsonSha256"] == hashlib.sha256((ROOT / "config/southbank-basemap.geojson").read_bytes()).hexdigest()
    assert provenance["featureCount"] == len(basemap["features"])
    assert provenance["countsByKind"] == dict(Counter(f["properties"]["kind"] for f in basemap["features"]))
    assert provenance["excluded"] == []
    assert provenance["license"] == "ODbL-1.0"
    assert "OpenStreetMap" in provenance["attribution"]
    assert provenance["sourceUrl"] == "https://overpass-api.de/api/interpreter"
    assert provenance["bounds"] == BOUNDS
    assert provenance["retrievedAt"] and provenance["osmBaseTimestamp"]
    assert "out geom" in provenance["query"]
    assert all(f["properties"]["osmId"].split("/")[0] in {"node", "way", "relation"} for f in basemap["features"])
    identifiers = [(f["properties"]["osmId"], f["properties"]["kind"]) for f in basemap["features"]]
    assert len(identifiers) == len(set(identifiers))


def member(ref, role, points):
    return {"type": "way", "ref": ref, "role": role,
            "geometry": [{"lon": x, "lat": y} for x, y in points]}


def test_multipolygon_stitches_reversed_members_and_assigns_holes_to_correct_outer():
    element = {"members": [
        member(1, "outer", [[0, 0], [10, 0], [10, 10]]),
        member(2, "outer", [[0, 0], [0, 10], [10, 10]]),
        member(3, "inner", [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]),
        member(4, "outer", [[20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]),
        member(5, "inner", [[22, 2], [24, 2], [24, 4], [22, 4], [22, 2]]),
    ]}
    geometry = relation_geometry(element)
    assert geometry["type"] == "MultiPolygon"
    assert [len(polygon) for polygon in geometry["coordinates"]] == [2, 2]
    assert all(point_in_ring(poly[1][0], poly[0]) for poly in geometry["coordinates"])
    assert all(signed_area(poly[0]) > 0 and signed_area(poly[1]) < 0 for poly in geometry["coordinates"])


@pytest.mark.parametrize("parts", [[], [[[0, 0], [1, 1]]], [[[0, 0], [1, 1]], []]])
def test_incomplete_multipolygons_fail_without_fabricating_closing_edges(parts):
    if not parts:
        with pytest.raises(ValueError, match="no outer"):
            relation_geometry({"members": []})
    else:
        with pytest.raises(ValueError, match="unclosed|incomplete"):
            stitch_rings(parts)


def test_landmark_point_avoids_a_building_courtyard():
    outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    inner = [[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]]
    point = label_position({"type": "Polygon", "coordinates": [outer, inner]})
    assert point_in_ring(point, outer)
    assert not point_in_ring(point, inner)


def test_line_rivers_remain_lines_and_proposed_roads_are_excluded():
    assert classify({"waterway": "river"}) == "water"
    river = {"type": "way", "id": 1, "tags": {"waterway": "river"},
             "geometry": [{"lon": 144.96, "lat": -37.82}, {"lon": 144.97, "lat": -37.83}]}
    assert source_geometry(river, "water")["type"] == "LineString"
    assert classify({"highway": "proposed"}) is None
    assert classify({"highway": "construction"}) is None
    assert classify({"building": "no"}) is None


def test_malformed_source_is_audited_instead_of_drawn():
    payload = {"elements": [{"type": "way", "id": 1, "tags": {"building": "yes"},
                             "geometry": [{"lon": 0, "lat": 0}, {"lon": 1, "lat": 1}]}]}
    _, provenance = convert(payload, {"sourceUrl": "fixture", "retrievedAt": "fixture", "query": "fixture", "rawSha256": "fixture"})
    assert provenance["featureCount"] == 0
    assert provenance["excluded"] == [{"osmId": "way/1", "reason": "Area source way is not a closed ring"}]


def test_rebuild_from_cached_snapshot_is_byte_identical(tmp_path):
    if not (CACHE / "southbank-overpass.json").exists():
        pytest.skip("Untracked OSM source cache not present; run the documented importer for a fresh snapshot")
    build(CACHE, tmp_path)
    assert (tmp_path / "southbank-basemap.geojson").read_bytes() == (ROOT / "config/southbank-basemap.geojson").read_bytes()
    assert (tmp_path / "basemap-provenance.json").read_bytes() == (ROOT / "config/basemap-provenance.json").read_bytes()


def test_source_cache_tampering_fails_before_writing_map(tmp_path):
    (tmp_path / "southbank-overpass.json").write_text('{"elements":[]}', encoding="utf-8")
    (tmp_path / "snapshot.json").write_text('{"rawSha256":"incorrect"}', encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        build(tmp_path, tmp_path / "generated")
    assert not (tmp_path / "generated").exists()
