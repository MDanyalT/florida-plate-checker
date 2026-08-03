#!/usr/bin/env python3
"""Launch the Florida Plate Research dashboard at http://127.0.0.1:8000."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.launcher_utils import remove_pid_file, write_pid_file
from app.routes import router, run_manager
from app.settings import PROJECT_ROOT


LOCAL_URL = "http://127.0.0.1:8000"
_browser_open_lock = threading.Lock()
_browser_opened = False


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def open_browser_once(
    url: str = LOCAL_URL,
    *,
    opener: object = webbrowser.open,
    startup_timeout: float = 30.0,
) -> bool:
    """Open the dashboard once after it becomes healthy, including reload children."""

    global _browser_opened
    if not _env_enabled("OPEN_BROWSER") or os.getenv("PLATE_RESEARCH_BROWSER_OPENED") == "1":
        return False
    with _browser_open_lock:
        if _browser_opened:
            return False
        _browser_opened = True
        os.environ["PLATE_RESEARCH_BROWSER_OPENED"] = "1"

    def wait_and_open() -> None:
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{url}/health", timeout=0.5) as response:
                    if response.status == 200:
                        opener(url)  # type: ignore[operator]
                        return
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)

    threading.Thread(target=wait_and_open, name="open-dashboard", daemon=True).start()
    return True


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    run_manager.recover_interrupted_runs()
    yield
    run_manager.shutdown()


app = FastAPI(
    title="Florida Plate Research",
    description="Local, responsible FLHSMV personalized plate research dashboard.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    pid_file_value = os.getenv("PLATE_RESEARCH_PID_FILE", "").strip()
    pid_file = Path(pid_file_value) if pid_file_value else None
    if pid_file is not None:
        write_pid_file(pid_file, os.getpid())
    open_browser_once()
    try:
        uvicorn.run(app, host="127.0.0.1", port=8000)
    finally:
        if pid_file is not None:
            remove_pid_file(pid_file, os.getpid())
