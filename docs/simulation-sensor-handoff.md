# Simulation and sensor UI integration handoff

2026-10-06: the user confirmed another agent is redesigning the frontend and explicitly required this task not to interfere. Frontend writes and builds are paused. The backend and USB pipeline are implemented and verified; current UI acceptance is pending. Preserve the redesign when resuming integration.

## Verified backend contract

- `POST /api/v1/settings` with `{"mode":"simulation","transportMode":"auto"}`: simulated water/rain, actual tram API preferred. `transportMode:"mock"` is an explicit simulation-only override. Switching to `mode:"normal"` resets transport to auto.
- `POST /api/v1/scenarios/rainfall` with `{"intensityMmPerHour":85}`: simulation-only 0–200 mm/h. Rain is independent of water-level scenario; a water slider change preserves rain, while scenario/mode/reset clears the rain override. Normal mode returns 409 for rain controls.
- Snapshot `weather`: intensity, source, observedAt, freshness. Missing actual rainfall remains null/unavailable; stale/unavailable data must not animate current rain.
- Snapshot `transport`: source, fallback, fallbackReason, mockFeeds, effective feeds and original `liveFeeds`. Vehicles and predictions carry individual source. Healthy real feeds, including empty real feeds, are retained; unavailable/stale feeds use explicitly labelled mock data. Mock service alerts cannot establish official NORMAL. Named outage/official-alert fixtures retain their explicit fixture semantics.
- Snapshot `sensor`: floatLevel, lowerFloat, upperFloat, sensorUptimeMs in addition to the existing common fields. Hardware levels 0/1/2 map to 0/60/90; invalid upper-only state is -1/fault and UNKNOWN. Do not label these unitless values as water depth. Two floats do not measure rainfall.
- `status.dataFreshness.sensor` governs current-reading presentation. Stale water/float state must not look live. A stopped collector reaches stale/UNKNOWN after the configured 30 seconds.

## Pending frontend merge

Existing `ObservationPanels.tsx`, `RainOverlay.tsx`, and `observations.css` contain the prepared components. Reconcile them with the redesign before use:

1. Restore the required presentation helpers (`currentRain`, `vehicleTitle`, `transportSourceLabel`) in the redesigned `presentation.ts`; preserve its new icons/formatting helpers.
2. Import observations CSS and mount FloatPanel, WeatherPanel and simulation-only RainControls in the new App layout. Add the simulation transport auto/mock control. Show live feed health separately from effective mock records.
3. Mount RainOverlay in MapView; preserve the new camera/intro/Google style work. Label individual vehicle sources in both SVG and Google paths, and ensure mock or mixed data cannot be labelled live.
4. Gate current values, trend and rain animation by freshness and respect reduced motion.
5. Run presentation tests, TypeScript/build and browser acceptance after the other agent finishes. These have not been run against the current redesign by this task.

## Current evidence

- Backend: 255 passed, 2 skips for unmigrated raw source data, one third-party deprecation warning.
- `artifacts/hardware-integration-20261006/result.json`: actual COM8 produced 16 unique level-0 API readings; rain and moving mock-tram HTTP checks passed; auto transport returned fresh Transport Victoria data; stopping collector produced stale/UNKNOWN at 30.142862 seconds. USB remained attached during this timeout test.
- `artifacts/hardware-launcher-result.json`: one-command startup produced five real readings, rejected an occupied port, and released API and serial ports after interruption.
- Firmware and collector details: [sensor-integration.md](sensor-integration.md).
