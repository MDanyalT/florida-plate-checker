import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.checker_service import CheckResult
from app.models import CheckHistory, CheckingRun, Plate
from app.run_manager import RunManager


class FakeCheckerService:
    def run(
        self,
        candidates,
        *,
        on_batch_results,
        on_batch=None,
        on_state=None,
        on_metric=None,
        should_stop=None,
    ):
        if on_state:
            on_state("running")
        if on_batch:
            on_batch(1, candidates)
        on_batch_results(
            [
                CheckResult(
                    plate=plate,
                    status="Available",
                    raw_result="MOCK AVAILABLE",
                    checked_at=datetime.now(timezone.utc),
                    batch_number=1,
                )
                for plate in candidates
            ]
        )
        if on_metric:
            on_metric("batch_completed", 1)
        return False


def test_mocked_checking_run_persists_results(
    session_factory: sessionmaker[Session], db_session: Session
) -> None:
    plate = Plate(plate="ABC", normalized_plate="ABC", current_status="Not available")
    db_session.add(plate)
    db_session.commit()

    manager = RunManager(session_factory, FakeCheckerService)
    run = manager.start([plate.id])
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with session_factory() as session:
            current = session.get(CheckingRun, run.id)
            if current and current.status == "completed":
                break
        time.sleep(0.02)

    with session_factory() as session:
        finished = session.get(CheckingRun, run.id)
        updated = session.scalar(select(Plate).where(Plate.normalized_plate == "ABC"))
        assert finished is not None and finished.status == "completed"
        assert finished.checked_count == 1
        assert finished.batches_completed == 1
        assert finished.elapsed_seconds >= 0
        assert finished.average_seconds_per_plate >= 0
        assert updated is not None and updated.current_status == "Available"
        assert updated.previous_status == "Not available"
        assert session.query(CheckHistory).count() == 1
