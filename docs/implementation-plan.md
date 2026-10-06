# Implementation plan and baseline

## Baseline (22 September 2026)

The repository contains coursework artefacts and `gtfs_tram_test/test_tram_api.py` only. There is no existing web application, API, database or automated application test suite. Preserve the coursework and standalone tester. The tester supplies the official tram endpoint pattern, protobuf decoding and backend `KeyID` header precedent; the application will use an independently testable adapter with caching and route filtering.

No files were tracked at baseline. No backend or Maps credential was present in the process environment or root `.env`. Do not recover old conversation credentials. The guide requires a rotated Transport Victoria subscription key. Missing keys must be a visible, supported state; live authentication and Google basemap validation remain pending until replacement keys are configured.

## Guide-to-file mapping and sequence

| Guide | Implementation | Validation |
| --- | --- | --- |
| §5 static identity | `adapters/gtfs_static.py`, `config/site.json`, `config/route-58.geojson`, `config/gtfs-trip-index.json` | Current official archive; stop → stop time → trip → route → shape joins; provenance report |
| §5 realtime observations | `adapters/gtfs_realtime.py` | Protobuf fixtures, feed-specific age/failures, protected backend requests |
| §5 sensors | `domain/models.py`, `adapters/mock_sensor.py`, `adapters/physical_sensor.py`, `contracts/sensor-reading.schema.json` | Shared ingestion validation, duplicate handling, deterministic scenarios |
| §6 state | `domain/state_engine.py`, `config/demo-thresholds.json` | Boundaries, dwell, hysteresis, freshness, hazard/service independence |
| §7–8 experience | `web/src/` React/TypeScript components and styles | Map overlays, all states, mobile sheet, keyboard and reduced motion |
| §9 API/persistence | `api/main.py`, `api/runtime.py`, SQLite store | HTTP integration tests, SSE, cache persistence, scenario controls |
| §10 credentials | `.env.example`, `.gitignore`, backend settings, secret scan | No Transport key in client API or built assets |
| §11–15 integration/evaluation | `tests/`, `web/e2e/`, `scripts/`, `config/evaluation.json`, `docs/` | Automated acceptance suite, browser screenshots, reproducible results |

Resolve static identity before feature implementation. Then build the UI and domain/API in parallel against a documented JSON contract, integrate the realtime adapter, and run backend, build, frontend and browser acceptance checks. Record failed or unavailable checks honestly.

## Architecture decision

Use React + TypeScript + Vite, FastAPI/Python, SQLite and SSE. Serve a built UI and API from one process/origin for one-command local operation. Local persistence is single-process; this prototype is not a distributed service. Keep the state engine pure by passing its previous transition memory explicitly along with sensor, transport, configuration and time.

Use a monochrome Google Maps 2D map when a restricted browser key is supplied. Following the user's request for recognizable Melbourne geography, the keyless renderer now combines a cached local OpenStreetMap extract with the verified GTFS route/stop overlay. Roads, buildings, bridges, rivers and parks come from the geographic source; no street footprints are invented. The local cache is served through `/api/v1/site/basemap`, supports pan/zoom, and retains OpenStreetMap contributor / ODbL attribution. Its coverage is the selected Southbank area; a full-route overview outside that coverage remains GTFS geometry. Both renderers use the same verified transport geometry and backend risk states. Google live-rendering validation remains separate from cached-map acceptance checks.

Hazard and service state have independent provenance. Demonstration transport alert fixtures must carry `source: fixture` and never be presented as a real official alert. Normal-operation mode uses the physical ingestion boundary and cannot recycle mock readings as live. Sensor hardware is unavailable, so normal operation initially shows unknown hazard. The default impact is local; the full route is an explicit simulation option.

No 3D, diversion, additional sites, Kubernetes or Fission work is planned. Cloud deployment instructions may describe a single container with external secrets, persistent storage and authentication, without claiming an actual deployment.
