"""Offline identity contract tests plus re-import verification when the source is present."""

import copy
import csv
import io
import json
from pathlib import Path
import zipfile

import pytest

from adapters.gtfs_static import discover, validate_config

ROOT = Path(__file__).resolve().parents[1]


def write_fixture(path, *, missing_connection=False, missing_shape=False):
    """Deliberately synthetic IDs ensure public stop number never becomes stop_id."""
    tables = {
        "agency.txt": "agency_id,agency_name\nfixture-agency,Fixture Transit\n",
        "routes.txt": "route_id,route_short_name,route_long_name,route_type\nfixture-route,58,Fixture termini,0\nother,59,Other,0\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nplatform-a,City Rd/Kings Way #116,-37.8262,144.9606\nplatform-b,City Rd/Kings Way #116,-37.8263,144.9608\n116,Unrelated stop,-37.8000,144.9000\n",
        "trips.txt": "route_id,service_id,trip_id,shape_id,trip_headsign,direction_id\nfixture-route,weekday,a,path-a,North terminus,0\nfixture-route,weekday,b,path-b,South terminus,1\nother,weekday,unrelated,path-other,Elsewhere,0\n",
        "stop_times.txt": "trip_id,stop_id,stop_sequence\na,platform-a,4\n" + ("" if missing_connection else "b,platform-b,5\n") + "unrelated,116,1\n",
        "shapes.txt": "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\npath-a,-37.8300,144.9606,10\npath-a,-37.8262,144.9606,20\npath-a,-37.8200,144.9606,30\n" + ("" if missing_shape else "path-b,-37.8200,144.9608,10\npath-b,-37.8263,144.9608,20\npath-b,-37.8300,144.9608,30\n"),
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in tables.items():
            archive.writestr(name, content)


def test_identity_is_joined_across_stops_stop_times_trips_routes_and_shapes(tmp_path):
    archive = tmp_path / "fixture.zip"
    write_fixture(archive)
    site, geometry, index = discover(archive, {"datasetVersion": "fixture-only"})
    assert site["gtfsStopIds"] == ["platform-a", "platform-b"]
    assert site["gtfsRouteIds"] == ["fixture-route"]
    assert site["gtfsAgencyIds"] == ["fixture-agency"]
    assert [s["directions"][0]["directionId"] for s in site["stops"]] == ["0", "1"]
    assert set(index) == {"a", "b"}
    paths = [f for f in geometry["features"] if f["properties"]["kind"] == "route"]
    assert paths[0]["geometry"]["coordinates"] == [[144.9606, -37.83], [144.9606, -37.8262], [144.9606, -37.82]]
    assert len(paths) == 2
    assert site["conceptualFlood"]["coordinates"][0][0] == site["conceptualFlood"]["coordinates"][0][-1]
    validate_config(archive, site)


@pytest.mark.parametrize("broken", ["missing_connection", "missing_shape"])
def test_incomplete_gtfs_relationships_fail_closed(tmp_path, broken):
    archive = tmp_path / "fixture.zip"
    write_fixture(archive, **{broken: True})
    with pytest.raises(ValueError, match="not served|missing shape"):
        discover(archive, {"datasetVersion": "fixture-only"})


def test_source_or_config_tampering_is_rejected(tmp_path):
    archive = tmp_path / "fixture.zip"
    write_fixture(archive)
    with pytest.raises(ValueError, match="SHA-256"):
        discover(archive, {"datasetVersion": "fixture-only", "tramArchiveSha256": "incorrect"})
    site, _, _ = discover(archive, {"datasetVersion": "fixture-only"})
    site["gtfsStopIds"].append("116")
    with pytest.raises(ValueError, match="gtfsStopIds"):
        validate_config(archive, site)


def test_committed_geojson_and_trip_index_match_verified_configuration():
    site = json.loads((ROOT / "config/site.json").read_text(encoding="utf-8"))
    geometry = json.loads((ROOT / "config/route-58.geojson").read_text(encoding="utf-8"))
    index = json.loads((ROOT / "config/gtfs-trip-index.json").read_text(encoding="utf-8"))
    assert site["passengerStopNumber"] not in site["gtfsStopIds"]
    assert len(index) == site["routeTripCount"]
    assert {record["routeId"] for record in index.values()} == set(site["gtfsRouteIds"])
    assert {record["shapeId"] for record in index.values()} == set(site["gtfsShapeIds"])
    full = {f["properties"]["shapeId"]: f for f in geometry["features"] if f["properties"]["kind"] == "route"}
    assert set(full) == set(site["displayGtfsShapeIds"])
    for feature in geometry["features"]:
        properties = feature["properties"]
        if properties["kind"] == "local_segment":
            source_vertices = full[properties["shapeId"]]["geometry"]["coordinates"]
            assert all(point in source_vertices for point in feature["geometry"]["coordinates"])
        if properties["kind"] == "stop":
            stop = next(s for s in site["stops"] if s["stopId"] == properties["stopId"])
            assert feature["geometry"]["coordinates"] == [stop["longitude"], stop["latitude"]]


def test_every_configured_stop_is_served_in_downloaded_official_dataset():
    """AC-02: independently join the saved official source, not a mocked index."""
    site = json.loads((ROOT / "config/site.json").read_text(encoding="utf-8"))
    path = ROOT / "data" / f"gtfs-tram-{site['gtfsDatasetVersion']}.zip"
    if not path.exists():
        pytest.skip("Official source ZIP is intentionally untracked; run GTFS discovery to enable this re-import test")
    with zipfile.ZipFile(path) as archive:
        def source_rows(name):
            return csv.DictReader(io.TextIOWrapper(archive.open(name), encoding="utf-8-sig"))
        trips = {row["trip_id"]: row for row in source_rows("trips.txt") if row["route_id"] in site["gtfsRouteIds"]}
        served = set()
        directions = set()
        for record in source_rows("stop_times.txt"):
            if record["stop_id"] in site["gtfsStopIds"] and record["trip_id"] in trips:
                served.add(record["stop_id"])
                directions.add((record["stop_id"], trips[record["trip_id"]]["direction_id"]))
        source_shapes = {shape: [] for shape in site["displayGtfsShapeIds"]}
        for record in source_rows("shapes.txt"):
            if record["shape_id"] in source_shapes:
                source_shapes[record["shape_id"]].append(record)
    assert served == set(site["gtfsStopIds"])
    assert directions == {(s["stopId"], d["directionId"]) for s in site["stops"] for d in s["directions"]}
    geometry = json.loads((ROOT / "config/route-58.geojson").read_text(encoding="utf-8"))
    for feature in geometry["features"]:
        if feature["properties"]["kind"] == "route":
            records = sorted(source_shapes[feature["properties"]["shapeId"]], key=lambda r: int(r["shape_pt_sequence"]))
            assert feature["geometry"]["coordinates"] == [[float(r["shape_pt_lon"]), float(r["shape_pt_lat"])] for r in records]
    validate_config(path, copy.deepcopy(site))
