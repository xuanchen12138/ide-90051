"""Check the real feeds without ever printing credentials, headers or payloads."""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from adapters.gtfs_realtime import TransportAdapter


async def main():
    load_dotenv(ROOT / ".env")
    site = json.loads((ROOT / "config/site.json").read_text(encoding="utf-8"))
    index = json.loads((ROOT / "config/gtfs-trip-index.json").read_text(encoding="utf-8"))
    adapter = TransportAdapter(site, index, os.getenv("TRANSPORT_VIC_API_KEY", ""))
    try:
        result = await adapter.refresh()
        report = {"freshness": result["freshness"], "feeds": result["feeds"],
                  "route58Vehicles": len(result["vehicles"]), "route58TripUpdates": len(result["tripUpdates"]),
                  "route58Alerts": len(result["alerts"])}
        print(json.dumps(report, indent=2))
        if "--output" in sys.argv:
            target = Path(sys.argv[sys.argv.index("--output") + 1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0 if result["freshness"] == "fresh" else 1
    finally:
        await adapter.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
