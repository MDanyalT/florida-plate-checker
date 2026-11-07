"""Small, standard-library helpers shared by the desktop launchers."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

LOCAL_URL = "http://127.0.0.1:8000"


def read_pid_file(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
        pid = int(value)
        return pid if pid > 0 else None
    except (FileNotFoundError, OSError, ValueError):
        return None


def write_pid_file(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(f"{pid}\n", encoding="utf-8")
    temporary.replace(path)


def remove_pid_file(path: Path, expected_pid: int | None = None) -> bool:
    current = read_pid_file(path)
    if expected_pid is not None and current not in (None, expected_pid):
        return False
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def process_command(pid: int) -> str:
    if os.name == "nt":
        command = (
            "$p=Get-CimInstance Win32_Process -Filter \"ProcessId="
            f"{pid}\" -ErrorAction SilentlyContinue; if ($p) {{$p.CommandLine}}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
    return result.stdout.strip() if result.returncode == 0 else ""


def is_project_process(pid: int, project_root: Path, command_line: str | None = None) -> bool:
    if not process_exists(pid):
        return False
    command = command_line if command_line is not None else process_command(pid)
    expected_app = str((project_root / "app.py").resolve()).lower()
    normalized = command.replace('"', "").lower()
    return expected_app in normalized


def health_is_ready(url: str = f"{LOCAL_URL}/health", timeout: float = 1.0) -> bool:
    # A launcher must reach its own loopback server directly.  In particular,
    # inherited HTTP(S)_PROXY settings can otherwise send this request to a
    # proxy instead of 127.0.0.1 and make a healthy local app look unavailable.
    local_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with local_opener.open(url, timeout=timeout) as response:
            return response.status == 200 and b'"status":"ok"' in response.read().replace(b" ", b"")
    except (OSError, urllib.error.URLError):
        return False


def wait_for_health(timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health_is_ready():
            return True
        time.sleep(0.25)
    return False


def port_is_in_use(port: int = 8000) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def stop_project_process(pid_file: Path, project_root: Path, timeout: float = 10.0) -> str:
    stop_marker = pid_file.with_suffix(".stop")
    pid = read_pid_file(pid_file)
    if pid is None:
        remove_pid_file(pid_file)
        stop_marker.unlink(missing_ok=True)
        return "not-running"
    if not process_exists(pid):
        remove_pid_file(pid_file, pid)
        stop_marker.unlink(missing_ok=True)
        return "stale"
    if not is_project_process(pid, project_root):
        return "mismatch"
    stop_marker.parent.mkdir(parents=True, exist_ok=True)
    stop_marker.write_text(f"{pid}\n", encoding="utf-8")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while process_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if not process_exists(pid):
        remove_pid_file(pid_file, pid)
        return "stopped"
    stop_marker.unlink(missing_ok=True)
    return "timeout"


def _main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("initialize")
    subparsers.add_parser("health")
    wait_parser = subparsers.add_parser("wait-health")
    wait_parser.add_argument("--timeout", type=float, default=30.0)
    subparsers.add_parser("port-in-use")
    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--pid-file", type=Path, required=True)
    stop_parser.add_argument("--project-root", type=Path, required=True)
    subparsers.add_parser("backup")
    args = parser.parse_args()

    if args.command == "initialize":
        from app.database import init_db

        init_db()
        print("Application folders and database are ready.")
        return 0
    if args.command == "health":
        return 0 if health_is_ready() else 1
    if args.command == "wait-health":
        return 0 if wait_for_health(args.timeout) else 1
    if args.command == "port-in-use":
        return 0 if port_is_in_use() else 1
    if args.command == "stop":
        result = stop_project_process(args.pid_file, args.project_root)
        print(result)
        return 0 if result in {"not-running", "stale", "stopped"} else 2
    if args.command == "backup":
        from app.data_paths import create_database_backup
        from app.settings import settings

        path = create_database_backup(settings.database_path, settings.backups_directory)
        print(path)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_main())
