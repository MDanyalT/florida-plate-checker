"""SQLite engine setup and repository helpers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.data_paths import prepare_data_storage
from app.models import Base, CheckHistory, CheckingRun, Plate, utc_now
from app.settings import settings


def create_sqlite_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


prepare_data_storage(
    data_directory=settings.data_directory,
    database_path=settings.database_path,
    legacy_database_path=settings.legacy_database_path,
)
engine = create_sqlite_engine(settings.database_path)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)


RUN_METRIC_COLUMNS = {
    "batches_completed": "INTEGER NOT NULL DEFAULT 0",
    "retry_count": "INTEGER NOT NULL DEFAULT 0",
    "elapsed_seconds": "FLOAT NOT NULL DEFAULT 0",
    "captcha_pause_seconds": "FLOAT NOT NULL DEFAULT 0",
}


def _add_missing_run_metric_columns(target_engine: Engine) -> None:
    """Apply the small additive SQLite migration without replacing user data."""

    inspector = inspect(target_engine)
    if "checking_runs" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("checking_runs")}
    with target_engine.begin() as connection:
        for name, definition in RUN_METRIC_COLUMNS.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE checking_runs ADD COLUMN {name} {definition}"))


def init_db(target_engine: Engine = engine) -> None:
    Base.metadata.create_all(bind=target_engine)
    _add_missing_run_metric_columns(target_engine)


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def apply_check_result(
    session: Session,
    *,
    plate: Plate,
    status: str,
    raw_result: str,
    checked_at: datetime,
    batch_number: int,
    run: CheckingRun | None,
) -> bool:
    """Update current state, append history, and return whether status changed."""

    old_status = plate.current_status
    changed = old_status is not None and old_status != status
    if changed:
        plate.previous_status = old_status
        plate.status_changed_at = checked_at

    plate.current_status = status
    plate.raw_result = raw_result
    plate.first_checked_at = plate.first_checked_at or checked_at
    plate.last_checked_at = checked_at
    plate.check_count += 1
    plate.updated_at = utc_now()

    session.add(
        CheckHistory(
            plate_id=plate.id,
            status=status,
            raw_result=raw_result,
            checked_at=checked_at,
            batch_number=batch_number,
            run_id=run.id if run else None,
        )
    )
    return changed
