"""One-command, loopback-only local setup and launch: python run.py."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def execute(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def js_manager() -> list[str]:
    for name in ("pnpm", "npm"):
        candidate = shutil.which(name)
        if candidate:
            return [candidate]
    runtime = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
    node, pnpm = runtime / "bin/node.exe", runtime / "node_modules/pnpm/bin/pnpm.cjs"
    if node.exists() and pnpm.exists():
        os.environ["PATH"] = str(node.parent) + os.pathsep + os.environ.get("PATH", "")
        return [str(node), str(pnpm)]
    raise SystemExit("Install Node.js 22+ with npm (or pnpm), then run python run.py again.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--setup-only", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    python = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    if not python.exists():
        execute([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    requirement_hash = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
    marker = ROOT / ".venv/southbank-requirements.sha256"
    if not marker.exists() or marker.read_text() != requirement_hash:
        execute([str(python), "-m", "pip", "install", "-r", "requirements.txt"])
        marker.write_text(requirement_hash)
    if args.rebuild or not (ROOT / "web/dist/index.html").exists():
        manager = js_manager()
        execute([*manager, "--prefix", "web", "install"])
        execute([*manager, "--prefix", "web", "run", "build"])
    if args.setup_only:
        print("Setup complete. Run python run.py to start.")
        return
    source_hash = hashlib.sha256()
    for directory in ("api", "domain", "adapters", "web/src", "config"):
        for source in sorted((ROOT / directory).rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts:
                source_hash.update(str(source.relative_to(ROOT)).encode())
                source_hash.update(source.read_bytes())
    os.environ.setdefault("BUILD_ID", "source-" + source_hash.hexdigest()[:16])
    print(f"Southbank Flood Watch: http://127.0.0.1:{args.port}", flush=True)
    execute([str(python), "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(args.port)])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
