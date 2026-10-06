# Reproducible demonstration

1. Run `python run.py`; open the app at 1440×1000 or similar desktop resolution. Point out City Rd/Kings Way, Stop 116 and Route 58 against the cached OpenStreetMap roads, buildings, bridges, Yarra River and parks. Read the separate GTFS and OpenStreetMap attribution. The local basemap works without a Google key; it is a static geographic extract, not current road or flood observations. Zoom and pan, then use **Return to Stop 116** to restore the camera.
2. Identify the **simulated sensor** and the separate **Transport Victoria observations**. Read each feed's freshness and timestamp. An empty or old response is legitimate evidence, not something to hide.
3. Reset. Start **Water rising**. It moves through green → yellow → orange → red in about 40 seconds including dwell. Pause to discuss any state; heartbeats continue while the water value is paused.
4. At critical, enable **Full route demo**. Read the “Simulated impact — not an official service status” label. Official service classification does not change because the water slider changed. The cached street/building context covers the local Southbank area only; the rest of the route remains an official GTFS overview.
5. Start **Official alert fixture**. It is a synthetic NO_SERVICE announcement used to demonstrate independent service classification; it is not a real report from the operator.
6. Start **Stale sensor**, then **Sensor fault**. Hazard becomes UNKNOWN and the route grey/dashed; transport information remains separate.
7. Start **Transport feed unavailable**. Explain that it is a feed-outage fixture and verify that hazard remains independently available. Reset restores the actual cached transport feeds.
8. Start **Recovery**; watch critical → warning → watch → normal, including the five-second dwell and hysteresis between steps.
9. Select **Normal operation**. Without an ingested physical observation, hazard is UNKNOWN. The future collector uses the documented sensor endpoint; mock observations are not reused.
10. Return to simulation, export the run events, and show observed/received/evaluated/rendered timestamps. Record any errors and pending reviewer responses.

Keyboard users can tab through all controls. The cached local map supports arrow keys and +/- when focused, with a Return to Stop 116 button. On mobile, the condensed status remains visible while the rest of the status/controls sheet can collapse. Reduced-motion mode removes ripples and pulsing. Google Maps is optional and must be verified separately with a valid restricted browser key.

To collect human evaluation, show the screen to three reviewers independently and ask: “Is this flood warning simulated or observed? Is this transport alert a test fixture or an official current report? Which data is stale?” Record exact answers without prompting toward the correct answer. Do not invent a reviewer sample.
