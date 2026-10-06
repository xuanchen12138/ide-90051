"""Measure actual polling recovery time with deterministic HTTP fault injection.

This exercises the real adapter/cache but substitutes httpx.MockTransport. It is
not a claim about a live upstream outage. Default: one real 60-second poll wait.
"""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from google.transit import gtfs_realtime_pb2 as pb
from adapters.gtfs_realtime import TransportAdapter


async def main():
    config = json.loads((ROOT / "config/demo-thresholds.json").read_text())
    targets = json.loads((ROOT / "config/evaluation.json").read_text())
    failing = False
    requests = []
    def handler(request):
        failed = failing and request.url.path.endswith("service-alerts")
        requests.append({"feed": request.url.path.rsplit("/", 1)[-1], "status": 503 if failed else 200})
        if failed:
            return httpx.Response(503)
        feed = pb.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        feed.header.timestamp = int(datetime.now(timezone.utc).timestamp())
        return httpx.Response(200, content=feed.SerializeToString())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = TransportAdapter({"gtfsRouteIds": ["fixture-58"], "gtfsStopIds": ["fixture-116"]}, {}, "fixture-only", client=client)
        initial = await adapter.refresh()
        failing = True
        failure = await adapter.refresh()
        started = time.monotonic()
        failing = False
        await asyncio.sleep(config["transportPollSeconds"])
        recovered = await adapter.refresh()
        elapsed = time.monotonic() - started
    result = {"measuredAt": datetime.now(timezone.utc).isoformat(), "method": "Real adapter and elapsed wall time; injected HTTP503 through httpx.MockTransport, not live upstream outage",
              "pollIntervalSeconds": config["transportPollSeconds"], "initial": initial["freshness"],
              "duringFailure": failure["freshness"], "unaffectedVehicleFeed": failure["feeds"]["vehiclePositions"]["freshness"],
              "afterRecovery": recovered["freshness"], "recoverySeconds": elapsed, "targetSeconds": targets["maxTransportRecoverySeconds"],
              "passed": elapsed <= targets["maxTransportRecoverySeconds"] and initial["freshness"] == "fresh" and failure["freshness"] == "stale" and recovered["freshness"] == "fresh",
              "requests": requests}
    target = ROOT / "artifacts" / f"transport-recovery-{int(time.time())}.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
