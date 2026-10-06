import asyncio
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from adapters.mock_sensor import MockSensorProvider, SCENARIO_IDS
from adapters.mock_transport import MockTransportProvider, apply_fallback
from adapters.physical_sensor import HttpSensorProvider
from api.store import Store
from domain.models import SensorReading, iso, utc_now
from domain.state_engine import TransitionState, evaluate_status


ROOT = Path(__file__).resolve().parents[1]


def source_build_id(root: Path = ROOT) -> str:
    """Hash an explicit source allowlist, never environment files or generated data."""
    digest = hashlib.sha256()
    for directory in ("api", "domain", "adapters", "web/src", "config"):
        for source in sorted((root / directory).rglob("*")):
            if source.is_file() and source.suffix in {".py", ".ts", ".tsx", ".css", ".json", ".geojson"} and "__pycache__" not in source.parts:
                digest.update(str(source.relative_to(root)).encode())
                digest.update(source.read_bytes())
    return "source-" + digest.hexdigest()[:16]


class UnavailableTransport:
    def snapshot(self, now=None):
        return {"routeShortName": "58", "source": "transport-victoria", "fetchedAt": None, "feedTimestamp": None,
                "vehicles": [], "tripUpdates": [], "alerts": [], "freshness": "unavailable",
                "feeds": {name: {"freshness": "unavailable", "error": "not_configured"} for name in ("vehiclePositions", "tripUpdates", "serviceAlerts")}}

    async def refresh(self):
        return self.snapshot()

    async def close(self):
        pass


class Runtime:
    def __init__(self, database_path: str, transport=None, site=None, config=None):
        self.site = site or json.loads((ROOT / "config/site.json").read_text(encoding="utf-8"))
        self.config = copy.deepcopy(config or json.loads((ROOT / "config/demo-thresholds.json").read_text(encoding="utf-8")))
        if os.getenv("TRANSPORT_POLL_SECONDS"):
            try:
                self.config["transportPollSeconds"] = float(os.environ["TRANSPORT_POLL_SECONDS"])
            except ValueError:
                raise ValueError("TRANSPORT_POLL_SECONDS must be a positive finite number") from None
        limits = [self.config.get("thresholds", {}).get(state) for state in ("WATCH", "WARNING", "CRITICAL")]
        if not all(isinstance(value, (int, float)) for value in limits) or not 0 < limits[0] < limits[1] < limits[2] <= 100:
            raise ValueError("Demonstration thresholds must increase strictly between 0 and 100")
        for key in ("hysteresis", "riseDwellSeconds", "recoveryDwellSeconds", "sensorStaleSeconds", "futureToleranceSeconds"):
            value = self.config.get(key, 0)
            if not isinstance(value, (int, float)) or not 0 <= value < float("inf"):
                raise ValueError(f"Invalid nonnegative demonstration setting: {key}")
        if self.config.get("hysteresis", 3) >= min(limits[0], limits[1] - limits[0], limits[2] - limits[1]):
            raise ValueError("Hysteresis must be smaller than every threshold gap")
        for key, default in (("sensorIntervalSeconds", 1), ("transportPollSeconds", 60)):
            value = self.config.get(key, default)
            if not isinstance(value, (int, float)) or not 0 < value < float("inf"):
                raise ValueError(f"Polling interval must be positive and finite: {key}")
        provider = os.getenv("SENSOR_PROVIDER", "mock").lower()
        if provider not in {"mock", "physical", "http"}:
            raise ValueError("SENSOR_PROVIDER must be mock, physical or http")
        self.build_id = os.getenv("BUILD_ID") or source_build_id()
        self.store = Store(database_path)
        self.transport = transport or UnavailableTransport()
        self.cached_transport = self.store.cache("transport")
        if self.cached_transport and hasattr(self.transport, "restore"):
            self.transport.restore(self.cached_transport)
            self.cached_transport = None
        self.real_transport = self.transport.snapshot(utc_now())
        self.transport_refresh_failed = False
        self.mock = MockSensorProvider()
        self.mock_transport = MockTransportProvider(self.site)
        self.transport_mode = "auto"
        self.manual_rainfall = None
        self.physical = HttpSensorProvider()
        previous_physical = self.store.latest_physical(self.site["siteId"])
        if previous_physical:
            self.physical.accept(previous_physical)
        self.sensor = None
        self.memory = TransitionState()
        self.status = None
        self.mode = "simulation" if provider == "mock" else "normal"
        self.impact_scope = "local_segment"
        self.scenario_id = "normal-steady"
        self.elapsed = 0.0
        self.paused = False
        self.manual_level = None
        self.last_tick = utc_now()
        self.run_id = str(uuid4())
        self.subscribers: set[asyncio.Queue] = set()
        self.tasks = []
        self.last_evaluated_id = None
        self.rendered_ids: set[str] = set()
        self.run = self.new_run(self.last_tick)

    def new_run(self, now: datetime) -> dict:
        self.run_id = str(uuid4())
        config_hash = hashlib.sha256(json.dumps({"thresholds": self.config, "site": self.site}, sort_keys=True).encode()).hexdigest()
        record = {"runId": self.run_id, "buildId": self.build_id,
                  "scenario": self.scenario_id, "seed": 0, "startedAt": iso(now), "configurationHash": config_hash,
                  "gtfsDatasetVersion": self.site.get("gtfsDatasetVersion"), "realtimeFetchedAt": self.real_transport.get("fetchedAt")}
        self.store.event(self.run_id, "run-started", record, now)
        return record

    def scenario(self) -> dict:
        return {"id": self.scenario_id, "paused": self.paused, "elapsedSeconds": round(self.elapsed, 3),
                "manualLevel": self.manual_level, "manualRainfall": self.manual_rainfall,
                "transportMode": self.transport_mode, "mode": self.mode, "impactScope": self.impact_scope}

    def effective_transport(self, now: datetime) -> dict:
        real = copy.deepcopy(self.transport.snapshot(now))
        if self.cached_transport and real.get("freshness") == "unavailable":
            real = copy.deepcopy(self.cached_transport)
            real["freshness"] = "stale"
            for feed in real.get("feeds", {}).values():
                if feed.get("freshness") != "unavailable":
                    feed["freshness"] = "stale"
                    feed["error"] = "restored_cache_requires_refresh"
        if self.transport_refresh_failed:
            real["freshness"] = "stale" if real.get("freshness") != "unavailable" else "unavailable"
            for feed in real.get("feeds", {}).values():
                if feed.get("freshness") != "unavailable":
                    feed["freshness"] = "stale"
                feed["error"] = "adapter_refresh_failed"
        self.real_transport = copy.deepcopy(real)
        if self.mode == "simulation" and self.scenario_id == "transport-feed-unavailable":
            real.update(source="fixture", freshness="unavailable", vehicles=[], tripUpdates=[], alerts=[], fixture=True,
                        fixtureLabel="Demonstration transport outage — not a live feed failure")
            real["feeds"] = {name: {"freshness": "unavailable", "error": "fixture_outage"} for name in ("vehiclePositions", "tripUpdates", "serviceAlerts")}
        elif self.mode == "simulation" and self.scenario_id == "official-alert-present":
            # Do not combine a fixture's timestamp/health with an actual feed's content.
            real = {"routeShortName": "58", "source": "fixture", "fixture": True,
                    "fixtureLabel": "Demonstration official-alert fixture — not a live official alert",
                    "fetchedAt": iso(now), "feedTimestamp": iso(now), "freshness": "fresh", "vehicles": [], "tripUpdates": [],
                    "alerts": [{"id": "demo-route58-no-service", "header": "DEMONSTRATION FIXTURE: Route 58 no service",
                                "description": "A test alert to demonstrate independent official-service classification. This is not a live official report.",
                                "effect": "NO_SERVICE", "source": "fixture", "activeFrom": iso(now)}],
                    "feeds": {name: {"freshness": "fresh", "source": "fixture", "fetchedAt": iso(now), "feedTimestamp": iso(now)} for name in ("vehiclePositions", "tripUpdates", "serviceAlerts")}}
        else:
            return apply_fallback(real, self.mock_transport.snapshot(now), force_mock=self.mode == "simulation" and self.transport_mode == "mock")
        # Named test fixtures are intentionally separate from automatic fallback.
        real["fallback"] = False
        real["liveFeeds"] = copy.deepcopy(self.real_transport.get("feeds", {}))
        return real

    async def ingest(self, reading: SensorReading, *, external=False, now=None) -> dict:
        now = now or utc_now()
        if reading.siteId != self.site["siteId"]:
            raise ValueError("site_not_configured")
        if external and reading.source != "physical":
            raise ValueError("physical_source_required")
        if (reading.observedAt - now).total_seconds() > self.config.get("futureToleranceSeconds", 5):
            raise ValueError("future_observation")
        reading = reading.model_copy(update={"receivedAt": now})
        result = self.store.put_reading(reading)
        if result in {"duplicate", "conflict"}:
            return {"result": result, "readingId": str(reading.readingId), "latest": False}
        latest = True
        if external:
            latest = self.physical.accept(reading)
            if self.mode == "normal" and latest:
                self.sensor = reading
        elif self.mode == "simulation":
            self.sensor = reading
        self.store.event(self.run_id, "sensor-ingested", {"readingId": str(reading.readingId), "source": reading.source,
                         "observedAt": iso(reading.observedAt), "receivedAt": iso(now), "outOfOrder": not latest}, now)
        return {"result": result, "readingId": str(reading.readingId), "latest": latest}

    async def tick(self, now=None, *, generate=True):
        now = now or utc_now()
        delta = max(0, (now - self.last_tick).total_seconds())
        self.last_tick = now
        if self.mode == "simulation":
            if not self.paused:
                self.elapsed += delta
            if generate:
                reading = await self.mock.get_latest(self.site["siteId"], scenario_id=self.scenario_id, elapsed=self.elapsed, now=now, manual_level=self.manual_level, manual_rainfall=self.manual_rainfall)
                await self.ingest(reading, now=now)
        else:
            self.sensor = await self.physical.get_latest(self.site["siteId"])
        transport = self.effective_transport(now)
        old = self.status
        self.status, self.memory = evaluate_status(self.sensor, transport, self.config, now, self.memory,
                         site_id=self.site["siteId"], impact_scope=self.impact_scope, simulated=self.mode == "simulation")
        if old is None or old["hazardState"] != self.status["hazardState"] or old["serviceState"] != self.status["serviceState"]:
            self.store.event(self.run_id, "state-transition", {"hazardState": self.status["hazardState"], "serviceState": self.status["serviceState"],
                             "simulated": self.status["simulated"], "serviceSource": self.status["serviceSource"],
                             "previousHazardState": old["hazardState"] if old else None, "reasonCodes": self.status["reasonCodes"],
                             "message": f"Hazard {self.status['hazardState']} · service {self.status['serviceState']}"}, now)
        if self.sensor and str(self.sensor.readingId) != self.last_evaluated_id:
            self.last_evaluated_id = str(self.sensor.readingId)
            self.store.event(self.run_id, "reading-evaluated", {"readingId": self.last_evaluated_id,
                             "observedAt": iso(self.sensor.observedAt), "receivedAt": iso(self.sensor.receivedAt), "evaluatedAt": iso(now),
                             "hazardState": self.status["hazardState"]}, now)
        snapshot = self.snapshot(now, transport=transport)
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(snapshot)
        return snapshot

    def weather(self, now: datetime) -> dict:
        reading = self.sensor
        value = reading.rainfallIntensityMmPerHour if reading else None
        if value is None:
            return {"intensityMmPerHour": None, "source": "unavailable", "observedAt": None, "freshness": "unavailable"}
        age = (now - reading.observedAt).total_seconds()
        freshness = "fresh"
        if reading.quality in {"fault", "unknown"} or age < -self.config.get("futureToleranceSeconds", 5):
            freshness = "unavailable"
        elif reading.quality == "stale" or age > self.config.get("sensorStaleSeconds", 30):
            freshness = "stale"
        return {"intensityMmPerHour": value, "source": reading.source, "observedAt": iso(reading.observedAt), "freshness": freshness}

    def snapshot(self, now=None, transport=None) -> dict:
        now = now or utc_now()
        return {"status": self.status, "sensor": self.sensor.model_dump(mode="json") if self.sensor else None, "weather": self.weather(now),
                "transport": transport if transport is not None else self.effective_transport(now),
                "scenario": self.scenario(), "timeline": self.store.events(self.run_id, 20, exclude=("sensor-ingested", "reading-evaluated", "browser-render", "transport-polled")),
                "serverTime": iso(now)}

    async def start_scenario(self, scenario_id: str):
        if scenario_id not in SCENARIO_IDS:
            raise ValueError("unknown_scenario")
        self.mode, self.scenario_id = "simulation", scenario_id
        self.elapsed, self.paused, self.manual_level = 0.0, False, None
        self.manual_rainfall = None
        self.last_tick = utc_now()
        # Every named scenario starts from its documented first reading.
        self.memory, self.sensor, self.status = TransitionState(), None, None
        self.run = self.new_run(self.last_tick)
        return await self.tick(self.last_tick)

    async def reset(self):
        self.impact_scope = "local_segment"
        self.manual_rainfall = None
        self.transport_mode = "auto"
        if self.mode == "normal":
            self.scenario_id, self.elapsed, self.manual_level, self.paused = "normal-steady", 0.0, None, False
            self.memory, self.status = TransitionState(), None
            self.run = self.new_run(utc_now())
            return await self.tick(generate=False)
        return await self.start_scenario("normal-steady")

    async def update_settings(self, mode=None, impact_scope=None, transport_mode=None):
        if transport_mode == "mock" and (mode or self.mode) != "simulation":
            raise ValueError("mock_transport_requires_simulation_mode")
        if mode and mode != self.mode:
            self.mode = mode
            self.memory, self.sensor, self.status = TransitionState(), None, None
            self.scenario_id, self.elapsed, self.manual_level = "normal-steady", 0.0, None
            self.manual_rainfall = None
            self.paused = False
            self.last_tick = utc_now()
        if transport_mode:
            self.transport_mode = transport_mode
        if impact_scope:
            self.impact_scope = impact_scope
        if self.mode == "normal":
            self.impact_scope = "local_segment"
            self.transport_mode = "auto"
        self.store.event(self.run_id, "settings-changed", self.scenario())
        return await self.tick()

    async def refresh_transport(self):
        try:
            result = await self.transport.refresh()
            self.transport_refresh_failed = False
            if result and result.get("freshness") != "unavailable":
                self.store.cache("transport", result)
                self.cached_transport = None
            if result:
                self.store.event(self.run_id, "transport-polled", {"source": "transport-victoria", "freshness": result.get("freshness"),
                                 "fetchedAt": result.get("fetchedAt"), "feedTimestamp": result.get("feedTimestamp"), "feeds": result.get("feeds", {})})
            return result
        except Exception:
            # Never retain an exception string: upstream URLs/headers may contain secrets.
            self.store.event(self.run_id, "transport-error", {"code": "adapter_refresh_failed"})
            self.transport_refresh_failed = True
            return None

    async def start(self):
        async def sensors():
            while True:
                await asyncio.sleep(self.config.get("sensorIntervalSeconds", 1))
                await self.tick()

        async def feeds():
            while True:
                await self.refresh_transport()
                await self.tick(generate=False)
                await asyncio.sleep(self.config.get("transportPollSeconds", 60))

        self.tasks = [asyncio.create_task(sensors()), asyncio.create_task(feeds())]

    def render_telemetry(self, reading_id: str, rendered_at: datetime) -> dict:
        if reading_id in self.rendered_ids or self.store.has_render(reading_id):
            return {"result": "duplicate"}
        reading = self.store.get_reading(reading_id)
        if not reading:
            raise ValueError("reading_not_found")
        evaluation = self.store.evaluation(reading_id)
        if not evaluation:
            raise ValueError("reading_not_evaluated")
        observed = datetime.fromisoformat(reading["observedAt"])
        latency = (rendered_at - observed).total_seconds() * 1000
        if latency < -5000 or (rendered_at - utc_now()).total_seconds() > 300:
            raise ValueError("browser_clock_out_of_range")
        self.rendered_ids.add(reading_id)
        sample = {"readingId": reading_id, "observedAt": reading["observedAt"], "receivedAt": reading["receivedAt"],
                  "evaluatedAt": evaluation["evaluatedAt"], "renderedAt": iso(rendered_at), "latencyMs": round(latency, 3), "source": reading["source"], "measurement": "browser_reported_wall_clock"}
        self.store.event(evaluation["runId"], "browser-render", sample)
        return {"result": "accepted", **sample}

    def export(self):
        events = self.store.events(self.run_id)
        samples = [event for event in events if event["type"] == "browser-render"]
        return {**self.run, "scenario": self.scenario_id, "realtimeFetchedAt": self.real_transport.get("fetchedAt"),
                "events": events, "latencySamplesMs": [event["latencyMs"] for event in samples],
                "renderSamples": samples, "transitionChecks": [event for event in events if event["type"] == "state-transition"],
                "errors": [event for event in events if event["type"].endswith("error")],
                "notes": "Browser samples are reported by the browser clock; device clock synchronization is not established. Historical runs remain in SQLite."}

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.transport.close()
        self.store.close()
