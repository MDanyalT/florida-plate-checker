"""SQLite engine setup and repository helpers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

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


engine = create_sqlite_engine(settings.database_path)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)


def init_db(target_engine: Engine = engine) -> None:
    Base.metadata.create_all(bind=target_engine)


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

