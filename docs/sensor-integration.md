# USB float sensor integration

The supplied Arduino sketch reads two float switches on D2/D3 with INPUT_PULLUP, treats HIGH as raised/wet, debounces for 100 ms, and drives LEDs on D7/D8. The project preserves that circuit and polarity. Verify the actual switch orientation against the hardware before demonstrating water levels.

The collector reads the USB serial device at 9600 baud and posts physical observations to the local API. Rainfall is **not measured** by these two switches; physical readings therefore carry null rainfall and null millimetre depth. Water and tram data sources remain independent.

## Windows demo startup

The connected board was identified on 6 October 2026 as an Arduino Uno on **COM8**, USB VID `2341`, PID `0043`. Windows can assign a different COM port after reconnecting, so list ports again if COM8 is unavailable.

Close Arduino Serial Monitor / Serial Plotter before starting the service. Only one program can own the device port. Start both the API and USB collector in one PowerShell terminal:

```powershell
cd "C:\Project\ide-90051"
.\.venv\Scripts\python.exe run.py --sensor-port COM8
```

Open http://127.0.0.1:8000. This command selects physical sensor mode, starts the API, waits for it to become available, and then starts the collector. Keep the terminal open; **Ctrl+C stops both processes**. The launcher never flashes firmware. For a different web port, use `run.py --sensor-port COM8 --port 8001`, then open http://127.0.0.1:8001.

To run the platform without opening the USB device, use `run.py` and choose the desired operating mode in the browser.

### Separate collector and serial diagnosis

List ports without opening them:

```powershell
cd "C:\Project\ide-90051"
.\.venv\Scripts\python.exe scripts\collect_sensor.py --list-ports
```

If the API is already running separately, start only the collector (replace COM8 and the API port as needed):

```powershell
.\.venv\Scripts\python.exe scripts\collect_sensor.py --port COM8 --api-url http://127.0.0.1:8000
```

Select physical sensor mode in the browser when using this separate command. The collector itself does not switch modes, and physical ingestion does not overwrite the simulation source. Do not start this second collector while the combined launcher already owns the port.

For read-only serial diagnosis, stop the collector / combined launcher first, then run:

```powershell
.\.venv\Scripts\python.exe scripts\collect_sensor.py --port COM8 --dry-run --duration 15
```

This prints normalized observations from the real board without submitting HTTP readings. If pyserial is missing, install the project's requirements using `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

## Original sketch and heartbeat firmware

The original sketch emits only `Flood level changed to: LEVEL 0`, `LEVEL 1`, `LEVEL 2`, or `INVALID SENSOR STATE`, plus diagnostic text. These exact event lines are supported. Each new line is one physical observation. Keeping a float steady emits no further observations, so the server will correctly mark the measurement stale after its configured freshness timeout. This is an original-firmware limitation, not a reason to replay the last value with a new timestamp.

The heartbeat firmware in `firmware/flood_level_sensor/flood_level_sensor.ino` was compiled for Arduino Uno and uploaded to the identified COM8 board on 6 October 2026; the upload verification succeeded. Before this one-time upload, the existing flash was backed up to `artifacts/firmware-original-20261006.hex`, and the supplied original sketch was retained at `firmware/original/flood_level_original.ino`. Keep these files if restoring the original demonstration is needed.

This replacement retains the two pins, active-HIGH interpretation, 100 ms debounce, and LED behaviour. It emits the initial state (including an invalid combination), every debounced state change, and a heartbeat every second. Normal service startup does not compile or flash the board. For a future firmware change, stop the collector, open the sketch in Arduino IDE, and explicitly select and upload to the correct board/port.

The wire format is one JSON object followed by newline:

```json
{"type":"flood_reading","protocolVersion":1,"sequence":0,"uptimeMs":100,"lowerFloat":false,"upperFloat":false,"floodLevel":0}
```

| Lower | Upper | Board level | Demo scenario level | Expected hazard after configured dwell |
|---|---|---:|---:|---|
| Down / LOW | Down / LOW | 0 | 0 | NORMAL |
| Raised / HIGH | Down / LOW | 1 | 60 | WARNING |
| Raised / HIGH | Raised / HIGH | 2 | 90 | CRITICAL |
| Down / LOW | Raised / HIGH | -1 | 0 with quality=fault | UNKNOWN |

These scenario levels demonstrate threshold crossings. They are **not calibrated water depths** or official flood thresholds. Two switches provide three valid bands; they cannot independently distinguish all four normal/watch/warning/critical bands. The selected mapping deliberately exercises warning and critical; WATCH remains available in simulation. Risk rise/recovery dwell and hysteresis still apply in the backend.

## Freshness, reconnect and retries

- USB bytes are assembled across partial reads; overlong lines are discarded until newline. Diagnostics and malformed/inconsistent JSON never become measurements.
- Each frame is timestamped in UTC at laptop receipt. `uptimeMs` is recorded as device uptime, not converted into a fictitious wall-clock time.
- The serial reader runs independently of HTTP. A one-item queue keeps the newest observation, rather than draining an outage backlog and claiming it is current. HTTP retries retain the original `readingId` and `observedAt`. Unsent observations older than five seconds are discarded.
- JSON sequence duplicates and out-of-order frames do not refresh liveness. UInt32 sequence/millis wrap is supported. A reset of both counters near device boot starts a new identity epoch. Protocol v1 has no hardware boot nonce; a replay of old near-boot bytes cannot be perfectly distinguished from a real reboot. This is a directly connected trusted-device demo protocol.
- Opening the serial port can reset some Arduino boards through DTR. Reconnecting discards the prior input buffer and resumes complete frames. Unplugging the board, serial contention, or silent firmware never triggers mock water readings. The server becomes stale/UNKNOWN according to its freshness rule.
- The token is read from `SENSOR_INGEST_TOKEN` in the root `.env` / environment and sent only to loopback HTTP or an explicitly configured HTTPS URL. Redirects are not followed, and token values / HTTP response bodies are never logged.

## Validation

`python -m pytest tests/test_serial_sensor.py` covers the protocol, legacy events, faulty switch combinations, malformed/partial/overlong input, counter wrap/reset, duplicate liveness, safe API URLs, stable HTTP retries, bounded queues, and disconnect/silence behaviour using fake serial data. These tests do not prove electrical polarity, USB-driver reliability, or physical water-depth calibration.

Hardware checks on 6 October 2026 identified the Uno on COM8, compiled and verified the new firmware upload, and received actual serial levels **0, 1, and 2**. This evidence establishes device communication and those level messages. It does not establish calibrated switch heights, polarity under installed water conditions, an upper-only fault test, or a physical unplug/reconnect acceptance test. The actual USB-to-HTTP check is recorded in `artifacts/hardware-integration-20261006/result.json`: **16 distinct level-0 physical readings** reached the API and remained fresh during sampling. Each retained null rainfall, with no simulated weather leaking into physical mode. After the collector was stopped while USB remained attached, the last reading aged to **30.142862 seconds** and the API reported `stale` / `UNKNOWN` without fabricating a new reading. This is a collector-stop liveness test, not a physical USB-unplug test.

The same API experiment verified simulated rain at **85 mm/h**, **2 moving mock trams** and **2 mock arrival predictions**, followed by an automatic-source snapshot with fresh `transport-victoria` data and `fallback=false`. It establishes backend data behaviour, not current browser rendering.

The combined launcher was exercised against the real COM8 board; `artifacts/hardware-launcher-result.json` records **5 actual readings**, automatic selection of physical mode, rejection of an occupied API port, and release of both the test API port 8002 and COM8 after interruption. Port 8000 remains the default for normal use.

Current UI integration/build is paused at the user's request while the separate UI redesign is retained. The added observation panels are not yet wired into that redesigned interface, so these API and launcher results must not be presented as a completed browser integration test.

A hardware acceptance run should verify both floats down, lower raised, both raised, upper-only fault, holding each state beyond the freshness timeout, and unplugging/reconnecting USB. With revised firmware the held states remain fresh; unplugging becomes stale. Do not use serial monitor and collector simultaneously.

Primary references: [pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html), [Arduino Serial.begin](https://docs.arduino.cc/language-reference/en/functions/communication/serial/begin/), [Arduino millis](https://docs.arduino.cc/language-reference/en/functions/time/millis/).
