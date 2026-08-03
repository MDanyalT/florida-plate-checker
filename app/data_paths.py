"""Local data-directory preparation, migration, and SQLite backups."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


def ensure_data_directories(data_directory: Path, database_path: Path) -> None:
    """Create only the local folders the application owns."""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    for name in ("exports", "backups", "debug"):
        (data_directory / name).mkdir(parents=True, exist_ok=True)


def copy_sqlite_database(source: Path, destination: Path) -> None:
    """Copy a live SQLite database consistently, including WAL-backed changes."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.copying")
    temporary.unlink(missing_ok=True)
    try:
        with sqlite3.connect(source) as source_db, sqlite3.connect(temporary) as target_db:
            source_db.backup(target_db)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def migrate_legacy_database(legacy_path: Path, destination: Path) -> bool:
    """Safely copy the legacy database once, retaining the original as a fallback."""

    if destination.exists() or not legacy_path.exists():
        return False
    copy_sqlite_database(legacy_path, destination)
    marker = destination.parent / ".legacy-database-copied"
    marker.write_text(
        f"Copied from {legacy_path.resolve()} on {datetime.now().astimezone().isoformat()}\n",
        encoding="utf-8",
    )
    return True


def prepare_data_storage(
    *, data_directory: Path, database_path: Path, legacy_database_path: Path
) -> bool:
    """Prepare local folders and migrate a default legacy database when needed."""

    ensure_data_directories(data_directory, database_path)
    return migrate_legacy_database(legacy_database_path, database_path)


def create_database_backup(database_path: Path, backup_directory: Path) -> Path:
    """Create a timestamped, consistent SQLite backup and return its path."""

    if not database_path.exists():
        raise FileNotFoundError(f"Database does not exist: {database_path}")
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_directory / f"plate-research-{timestamp}.db"
    copy_sqlite_database(database_path, destination)
    return destination
