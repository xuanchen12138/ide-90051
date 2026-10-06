"""Start the prebuilt cloud/container app with exactly one scheduler/worker."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if not (ROOT / "web/dist/index.html").is_file():
        raise SystemExit("Frontend build missing. Build web/dist before starting the deployment.")
    try:
        port = int(os.getenv("PORT", "10000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise SystemExit("PORT must be an integer from 1 to 65535") from None
    os.chdir(ROOT)
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=port, workers=1,
                timeout_graceful_shutdown=10, proxy_headers=True)


if __name__ == "__main__":
    main()
