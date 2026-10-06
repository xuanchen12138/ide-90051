# Northflank free demonstration deployment

The cloud target is a single Docker container on Northflank Sandbox. It serves
the React build, FastAPI, the 1 Hz SSE stream and the simulation scheduler from
one process. This is a demonstration, not an operational flood warning system.

## Service configuration

- Project: `southbank-flood-watch`, Northflank Cloud **US - Central** (free region).
- Source: private GitHub repository `xuanchen12138/ide-90051`, branch `main`.
- Service type: combined build and deployment; Dockerfile `/Dockerfile`, context `/`.
- Compute: **Sandbox / free**, one instance. Do not enable autoscaling or add paid volumes.
- Public HTTP port: `10000`; Northflank supplies the HTTPS endpoint.
- Health check: HTTP `GET /health/live`, port `10000`.
- Startup command: Dockerfile default (`python scripts/start_server.py`).

Set these **runtime** environment variables, not build arguments:

| Variable | Value |
| --- | --- |
| `PORT` | `10000` |
| `PUBLIC_DEPLOYMENT` | `true` |
| `DEMO_ACCESS_USERNAME` | `demo` |
| `DEMO_ACCESS_PASSWORD` | Unique random password, at least 16 characters |
| `ADMIN_API_TOKEN` | Independent random token, at least 16 characters |
| `SENSOR_INGEST_TOKEN` | Independent random token, at least 16 characters |
| `SENSOR_PROVIDER` | `mock` |
| `TRANSPORT_POLL_SECONDS` | `60` |
| `DATABASE_URL` | `sqlite:////app/data/prototype.db` |
| `TRANSPORT_VIC_API_KEY` | Optional backend-only Transport Victoria key |

The application refuses to start a public deployment without its three access
secrets. A browser login using `demo` and the demo password grants access to the
page, SSE, exports and scenario controls. The password is not bundled into the
frontend. Scripted administration may use `ADMIN_API_TOKEN` as a Bearer token;
physical sensor ingestion accepts only its separate `SENSOR_INGEST_TOKEN`.
Health endpoints are intentionally public. Keep secrets in the platform's
runtime variable store; never commit them or paste them into issue/build logs.

The cached OpenStreetMap map needs no Google Maps key. Without a transport key,
the real-time traffic feed is explicitly unavailable; static GTFS and simulation
remain usable. Missing or stale feed data must not be presented as live data.

## Free-tier storage and shared state

SQLite is stored in the container's ephemeral filesystem. A restart or redeploy
can erase accumulated readings and event history. Export demonstration evidence
before a redeploy. Persistent volumes are deliberately excluded from this free
setup. All signed-in viewers share one simulation state; changing a scenario
changes it for everyone. Multiple workers, instances and PostgreSQL are not
implemented.

## Validation and updates

GitHub Actions (`Validate deployment`) runs the Python and frontend tests,
builds the Linux Docker image, and checks health, the anonymous-access rejection,
the authenticated frontend and the geographic data endpoint. Check this workflow
before promoting a change. Northflank's build/deployment status is independent
of GitHub Actions; a local build alone does not confirm a live deployment.

After deployment, verify `/health/live`, browser authentication, `/api/v1/site/basemap`,
scenario controls and the continuously updating `/api/v1/events` stream over the
actual HTTPS endpoint. Proxies must preserve Host/Origin and stream SSE without
buffering. `/health/ready` reports usable/degraded source health, including
missing transport credentials. This does not validate physical sensors, water
depth thresholds or operational tram safety.

For local Docker validation (Docker Desktop required):

```powershell
cd C:\Project\ide-90051
docker build -t southbank-flood-watch .
# Use a local, Git-ignored .env containing the runtime settings above.
docker run --rm --env-file .env -p 10000:10000 southbank-flood-watch
# Open http://localhost:10000. Ctrl+C stops this demonstration.
```

Official references: [Northflank pricing](https://northflank.com/pricing),
[runtime variables](https://northflank.com/docs/v1/application/run/inject-runtime-variables),
[networking](https://northflank.com/docs/v1/application/network/networking-on-northflank).
