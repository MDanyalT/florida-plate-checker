from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.database import apply_check_result
from app.models import CheckHistory, CheckingRun, Plate


def test_status_updates_and_change_detection(db_session: Session) -> None:
    plate = Plate(plate="ABC", normalized_plate="ABC")
    run = CheckingRun(total_candidates=1, status="running")
    db_session.add_all([plate, run])
    db_session.commit()

    first = datetime.now(timezone.utc) - timedelta(days=1)
    changed = apply_check_result(
        db_session,
        plate=plate,
        status="Not available",
        raw_result="NOT AVAILABLE",
        checked_at=first,
        batch_number=1,
        run=run,
    )
    db_session.commit()
    assert changed is False
    assert plate.previous_status is None

    second = datetime.now(timezone.utc)
    changed = apply_check_result(
        db_session,
        plate=plate,
        status="Available",
        raw_result="AVAILABLE",
        checked_at=second,
        batch_number=1,
        run=run,
    )
    db_session.commit()
    assert changed is True
    assert plate.current_status == "Available"
    assert plate.previous_status == "Not available"
    assert plate.status_changed_at == second
    assert plate.check_count == 2
    assert db_session.query(CheckHistory).filter_by(plate_id=plate.id).count() == 2

