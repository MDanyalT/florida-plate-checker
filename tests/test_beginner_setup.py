from __future__ import annotations

import importlib.util
import os
import re
import sqlite3
import threading
import zipfile
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app import launcher_utils, settings as settings_module
from app.data_paths import create_database_backup, migrate_legacy_database
from app.database import create_sqlite_engine, init_db


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_server_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "plate_research_server_for_tests", PROJECT_ROOT / "app.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_health_endpoint() -> None:
    module = load_server_module()
    with TestClient(module.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_launcher_health_check_bypasses_proxy(monkeypatch) -> None:
    received: dict[str, object] = {}

    class Response:
        status = 200

        def read(self) -> bytes:
            return b'{"status": "ok"}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class LocalOpener:
        def open(self, url: str, *, timeout: float) -> Response:
            received["url"] = url
            received["timeout"] = timeout
            return Response()

    def build_opener(proxy_handler):
        received["proxy_handler"] = proxy_handler
        return LocalOpener()

    monkeypatch.setattr(launcher_utils.urllib.request, "build_opener", build_opener)

    assert launcher_utils.health_is_ready(timeout=2.5) is True
    assert received["url"] == "http://127.0.0.1:8000/health"
    assert received["timeout"] == 2.5


def test_first_run_database_initialization(tmp_path: Path) -> None:
    database = tmp_path / "new-user" / "plates.db"
    engine = create_sqlite_engine(database)
    init_db(engine)
    assert database.exists()
    assert {"plates", "checking_runs", "check_history"}.issubset(inspect(engine).get_table_names())
    engine.dispose()


def test_existing_database_receives_run_metrics_without_losing_rows(tmp_path: Path) -> None:
    database = tmp_path / "existing.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE checking_runs ("
            "id INTEGER PRIMARY KEY, status TEXT NOT NULL, total_candidates INTEGER NOT NULL, "
            "checked_count INTEGER NOT NULL, available_count INTEGER NOT NULL, "
            "unavailable_count INTEGER NOT NULL, invalid_count INTEGER NOT NULL, "
            "unknown_count INTEGER NOT NULL, error_count INTEGER NOT NULL, "
            "current_batch INTEGER NOT NULL, started_at DATETIME NOT NULL, "
            "completed_at DATETIME, last_processed_plate TEXT, error_message TEXT)"
        )
        connection.execute(
            "INSERT INTO checking_runs VALUES "
            "(1, 'completed', 1, 1, 1, 0, 0, 0, 0, 1, CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP, 'SAFE1', NULL)"
        )
    engine = create_sqlite_engine(database)
    init_db(engine)
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(checking_runs)")}
        saved = connection.execute(
            "SELECT status, last_processed_plate FROM checking_runs WHERE id=1"
        ).fetchone()
    assert {
        "batches_completed",
        "retry_count",
        "elapsed_seconds",
        "captcha_pause_seconds",
    }.issubset(columns)
    assert saved == ("completed", "SAFE1")
    engine.dispose()


def test_legacy_database_migration_and_existing_destination_preservation(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "data" / "plates.db"
    destination = tmp_path / "user_data" / "plates.db"
    legacy.parent.mkdir()
    with sqlite3.connect(legacy) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('legacy')")

    assert migrate_legacy_database(legacy, destination) is True
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("legacy",)

    with sqlite3.connect(destination) as connection:
        connection.execute("UPDATE sample SET value='current'")
    with sqlite3.connect(legacy) as connection:
        connection.execute("UPDATE sample SET value='changed legacy'")

    assert migrate_legacy_database(legacy, destination) is False
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("current",)


def test_data_path_configuration(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", "custom/location.db")
    assert settings_module._database_path() == PROJECT_ROOT / "custom" / "location.db"
    monkeypatch.setenv("DATABASE_PATH", "data/plates.db")
    assert settings_module._database_path() == settings_module.DATA_DIRECTORY / "plates.db"


def test_backup_creation_is_a_readable_sqlite_copy(tmp_path: Path) -> None:
    source = tmp_path / "plates.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('kept')")
    backup = create_database_backup(source, tmp_path / "backups")
    assert backup.parent == tmp_path / "backups"
    assert backup.name.startswith("plate-research-")
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("kept",)


def test_browser_opening_guard(monkeypatch) -> None:
    module = load_server_module()
    opened = threading.Event()

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setenv("OPEN_BROWSER", "true")
    monkeypatch.delenv("PLATE_RESEARCH_BROWSER_OPENED", raising=False)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    module._browser_opened = False
    assert module.open_browser_once(opener=lambda _url: opened.set(), startup_timeout=0.2)
    assert opened.wait(1)
    assert module.open_browser_once(opener=lambda _url: None, startup_timeout=0.2) is False


def test_pid_file_helpers_and_project_validation(tmp_path: Path, monkeypatch) -> None:
    pid_file = tmp_path / ".runtime" / "plate-research.pid"
    launcher_utils.write_pid_file(pid_file, 4321)
    assert launcher_utils.read_pid_file(pid_file) == 4321
    assert launcher_utils.remove_pid_file(pid_file, expected_pid=9999) is False
    assert launcher_utils.remove_pid_file(pid_file, expected_pid=4321) is True

    app_path = tmp_path / "app.py"
    assert launcher_utils.is_project_process(os.getpid(), tmp_path, f'python "{app_path}"')
    assert not launcher_utils.is_project_process(os.getpid(), tmp_path, "python unrelated.py")

    launcher_utils.write_pid_file(pid_file, 999999)
    monkeypatch.setattr(launcher_utils, "process_exists", lambda _pid: False)
    assert launcher_utils.stop_project_process(pid_file, tmp_path) == "stale"
    assert not pid_file.exists()
    assert not pid_file.with_suffix(".stop").exists()


def test_public_ui_contains_no_personal_placeholder_names() -> None:
    public_files = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "plates.example.txt",
        *sorted((PROJECT_ROOT / "templates").rglob("*.html")),
        PROJECT_ROOT / "static" / "app.js",
    ]
    forbidden = ("DAN" + "YAL", "TA" + "RIQ", "R" + "HM", "T" + "AM")
    public_text = "\n".join(path.read_text() for path in public_files).upper()
    assert all(re.search(rf"\b{name}\b", public_text) is None for name in forbidden)


def test_launchers_are_project_scoped_and_release_archives_are_clean(tmp_path: Path) -> None:
    launchers = [
        PROJECT_ROOT / "Setup Plate Research.command",
        PROJECT_ROOT / "Open Plate Research.command",
        PROJECT_ROOT / "Stop Plate Research.command",
        PROJECT_ROOT / "Setup Plate Research.bat",
        PROJECT_ROOT / "Open Plate Research.bat",
        PROJECT_ROOT / "Stop Plate Research.bat",
    ]
    launcher_text = "\n".join(path.read_text(encoding="utf-8") for path in launchers)
    assert "killall" not in launcher_text.lower()
    assert "taskkill /im python" not in launcher_text.lower()
    assert "plate-research.pid" in launcher_text

    spec = importlib.util.spec_from_file_location(
        "build_releases_for_tests", PROJECT_ROOT / "scripts" / "build_releases.py"
    )
    assert spec and spec.loader
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    mac_zip = tmp_path / "mac.zip"
    windows_zip = tmp_path / "windows.zip"
    builder.build_archive(mac_zip, builder.MAC_LAUNCHERS, macos=True)
    builder.build_archive(windows_zip, builder.WINDOWS_LAUNCHERS, macos=False)
    with zipfile.ZipFile(mac_zip) as archive:
        names = set(archive.namelist())
        assert "Setup Plate Research.command" in names
        assert "Setup Plate Research.bat" not in names
        assert all(not name.startswith(("tests/", "user_data/", ".venv/")) for name in names)
    with zipfile.ZipFile(windows_zip) as archive:
        names = set(archive.namelist())
        assert "Setup Plate Research.bat" in names
        assert "Setup Plate Research.command" not in names
