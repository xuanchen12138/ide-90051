# Validation and limitations

Validation uses the criteria in `AGENT_IMPLEMENTATION_GUIDE.md`. The targets in `config/evaluation.json` were written before the browser latency and recovery experiments. Backend/unit, controlled fixture and actual live API evidence are reported separately.

## Current evidence

The 2026-09-22 Melbourne map revision uses a cached OpenStreetMap extract for local streets, building footprints, bridges, the Yarra River, parks and landmarks. The final application build is `source-50345ffb1291e369`.

| Current map revision check | Result / evidence |
| --- | --- |
| Geographic source | 17,869 source features; reproducible cached export, source hashes and ODbL provenance in `config/basemap-provenance.json`. Counts include segments and building parts, not distinct physical structures |
| Backend/unit/adapter/API tests | 138 passed, including 14 geographic-data tests and the local GeoJSON endpoint check; two third-party deprecation warnings |
| Frontend presentation tests / production build | 5 passed; TypeScript and Vite build passed |
| Browser acceptance | All 9 distinct cases passed across the complete 8-case suite and the added missing-basemap case; map/mobile cases rerun after final label spacing changes |
| Map-specific regression | Actual water/building/road/bridge geometry, named Yarra and landmarks, pan/zoom/reset, zoom-out retention, external map requests blocked, and explicit fallback on a missing local snapshot all passed |
| Visual review | Inspected desktop, detailed street zoom, full-route overview and 390×844 mobile screenshots. Final previews and feature/label inventory are in `artifacts/map-review/` |
| Detailed-map performance | 64 actual browser samples: P95 188 ms observed-to-render and received-to-render; 59.3 Hz headless frame cadence; zero browser errors; all predeclared targets passed |

The new performance evidence is `artifacts/browser-evaluation-2026-09-21T18-08-30-170Z/`, containing `results.json`, correlated render samples, events and severity/mobile screenshots. Measurements use the real local API/SSE/React pipeline. They do not establish physical-sensor or production-network latency. Full-route street detail remains limited to the declared central Melbourne extract.

## Previous baseline evidence

The following results describe the preceding GTFS-only map build, retained as historical evidence. Use the current revision results above for map appearance and rendering performance.

| Check | Result / evidence |
| --- | --- |
| Official static dataset | 2026-09-18 release; both stop records joined to Route 58 through stop_times/trips; displayed vertices match source shapes |
| Reproducible download | Official range download re-run successfully; nested ZIP hash, GeoJSON and trip index reproduced |
| Backend/unit/adapter/API tests | 123 passed; two third-party deprecation warnings; no test failures |
| Frontend presentation tests | 5 passed |
| TypeScript and production Vite build | Passed |
| Live transport access | All three tram endpoints returned HTTP 200 through the backend-only KeyID adapter |
| Live feed content | Vehicle feed was stale; trip updates fresh and empty; fresh alerts include agency-wide information when relevant. A lack of Route 58 vehicles is not suspension evidence |
| Browser acceptance | 7/7 passed in 49.6 seconds; map/mobile cases rerun after the final contrast/legend refinement |
| Browser latency and visual artefacts | Final evaluation: 63 actual browser samples, P95 95 ms observed-to-render and received-to-render, 60.0 Hz frame cadence, zero browser errors; source build `source-cfdec22b6f5dcc24` |
| Transport recovery experiment | Passed in 60.007 seconds against predeclared ≤70-second target; real elapsed polling interval with injected HTTP 503, not a real upstream outage |
| Google Maps live rendering | Not run: separate restricted browser Maps key is absent |
| Human provenance comprehension | Not run: no reviewer answers fabricated |
| Physical sensor/end-to-end hardware | Not run: device is unavailable |

The final browser run is `artifacts/browser-evaluation-2026-09-21T17-44-13-134Z/`: `results.json`, `events.json`, `browser-render-samples.json`, five hazard screenshots, a full-route critical screenshot, synthetic-alert screenshot and mobile collapsed/expanded screenshots. Finite colour transitions are completed for static screenshots; the separate animation cadence measurement runs with normal motion enabled. Both final map/mobile regression cases passed after the visual refinements. Known-backend-secret scanning passed over source/build/evidence text files with its documented exclusions.

Backend tests cover threshold and recovery boundaries, dwell/hysteresis, timestamp/quality validation, strict JSON types, duplicates/conflicts, out-of-order ingestion, all named scenarios, physical/mock isolation, official alert filtering, protobuf errors, cached partial failures, retries, authentication, same-origin writes, persistence and telemetry attribution.

The first browser run failed at a **test timeout**, not a state mismatch: it allowed 15 seconds for three sequential five-second recovery dwells plus scheduler ticks. The observed sequence was Critical → Warning → Watch; Normal followed after the original assertion limit. The test allowance was corrected to 25 seconds based on the already documented dwell requirements. The engine was not sped up and the predeclared latency targets were not changed. The original failure screenshot, trace and report are retained in `artifacts/e2e-first-run`.

A second run passed six checks but found an ambiguous test selector: the required simulation phrase appears both in its badge and in the explanatory paragraph. The test now selects the exact badge text. That run's evidence remains in `artifacts/e2e-second-run`.

## Acceptance mapping

| Guide criteria | Evidence boundary |
| --- | --- |
| AC-01 geographic scope | Verified Stop 116 focus and Route 58 GeoJSON; cached OSM local context, source geometry, labels, pan/zoom/reset and mobile view checked in the current revision. Google basemap remains credential-dependent |
| AC-02 identity | Static source re-import test and discovery provenance |
| AC-03–06 hazard colours | Pure-engine tests plus browser transitions/full-route overlay assertions |
| AC-07 service alerts | Protobuf/domain tests plus explicitly synthetic UI alert; real feed retrieval also verified separately |
| AC-08–09 degradation | Fault/stale/outage fixtures, per-feed cache tests, SSE-disconnection browser check |
| AC-10 recovery | Strict recovery boundary/dwell tests and browser critical-to-normal transition |
| AC-11 accessibility | Text/non-colour symbols, keyboard map/controls, mobile persistent summary and reduced-motion browser checks. Not a full assistive-technology audit |
| AC-12 credential boundary | Backend-only configuration and KeyID adapter; known-secret source/build scan. Scope exclusions reported by the script |

## Experiment method

`node scripts/evaluate_browser.mjs` resets the current run, records at least 24 distinct one-second mock observations through the real HTTP/SSE/React path, captures a fixed camera for each severity, drives controlled recovery and records animation frame cadence and browser errors. It captures this evaluation browser's telemetry requests and correlates them with the server's reading-evaluated events, so another open browser cannot substitute its render timing. Run the main browser tests and this evaluation **sequentially** because scenario controls act on the same shared local runtime. Failures are saved alongside successful results.

The first latency harness tried to render every rapid manual POST individually and timed out when a periodic reading superseded one before the next frame. This is consistent with the documented latest-snapshot SSE queue. The measurement was corrected to sample the configured one-second mock stream. Its failed report remains under `artifacts/browser-evaluation-2026-09-21T17-36-35-376Z`; no performance target was changed.

Telemetry timestamps use two `requestAnimationFrame` callbacks as an approximate post-paint sample. They are browser-reported wall-clock times on this machine, not compositor instrumentation or evidence of synchronized physical-device clocks. Headless animation frame rate is a responsiveness check on this machine, not a GPU/device benchmark. Dwells are intentional state delays and are distinct from reading-to-screen display latency.

`python scripts/evaluate_transport_recovery.py` uses the real transport adapter/cache, swaps only its HTTP transport for a deterministic fixture, injects one endpoint's 503 response, then waits the configured polling interval before successful recovery. This establishes scheduling/cache behavior; it does not establish external Transport Victoria availability.

Each application run records its source/build identifier, configuration hash, dataset version and observed/received/evaluated times. Browser telemetry adds rendered time. SQLite keeps historical runs and failures; Export events downloads the current run. Raw transport credentials are never written to result records.

## Remaining limitations

- No calibrated physical sensor, site survey, operator-approved thresholds, flood prediction, hydraulic model or automatic service control.
- Google integration is implemented and type-checked but requires a valid Maps key and separate live visual check. The keyless renderer's cached OpenStreetMap street/building/bridge/water/park context has passed the geographic, browser and visual checks recorded above.
- The cached OpenStreetMap extract covers the selected local Southbank area, not every segment of Route 58 or all Melbourne. It is community-maintained static geography, not a survey, current construction/closure record or flood observation. Preserve OpenStreetMap contributor attribution and ODbL licensing when sharing its derived data.
- Informational or partial official feed content does not prove the absence of disruption. Fresh empty service alerts mean no relevant disruption reported.
- Realtime trip IDs are matched exactly to the checked-in current schedule. Refresh the static dataset as it rolls forward; unknown IDs are not guessed.
- SQLite is single-process local persistence. No multi-worker coordination, production authentication system, high availability or retention automation is claimed.
- No cloud deployment, 3D, multi-site expansion, suggested diversion, Fission or Kubernetes was undertaken.
- A complete guide definition-of-done claim is withheld while live Google rendering and human reviewer validation remain unperformed.
