"""USB serial -> local API bridge. Run from any directory with Python 3.11+."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adapters.serial_sensor import FrameError, LineDecoder, ReadingTracker, ingestion_url, parse_frame, post_reading


def read_serial(port: str, baud: int, site_id: str, sensor_id: str,
                observations: queue.Queue, stop: threading.Event, dry_run: bool = False) -> None:
    import serial
    tracker = ReadingTracker(site_id, sensor_id)
    legacy_warned = False
    while not stop.is_set():
        try:
            with serial.Serial(port, baudrate=baud, timeout=0.25, write_timeout=1) as device:
                # Opening some Arduino boards resets them via DTR. Discard pre-open
                # buffered bytes; then accept only complete newly received lines.
                device.reset_input_buffer()
                decoder = LineDecoder()
                print(f"Connected to {port} at {baud} baud. Waiting for device frames.", flush=True)
                while not stop.is_set():
                    chunk = device.read(min(max(device.in_waiting, 1), 512))
                    if not chunk:
                        continue  # Silence is not a reading/heartbeat.
                    for line in decoder.feed(chunk):
                        try:
                            frame = parse_frame(line)
                        except FrameError:
                            print("Ignored malformed sensor frame.", file=sys.stderr, flush=True)
                            continue
                        if frame is None:
                            continue
                        if frame.legacy and not legacy_warned:
                            print("Legacy sketch: state changes only; unchanged levels become stale. Upload heartbeat firmware for continuous monitoring.", file=sys.stderr, flush=True)
                            legacy_warned = True
                        observation = tracker.observation(frame, datetime.now(timezone.utc))
                        if observation is None:
                            continue
                        if dry_run:
                            print(json.dumps(observation), flush=True)
                            continue
                        item = (time.monotonic(), observation)
                        try:
                            observations.put_nowait(item)
                        except queue.Full:
                            try:
                                observations.get_nowait()
                            except queue.Empty:
                                pass
                            observations.put_nowait(item)
        except (serial.SerialException, OSError):
            # Never reuse the last state to cover an unplug or port contention.
            print(f"Serial connection unavailable on {port}; retrying in 2 seconds. No readings fabricated.", file=sys.stderr, flush=True)
            stop.wait(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-ports", action="store_true", help="List USB/serial ports and exit")
    parser.add_argument("--port", help="Explicit device port, for example COM3")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--sensor-id", default="southbank-float-usb")
    parser.add_argument("--site-id")
    parser.add_argument("--dry-run", action="store_true", help="Read actual device frames without HTTP ingestion")
    parser.add_argument("--duration", type=float, default=0, help="Optional stop after N seconds (0 runs until Ctrl+C)")
    parser.add_argument("--max-age", type=float, default=5, help="Discard unsent observations older than N seconds")
    args = parser.parse_args()
    try:
        from serial.tools import list_ports
    except ImportError:
        parser.error("pyserial is missing; run python -m pip install -r requirements.txt")
    if args.list_ports:
        ports = list(list_ports.comports())
        for port in ports:
            print(f"{port.device}: {port.description}")
        if not ports:
            print("No serial ports detected.")
        return 0
    if not args.port:
        parser.error("--port is required; first use --list-ports to identify the board")
    if args.duration < 0 or not 0 < args.max_age <= 10 or args.baud <= 0:
        parser.error("duration must be nonnegative, max-age must be in (0, 10], and baud must be positive")
    try:
        endpoint = ingestion_url(args.api_url)
    except ValueError as error:
        parser.error(str(error))
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    token = os.getenv("SENSOR_INGEST_TOKEN", "")
    site_id = args.site_id or json.loads((ROOT / "config/site.json").read_text(encoding="utf-8"))["siteId"]
    observations: queue.Queue = queue.Queue(maxsize=1)
    stop = threading.Event()
    worker = threading.Thread(target=read_serial, args=(args.port, args.baud, site_id, args.sensor_id, observations, stop, args.dry_run), daemon=True)
    worker.start()
    deadline = time.monotonic() + args.duration if args.duration else float("inf")
    current = None
    exit_code = 0
    import httpx
    try:
        with httpx.Client(timeout=2, trust_env=False, follow_redirects=False) as client:
            while time.monotonic() < deadline:
                if not worker.is_alive():
                    print("Serial reader stopped unexpectedly.", file=sys.stderr)
                    return 1
                try:
                    current = observations.get(timeout=0.25 if current is None else 0)
                except queue.Empty:
                    pass
                if current is None:
                    continue
                received_monotonic, payload = current
                if time.monotonic() - received_monotonic > args.max_age:
                    current = None
                    continue
                result = post_reading(client, endpoint, payload, token)
                if result == "accepted":
                    print(f"Ingested physical level {payload['floatLevel']} ({payload['quality']}).", flush=True)
                    current = None
                elif result == "unauthorized":
                    print("Sensor ingestion unauthorized. Configure SENSOR_INGEST_TOKEN in the project .env to match the server.", file=sys.stderr)
                    exit_code = 1
                    break
                elif result == "rejected":
                    print("Sensor frame rejected by API. Check server schema/site configuration.", file=sys.stderr)
                    current = None
                    stop.wait(1)
                else:
                    print("API temporarily unavailable; retaining the same timestamp and ID for bounded retry.", file=sys.stderr)
                    stop.wait(1)
    except KeyboardInterrupt:
        print("Sensor collector stopped.")
    finally:
        stop.set()
        worker.join(timeout=3)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
