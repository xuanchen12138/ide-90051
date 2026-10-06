"""Run with: uvicorn api.main:app --host 127.0.0.1 --port 8000."""
import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from adapters.mock_sensor import SCENARIOS, SCENARIO_IDS
from api.deployment import DemoAccessMiddleware, validate_deployment
from api.runtime import ROOT, Runtime
from domain.models import ManualControl, RainfallControl, RenderTelemetry, SensorReading, SettingsUpdate, utc_now

load_dotenv(ROOT / ".env")


def create_app(database_path: str | None = None, start_background: bool = True, transport=None, *, site=None, config=None):
    @asynccontextmanager
    async def lifespan(application):
        validate_deployment()
        selected_transport = transport
        selected_site = site or json.loads((ROOT / "config/site.json").read_text(encoding="utf-8"))
        if selected_transport is None:
            from adapters.gtfs_realtime import TransportAdapter
            trip_path = ROOT / "config/gtfs-trip-index.json"
            trips = json.loads(trip_path.read_text(encoding="utf-8")) if trip_path.exists() else {}
            selected_transport = TransportAdapter(selected_site, trips, api_key=os.getenv("TRANSPORT_VIC_API_KEY", ""))
        path = database_path
        if path is None:
            path = os.getenv("DATABASE_URL", "sqlite:///./data/prototype.db")
            if not path.startswith("sqlite:///"):
                raise RuntimeError("Only sqlite:/// database URLs are supported by this local prototype")
            path = path.removeprefix("sqlite:///")
            if path != ":memory:" and not Path(path).is_absolute():
                path = str(ROOT / path)
        application.state.runtime = Runtime(path, selected_transport, selected_site, config)
        await application.state.runtime.tick()
        if start_background:
            await application.state.runtime.start()
        try:
            yield
        finally:
            await application.state.runtime.close()

    app = FastAPI(title="Southbank Flood Early-Warning Prototype", version="0.1.0", lifespan=lifespan)

    app.add_middleware(DemoAccessMiddleware)

    def runtime(request: Request) -> Runtime:
        return request.app.state.runtime

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme not in {"http", "https"} or parsed.netloc != request.headers.get("host"):
                    return JSONResponse({"detail": "cross_origin_write_rejected"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "cross_site_write_rejected"}, status_code=403)
            try:
                oversized = int(request.headers.get("content-length", "0")) > 65536
            except ValueError:
                oversized = True
            if oversized:
                return JSONResponse({"detail": "payload_too_large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def sanitized_validation(request: Request, error: RequestValidationError):
        codes = sorted({item["type"] for item in error.errors()})
        runtime(request).store.event(runtime(request).run_id, "validation-error", {"code": "invalid_payload", "validationTypes": codes})
        return JSONResponse({"detail": "invalid_payload", "validationTypes": codes}, status_code=422)

    def authorize(request: Request, environment: str):
        if environment == "ADMIN_API_TOKEN" and getattr(request.state, "demo_authenticated", False):
            return
        token = os.getenv(environment, "")
        if not token:
            return
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied, f"Bearer {token}"):
            raise HTTPException(401, "authorization_required", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/health/live")
    @app.get("/api/v1/health/live")
    async def live():
        # The local launcher uses this nonce to distinguish its child API from
        # an unrelated or previously running server on the requested port.
        instance_id = os.getenv("PLATFORM_INSTANCE_ID")
        return {"status": "ok", **({"instanceId": instance_id} if instance_id else {})}

    @app.get("/health/ready")
    @app.get("/api/v1/health/ready")
    async def ready(request: Request):
        current = runtime(request).snapshot()
        degraded = current["status"]["dataFreshness"]["sensor"] != "fresh" or current["transport"]["freshness"] != "fresh" or current["transport"].get("fallback", False)
        return {"status": "degraded" if degraded else "ready", "ready": True,
                "dataFreshness": current["status"]["dataFreshness"], "mode": current["scenario"]["mode"]}

    @app.get("/api/v1/site")
    async def get_site(request: Request):
        return runtime(request).site

    @app.get("/api/v1/site/geometry")
    async def get_geometry():
        return json.loads((ROOT / "config/route-58.geojson").read_text(encoding="utf-8"))

    @app.get("/api/v1/site/basemap", response_class=FileResponse)
    async def get_basemap():
        path = ROOT / "config/southbank-basemap.geojson"
        if not path.is_file():
            raise HTTPException(503, "local_basemap_unavailable")
        return FileResponse(path, media_type="application/geo+json")

    @app.get("/api/v1/scenarios")
    async def get_scenarios():
        return SCENARIOS

    @app.get("/api/v1/transport/snapshot")
    async def transport_snapshot(request: Request):
        return runtime(request).effective_transport(utc_now())

    @app.get("/api/v1/sensors/latest")
    async def latest_sensor(request: Request):
        value = runtime(request).sensor
        return value.model_dump(mode="json") if value else None

    @app.post("/api/v1/sensors/readings", status_code=201)
    async def sensor_ingest(reading: SensorReading, request: Request):
        authorize(request, "SENSOR_INGEST_TOKEN")
        try:
            result = await runtime(request).ingest(reading, external=True)
        except ValueError as error:
            code = str(error)
            runtime(request).store.event(runtime(request).run_id, "validation-error", {"code": code})
            raise HTTPException(422, code) from None
        if result["result"] == "conflict":
            runtime(request).store.event(runtime(request).run_id, "validation-error", {"code": "reading_id_conflict", "readingId": str(reading.readingId)})
            raise HTTPException(409, "reading_id_conflict")
        await runtime(request).tick(generate=False)
        return JSONResponse(result, status_code=200 if result["result"] == "duplicate" else 201)

    @app.get("/api/v1/status")
    async def get_status(request: Request):
        # Reevaluate age for read-only callers even with the test scheduler disabled.
        await runtime(request).tick(generate=False)
        return runtime(request).status

    @app.get("/api/v1/snapshot")
    async def get_snapshot(request: Request):
        return await runtime(request).tick(generate=False)

    @app.post("/api/v1/scenarios/{scenario_id}/start")
    async def scenario_start(scenario_id: str, request: Request):
        authorize(request, "ADMIN_API_TOKEN")
        if scenario_id not in SCENARIO_IDS:
            raise HTTPException(404, "unknown_scenario")
        if runtime(request).mode != "simulation":
            raise HTTPException(409, "scenario_control_requires_simulation_mode")
        return await runtime(request).start_scenario(scenario_id)

    @app.post("/api/v1/scenarios/pause")
    async def scenario_pause(request: Request):
        authorize(request, "ADMIN_API_TOKEN")
        current = runtime(request)
        if current.mode != "simulation":
            raise HTTPException(409, "scenario_control_requires_simulation_mode")
        await current.tick()
        current.paused = True
        current.store.event(current.run_id, "scenario-paused", {"message": "Scenario playback paused; observation heartbeat continues."})
        return await current.tick(generate=False)

    @app.post("/api/v1/scenarios/resume")
    async def scenario_resume(request: Request):
        authorize(request, "ADMIN_API_TOKEN")
        current = runtime(request)
        if current.mode != "simulation":
            raise HTTPException(409, "scenario_control_requires_simulation_mode")
        current.paused = False
        current.last_tick = utc_now()
        current.store.event(current.run_id, "scenario-resumed", {"message": "Scenario playback resumed."})
        return await current.tick()

    @app.post("/api/v1/scenarios/reset")
    async def scenario_reset(request: Request):
        authorize(request, "ADMIN_API_TOKEN")
        return await runtime(request).reset()

    @app.post("/api/v1/scenarios/manual")
    async def scenario_manual(value: ManualControl, request: Request):
        authorize(request, "ADMIN_API_TOKEN")
        current = runtime(request)
        if current.mode != "simulation":
            raise HTTPException(409, "manual_control_requires_simulation_mode")
        # Manual mode must clear fault/stale/transport fixtures rather than retaining their side effects.
        current.scenario_id, current.manual_level, current.paused = "normal-steady", value.level, True
        current.store.event(current.run_id, "manual-level", {"level": value.level, "message": f"Manual demonstration level: {value.level:g}/100"})
        return await current.tick()

    @app.post("/api/v1/scenarios/rainfall")
    async def scenario_rainfall(value: RainfallControl, request: Request):
        authorize(request, "ADMIN_API_TOKEN")
        current = runtime(request)
        if current.mode != "simulation":
            raise HTTPException(409, "rainfall_control_requires_simulation_mode")
        current.manual_rainfall = value.intensityMmPerHour
        current.store.event(current.run_id, "manual-rainfall", {"intensityMmPerHour": value.intensityMmPerHour,
                            "message": f"Simulated rain: {value.intensityMmPerHour:g} mm/h; independent of the scripted water level."})
        return await current.tick()

    @app.post("/api/v1/settings")
    async def settings(value: SettingsUpdate, request: Request):
        authorize(request, "ADMIN_API_TOKEN")
        try:
            return await runtime(request).update_settings(value.mode, value.impactScope, value.transportMode)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/v1/telemetry/render")
    async def telemetry(value: RenderTelemetry, request: Request):
        try:
            return runtime(request).render_telemetry(str(value.readingId), value.renderedAt)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get("/api/v1/events/export")
    async def export(request: Request):
        return runtime(request).export()

    @app.get("/api/v1/events")
    async def events(request: Request):
        current = runtime(request)
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        current.subscribers.add(queue)

        async def stream():
            try:
                yield "event: snapshot\ndata: " + json.dumps(current.snapshot()) + "\n\n"
                while not await request.is_disconnected():
                    try:
                        snapshot = await asyncio.wait_for(queue.get(), timeout=15)
                        yield "event: snapshot\ndata: " + json.dumps(snapshot) + "\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                current.subscribers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    dist = ROOT / "web/dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
