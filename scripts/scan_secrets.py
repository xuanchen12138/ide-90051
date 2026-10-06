"""Report paths, never values; include browser assets and generated evidence."""
from __future__ import annotations
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

EXCLUDE_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "data", ".tools"}


def main():
    load_dotenv(ROOT / ".env")
    secrets = [os.environ.get(k, "").encode() for k in ("TRANSPORT_VIC_API_KEY", "SENSOR_INGEST_TOKEN", "ADMIN_API_TOKEN", "DEMO_ACCESS_PASSWORD")]
    secrets = [s for s in secrets if len(s) >= 8]
    findings, scanned = [], 0
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            if name.startswith(".env") and name != ".env.example":
                continue
            path = Path(directory) / name
            if path.suffix.lower() in {".png", ".jpg", ".pdf", ".docx", ".zip", ".db", ".db-wal", ".db-shm", ".pyc"}:
                continue
            if path.stat().st_size > 20 * 1024 * 1024:
                continue
            payload = path.read_bytes()
            scanned += 1
            if any(secret in payload for secret in secrets):
                findings.append(str(path.relative_to(ROOT)))
    if findings:
        print("FAIL: configured backend secret appears in: " + ", ".join(findings))
        return 1
    print(f"PASS: {scanned} text/source/build/evidence files checked; no configured backend secret found outside excluded secret files.")
    print("Excludes dependency trees, git internals, raw datasets, binaries and local SQLite stores. This is a scoped check, not a guarantee about unknown credentials or history.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
