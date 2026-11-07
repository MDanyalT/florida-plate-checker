from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.backup import build_backup, restore_backup
from app.database import apply_check_result
from app.models import CheckHistory, CheckingRun, Plate


def _seed(session):
    run = CheckingRun(total_candidates=1, status="completed")
    plate = Plate(plate="SUNNY", normalized_plate="SUNNY", favorite=True, notes="for mom")
    session.add_all([run, plate])
    session.commit()
    apply_check_result(session, plate=plate, status="Available", raw_result="AVAILABLE",
                       checked_at=datetime.now(timezone.utc), batch_number=1, run=run)
    session.commit()


def test_backup_round_trip_into_empty_database(db_session, session_factory, tmp_path) -> None:
    _seed(db_session)
    payload = build_backup(db_session)
    assert payload["counts"] == {"plates": 1, "history": 1, "runs": 1}

    from app.database import create_sqlite_engine
    from app.models import Base
    from sqlalchemy.orm import sessionmaker

    engine = create_sqlite_engine(tmp_path / "restore.db")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as target:
        summary = restore_backup(target, payload)
        assert summary["plates_added"] == 1 and summary["history_added"] == 1 and summary["runs_added"] == 1
        plate = target.scalar(select(Plate))
        assert plate.favorite and plate.notes == "for mom" and plate.current_status == "Available"
        assert target.scalar(select(CheckHistory)).run_id == target.scalar(select(CheckingRun)).id
        # Restoring twice adds nothing new.
        again = restore_backup(target, payload)
        assert again["plates_added"] == 0 and again["history_added"] == 0 and again["runs_added"] == 0
    engine.dispose()


def test_restore_never_overwrites_newer_results(db_session) -> None:
    _seed(db_session)
    payload = build_backup(db_session)
    plate = db_session.scalar(select(Plate))
    newer = datetime.now(timezone.utc) + timedelta(days=1)
    apply_check_result(db_session, plate=plate, status="Not available", raw_result="NOT AVAILABLE",
                       checked_at=newer, batch_number=1, run=None)
    plate.favorite = False
    db_session.commit()
    restore_backup(db_session, payload)
    db_session.refresh(plate)
    assert plate.current_status == "Not available"
    assert plate.favorite is True  # favorites from a backup are merged in


def test_restore_rejects_foreign_files(db_session) -> None:
    import pytest

    with pytest.raises(ValueError):
        restore_backup(db_session, {"plates": []})
