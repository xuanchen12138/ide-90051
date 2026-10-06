"""One-command, loopback-only local setup and launch: python run.py."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError
from uuid import uuid4

ROOT = Path(__file__).resolve().parent


def execute(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def stop_process_tree(process: subprocess.Popen | None) -> None:
    """Stop our child and its Windows venv redirector descendants."""
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


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
    parser.add_argument("--sensor-port", help="Start the real USB collector too, e.g. COM8; selects physical mode")
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
    server_command = [str(python), "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(args.port)]
    if not args.sensor_port:
        execute(server_command)
        return
    # Explicit hardware startup selects physical water. The UI may still switch
    # to simulation; the independent collector keeps recording actual frames.
    with socket.socket() as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError:
            raise SystemExit(f"Port {args.port} is already in use. Stop that server or choose --port 8001.") from None
    child_env = os.environ.copy()
    child_env["SENSOR_PROVIDER"] = "physical"
    instance_id = str(uuid4())
    child_env["PLATFORM_INSTANCE_ID"] = instance_id
    server = subprocess.Popen(server_command, cwd=ROOT, env=child_env)
    collector = None
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            time.sleep(.3)
            if server.poll() is not None:
                raise SystemExit("API failed to start; the sensor collector was not started.")
            try:
                with urlopen(f"http://127.0.0.1:{args.port}/health/live", timeout=1) as response:
                    if response.status == 200 and json.load(response).get("instanceId") == instance_id and server.poll() is None:
                        break
            except (OSError, URLError, ValueError):
                pass
        else:
            raise SystemExit("API did not become ready; check the startup messages.")
        collector = subprocess.Popen([str(python), str(ROOT / "scripts/collect_sensor.py"),
            "--port", args.sensor_port, "--api-url", f"http://127.0.0.1:{args.port}"], cwd=ROOT, env=child_env)
        print(f"Physical float sensor: {args.sensor_port}. Ctrl+C stops API and collector.", flush=True)
        while server.poll() is None and collector.poll() is None:
            time.sleep(.25)
        if (server.poll() not in (None, 0)) or (collector.poll() not in (None, 0)):
            raise SystemExit("A platform process stopped; see the preceding error.")
    finally:
        for process in (collector, server):
            stop_process_tree(process)



if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
