# Optional deployment path (not deployed)

The validated execution target is a local single-process FastAPI service serving the Vite build and SQLite. No cloud account, billable resource, domain or public endpoint is provisioned by this implementation.

For a small shared demonstration, build `web/dist`, install the pinned Python requirements and run **one** Uvicorn worker behind an HTTPS reverse proxy. Mount a persistent directory for `DATABASE_URL=sqlite:////data/prototype.db`; supply the transport key, collector token and administration token as runtime secrets. The Maps browser key must be restricted to the deployment's HTTP referrer; rebuild browser assets when changing it. Configure Maps usage quotas and budget alerts.

Protect scenario administration with an authenticated reverse proxy/session layer that can inject the admin Bearer token server-side, or use authenticated API calls. Do not put administration/collector secrets into Vite variables. Restrict collector network access and configure `SENSOR_INGEST_TOKEN`; the public UI must not become an unauthenticated scenario-control service. Apply request rate/body limits, backups, observability and retention policy before any shared deployment.

Proxy SSE without buffering (`/api/v1/events`), preserve the correct Host/Origin relationship and use sufficiently long idle timeouts. `/health/live` tests the process; `/health/ready` reports usable/degraded source health. Missing credentials or upstream outages must remain visible to users.

Multiple workers/instances and PostgreSQL are not implemented. A production/shared multi-instance architecture would move scheduler ownership and state to a shared service/storage layer and add migrations. Kubernetes/Fission and 3D remain deferred. Deployment of this prototype must never be described as validation for operational tram safety.
