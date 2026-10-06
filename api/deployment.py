"""Optional shared-demo access gate; never ship secrets to browser assets."""
import base64
import binascii
import hmac
import os

from starlette.responses import JSONResponse

HEALTH_PATHS = {"/health/live", "/health/ready", "/api/v1/health/live", "/api/v1/health/ready"}
COLLECTOR_PATH = "/api/v1/sensors/readings"


def validate_deployment():
    public = os.getenv("PUBLIC_DEPLOYMENT", "").lower() in {"1", "true", "yes"}
    password = os.getenv("DEMO_ACCESS_PASSWORD", "")
    if public and len(password) < 16:
        raise RuntimeError("PUBLIC_DEPLOYMENT requires DEMO_ACCESS_PASSWORD with at least 16 characters")
    if public or password:
        for name in ("ADMIN_API_TOKEN", "SENSOR_INGEST_TOKEN"):
            if len(os.getenv(name, "")) < 16:
                raise RuntimeError(f"Shared demo requires {name} with at least 16 characters")


def basic_authenticated(header: str) -> bool:
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
        username, separator, password = decoded.partition(":")
    except (ValueError, UnicodeError, binascii.Error):
        return False
    expected_username = os.getenv("DEMO_ACCESS_USERNAME", "demo")
    expected_password = os.getenv("DEMO_ACCESS_PASSWORD", "")
    return bool(separator and expected_password) and hmac.compare_digest(
        username.encode(), expected_username.encode()
    ) and hmac.compare_digest(password.encode(), expected_password.encode())


class DemoAccessMiddleware:
    """Pure ASGI wrapper, preserving SSE streaming without response buffering.

    HTTP Basic credentials are cached by the browser for fetch/EventSource.
    Health checks remain public. Device ingestion has its own Bearer token;
    the demo password must never authorize a physical sensor reading.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not os.getenv("DEMO_ACCESS_PASSWORD"):
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path in HEALTH_PATHS or (path == COLLECTOR_PATH and scope["method"] == "POST"):
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        if basic_authenticated(authorization):
            scope.setdefault("state", {})["demo_authenticated"] = True
            return await self.app(scope, receive, send)
        # Preserve authenticated scripted admin access without sharing Basic
        # credentials. Sensor tokens have no access to the rest of the app.
        admin = os.getenv("ADMIN_API_TOKEN", "")
        if admin and hmac.compare_digest(authorization.encode(), f"Bearer {admin}".encode()):
            return await self.app(scope, receive, send)
        response = JSONResponse({"detail": "demo_login_required"}, status_code=401, headers={
            "WWW-Authenticate": 'Basic realm="Southbank demonstration", charset="UTF-8"',
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })
        await response(scope, receive, send)
