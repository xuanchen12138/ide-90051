# Southbank detailed basemap

The application includes a local OpenStreetMap vector snapshot for Melbourne's Southbank and adjoining central-city streets. It works without a map API key or browser tile requests. The transport route, tram stops and simulated flood overlay retain their independent GTFS/sensor sources.

## Data and attribution

- Source: [OpenStreetMap](https://www.openstreetmap.org/#map=15/-37.824/144.961), obtained from the public [Overpass API](https://overpass-api.de/api/interpreter).
- Attribution: **© OpenStreetMap contributors**, linked to [copyright and licence information](https://www.openstreetmap.org/copyright).
- Database licence: [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Retain the attribution and this licence/provenance with redistributed derived map data.
- Query selection bounds: south **-37.839**, west **144.944**, north **-37.811**, east **144.978**. This is a local demonstration area, not city-wide coverage.
- Main source base timestamp: **2026-09-21T17:52:26Z**. The first import used one additional tiny river-centerline query to obtain the river's source names; its base timestamp is **2026-09-21T17:54:31Z**. Exact queries, retrieval times, raw hashes and the generated GeoJSON hash are in `config/basemap-provenance.json`.

The checked-in GeoJSON contains **17,869** features: **6,119 buildings**, **9,057 roads and paths**, **257 bridge segments/decks**, **746 railway/tramway segments**, **571 parks/green areas**, **28 water features** (24 surfaces and four river centerlines), and **1,091 source-backed landmark label points**. These are source elements, not distinct physical structures: a street, bridge or building complex can have several segments or overlapping levels. The approximately 6.6 MB GeoJSON is served locally. The renderer should cull features outside the viewport and limit labels at small scales.

Verified source examples include:

| Feature | OpenStreetMap source |
| --- | --- |
| Crown Melbourne footprint and name | [way 13306836](https://www.openstreetmap.org/way/13306836) |
| Melbourne Convention Centre | [way 406535470](https://www.openstreetmap.org/way/406535470) |
| Melbourne Exhibition Centre | [way 13306728](https://www.openstreetmap.org/way/13306728) |
| Flinders Street station label | [node 4936370201](https://www.openstreetmap.org/node/4936370201) |
| Southbank suburb label | [node 2090529953](https://www.openstreetmap.org/node/2090529953) |
| Yarra river surface | [relation 954522](https://www.openstreetmap.org/relation/954522) |
| Named Yarra River centerline | [way 291627171](https://www.openstreetmap.org/way/291627171) |

Bridge source names include **Kings Bridge**, **Queens Bridge**, **Spencer Street Bridge**, **Sandridge Bridge**, **Seafarers Bridge**, **Princes Bridge**, **Evan Walker Bridge** and **Webb Bridge**. Names are copied verbatim from OSM, including source spelling. The unnamed river surface remains unnamed in data; its visible river label comes from the separate named river centerline.

## Geometry and rendering contract

`config/southbank-basemap.geojson` is a GeoJSON `FeatureCollection`. Each feature has `kind` (`building`, `road`, `bridge`, `water`, `park`, `rail`, `landmark`), an `osmId` such as `way/13306836`, integer `layer`, boolean `bridge` and `tunnel`, plus source fields when present (`name`, `roadClass`, `railway`, `waterType`, `buildingType`, `height`, `levels`, `wikidata`). Landmark points additionally identify `landmarkType` and `labelPositionMethod`.

Building, water, park and bridge-deck footprints use `Polygon` or `MultiPolygon`. Paths, roads, railways and some bridge segments use `LineString`; river centerlines also use `LineString` and must not be rendered as filled water surfaces. Landmark labels use `Point`. Full source geometry is retained, so features intersecting the query bounds can extend beyond those bounds. Clip presentation to the coverage/view bounds; do not fit the camera to every vertex in the dataset.

Relation member ways are joined by their matching endpoints in either direction. Inner rings are assigned to the containing outer ring, and winding follows the GeoJSON right-hand rule. The current export preserves 24 features with holes and two multipolygons. Render polygons with holes (for SVG, use `fill-rule="evenodd"`). Missing/open/unsupported relation geometry is excluded with a reason in provenance instead of being closed with an invented line; the current export has **zero exclusions**.

Label points copy source nodes directly or are derived deterministically from their source geometry. Polygon label points use an interior scanline position in the largest polygon, avoiding courtyard holes. They are cartographic label anchors, not surveyed entrances. Map context is a community-maintained snapshot; it is not an operational road-closure or flood-extent source.

## Rebuild or refresh

Rebuild deterministically without network access from the ignored raw cache already present on the development machine:

```powershell
.\.venv\Scripts\python.exe scripts/build_basemap.py
.\.venv\Scripts\python.exe -m pytest tests/test_basemap.py -q
```

`data/basemap/southbank-overpass.json` and `snapshot.json` hold the original response and request provenance. The initial import also has `river-overpass.json` and `river-snapshot.json`; the builder automatically verifies and merges this named-river supplement. Source caches are ignored by Git. Geometry and provenance are checked in, so application startup and the normal tests do not need Overpass. The cache rebuild test skips explicitly when raw source files are absent.

To request a new bounded snapshot, select a new cache directory. This refuses to overwrite an existing snapshot and makes exactly one request; the current query includes river centerlines directly:

```powershell
.\.venv\Scripts\python.exe scripts/build_basemap.py --fetch --cache data/basemap-new
```

Review changed source timestamps, names, geometry counts and exclusions, run the basemap tests and visually check the map before accepting a refreshed export. App startup, pan, zoom and SSE updates never fetch OSM data or poll Overpass. The importer uses the project's existing `httpx` dependency and Python's standard library; it adds no runtime package or API key requirement.
