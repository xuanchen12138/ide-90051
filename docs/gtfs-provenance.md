# Route 58 / Stop 116 discovery evidence

The application uses the official [Victorian GTFS Schedule dataset](https://opendata.transport.vic.gov.au/dataset/gtfs-schedule), published by the Department of Transport and Planning. The portal reported **18 September 2026** as its latest dataset date when checked on **22 September 2026 in Melbourne**. The ZIP was retrieved at `2026-09-21T17:09:58.667896+00:00` (22 September, 03:09 AEST).

Only the metropolitan tram member, `3/google_transit.zip`, was downloaded from the 292,748,591-byte outer ZIP using HTTP byte ranges. The nested archive is 15,486,075 bytes; the ZIP reader verified the member CRC. Its SHA-256 is:

```text
2f6676c61c14292f3d1f0fddfbeedce5ce966e163256e2449b2b0eeea7cff666
```

This is the hash of the **nested tram ZIP**, not the full Victorian ZIP. `config/site.json` also records the exact source URL, HTTP last-modified date, retrieval timestamp and SHA-256 of the five identity/geometry source tables plus `agency.txt`. No credential is needed for this public static data.

## Verified identity

`routes.txt` identifies the tram route as `aus:vic:vic-03-58:` with `route_short_name=58`, `route_long_name=West Coburg - Toorak`, and `route_type=0`.

The route's `agency_id` column is blank. `agency.txt` contains exactly one agency record, `agency_id=1`, `agency_name=Transport Victoria`. Under the [GTFS single-agency rule](https://gtfs.org/documentation/schedule/reference/#routestxt), the route's agency field is optional in this situation. The generated `gtfsAgencyIds=["1"]` therefore comes from that sole source record, with this resolution method recorded explicitly; it is not inferred from an operator name.

| GTFS stop ID | Source stop name | Latitude | Longitude | Joined GTFS direction | Scheduled headsigns |
| --- | --- | ---: | ---: | --- | --- |
| `18233` | City Rd/Kings Way #116 | -37.82620633 | 144.96058968 | `0` | West Coburg; La Trobe Street - Stop 7; Royal Childrens Hospital - Stop 19 |
| `22612` | City Rd/Kings Way #116 | -37.82630014 | 144.96080296 | `1` | Toorak |

The passenger stop number `116` and the stop-page number `3116` are **not** the GTFS stop IDs. The official tram source contains two matching boarding-location records, with no parent-station/platform-code distinction. Direction and destination information above comes from the `stop_times.txt → trips.txt` join, not a guess based on coordinate position or direction number.

There are 2,652 Route 58 trips in this export. The source links 1,234 of them to stop `18233` and 1,263 to stop `22612`. These are trip records across the exported service calendars, **not daily service counts**. Short turns account for some Route 58 trips not passing the selected stop. A concrete trip/stop-sequence/shape example for each boarding location is saved in `site.json`.

## Geometry and display selection

All 42 Route 58 shape IDs remain in the site evidence and trip lookup. To avoid drawing overlapping duplicate patterns, the map displays the most frequently scheduled shape serving the site for each direction:

| Direction | Display shape | Vertex count | Source distance at final point |
| --- | --- | ---: | ---: |
| `0` | `3-58-vpt-5.2.H` | 415 | 17,772.76 m |
| `1` | `3-58-vpt-5.3.R` | 403 | 17,779.11 m |

Both selected shapes are full-length Toorak–West Coburg paths in this release. The representative paths are static route context; they do not promise that every realtime trip follows the same pattern. All coordinates in `route-58.geojson` come directly from `shapes.txt`, ordered by `shape_pt_sequence`, as GeoJSON `[longitude, latitude]` in WGS84. No street geometry was hand-drawn.

The local segment retains the source vertices approximately 600 m in each direction along each representative shape from its vertex nearest the resolved stop midpoint. The last retained vertex may extend beyond 600 m because no invented endpoint is interpolated. `localSegmentHalfLengthMeters` controls this display window. The default focus bounds are a configured camera window around the verified stop midpoint.

`conceptualFlood` is deliberately separate from GTFS geometry: it is an illustrative ellipse centred on the verified stop midpoint, with 180 m east/west and 120 m north/south radii. It is a configurable demonstration mask, **not an observed flood extent, surveyed asset boundary, or hydraulic prediction**. Its visible size is scaled by the frontend's simulated scenario level.

## Refresh and reproduce

From the project root, using Python 3.11 or later:

```powershell
# Downloads only the current official tram member and regenerates all three configs.
python -m adapters.gtfs_static --download

# Rebuild from the exact source downloaded for this implementation.
python -m adapters.gtfs_static --input data/gtfs-tram-2026-09-18.zip

# Verify existing configured IDs, directions, geometry references and source hashes.
python -m adapters.gtfs_static --input data/gtfs-tram-2026-09-18.zip --validate

# Tests run without a network call. The source re-import check runs if its ZIP exists.
python -m pytest tests/test_gtfs_static.py -q
```

The official portal resource is discovered via its public CKAN metadata API. Downloads and their metadata stay in ignored `data/`. The CLI uses only Python's standard library. If HTTP ranges are unavailable, download the public outer ZIP manually, extract its `3/google_transit.zip` member into `data/`, and supply `--input` with the corresponding metadata JSON. The stored SHA-256 must match the extracted member.

Treat a refresh as a reviewed data update: inspect stop matches, direction/headsign evidence, shape endpoints and configured focus after regenerating. `--validate` does not modify the versioned configuration. An absent matching stop, an unserved platform, a missing shape, or a source fingerprint mismatch fails explicitly.

## Currency, licence and limitations

The tram archive has no `feed_info.txt`. Its publication date therefore comes from the portal resource's `last_modified`, not an invented GTFS feed version. The minimum and maximum Route 58 `calendar.txt` dates are retained as `serviceCalendarRange`; individual services and calendar exceptions determine operation within that envelope. This envelope is not a guarantee that every route pattern operates on every date.

The publisher describes weekly/as-needed updates, rolling schedule coverage and possible path inaccuracies. Recheck the portal before an assessed or operational run; do not treat a committed September export as perpetually current. The realtime adapter uses exact Route 58 route IDs when supplied and this versioned trip lookup when only a trip ID is available. Unknown trip IDs after a schedule change cannot be guessed and may require refreshing the static export.

The source is licensed under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution: **Department of Transport and Planning, Victoria — GTFS Schedule**. This prototype redistributes a Route 58 subset, reformatted as JSON/GeoJSON with a documented display selection and local clipping. The conceptual flood mask is a prototype illustration, separate from the published data. Source identity verification establishes which location is drawn; it does not establish sensor siting suitability, flood risk or service safety.
