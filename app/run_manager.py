"""Single-run worker-thread coordinator for the local FastAPI application."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.checker_service import CheckResult, CheckerService
from app.database import apply_check_result
from app.models import CheckingRun, Plate


ACTIVE_STATUSES = ("queued", "running", "captcha", "stopping")


class RunManager:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        service_factory: Callable[[], CheckerService],
    ) -> None:
        self.session_factory = session_factory
        self.service_factory = service_factory
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_plate_ids: frozenset[int] = frozenset()

    @property
    def active_plate_ids(self) -> frozenset[int]:
        """Plate ids queued in the run currently being processed (empty when idle)."""

        thread = self._thread
        return self._active_plate_ids if thread and thread.is_alive() else frozenset()

    def recover_interrupted_runs(self) -> None:
        with self.session_factory() as session:
            runs = session.scalars(
                select(CheckingRun).where(CheckingRun.status.in_(ACTIVE_STATUSES))
            ).all()
            for run in runs:
                run.status = "interrupted"
                run.completed_at = datetime.now(timezone.utc)
                run.error_message = "Application restarted before this run completed."
            session.commit()

    def active_run(self, session: Session) -> CheckingRun | None:
        return session.scalar(
            select(CheckingRun)
            .where(CheckingRun.status.in_(ACTIVE_STATUSES))
            .order_by(CheckingRun.id.desc())
            .limit(1)
        )

    def start(self, plate_ids: Sequence[int]) -> CheckingRun:
        unique_ids = list(dict.fromkeys(int(value) for value in plate_ids))
        with self._lock:
            with self.session_factory() as session:
                active = self.active_run(session)
                if active is not None:
                    raise RuntimeError(f"Run #{active.id} is already active.")
                plates = session.scalars(select(Plate).where(Plate.id.in_(unique_ids))).all()
                by_id = {plate.id: plate for plate in plates}
                ordered = [by_id[plate_id] for plate_id in unique_ids if plate_id in by_id]
                if not ordered:
                    raise ValueError("Select at least one plate to check.")
                run = CheckingRun(status="queued", total_candidates=len(ordered))
                session.add(run)
                session.commit()
                run_id = run.id
                ordered_ids = [plate.id for plate in ordered]

            self._stop_event = threading.Event()
            self._active_plate_ids = frozenset(ordered_ids)
            self._thread = threading.Thread(
                target=self._worker,
                args=(run_id, ordered_ids),
                name=f"plate-check-run-{run_id}",
                daemon=True,
            )
            self._thread.start()
            with self.session_factory() as session:
                return session.get(CheckingRun, run_id)  # type: ignore[return-value]

    def stop(self) -> CheckingRun | None:
        self._stop_event.set()
        with self.session_factory() as session:
            active = self.active_run(session)
            if active:
                active.status = "stopping"
                session.commit()
            return active

    def shutdown(self, timeout: float = 15.0) -> None:
        """Request a safe stop and briefly wait for the worker to close Chromium."""

        self.stop()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

    def _worker(self, run_id: int, plate_ids: Sequence[int]) -> None:
        with self.session_factory() as session:
            run = session.get(CheckingRun, run_id)
            if run is None:
                return
            run.status = "running"
            session.commit()

        def update_state(state: str) -> None:
            with self.session_factory() as session:
                run = session.get(CheckingRun, run_id)
                if run and run.status not in {"stopping", "stopped"}:
                    run.status = state
                    session.commit()

        def update_batch(batch_number: int, _: Sequence[str]) -> None:
            with self.session_factory() as session:
                run = session.get(CheckingRun, run_id)
                if run:
                    run.current_batch = batch_number
                    session.commit()

        def save_result(result: CheckResult) -> None:
            with self.session_factory() as session:
                run = session.get(CheckingRun, run_id)
                plate = session.scalar(
                    select(Plate).where(Plate.normalized_plate == result.plate)
                )
                if run is None or plate is None:
                    raise RuntimeError(f"Database plate disappeared during run: {result.plate}")
                apply_check_result(
                    session,
                    plate=plate,
                    status=result.status,
                    raw_result=result.raw_result,
                    checked_at=result.checked_at,
                    batch_number=result.batch_number,
                    run=run,
                )
                run.checked_count += 1
                run.last_processed_plate = result.plate
                counter = {
                    "Available": "available_count",
                    "Not available": "unavailable_count",
                    "Invalid": "invalid_count",
                    "Unknown": "unknown_count",
                    "Error": "error_count",
                }[result.status]
                setattr(run, counter, getattr(run, counter) + 1)
                session.commit()

        try:
            with self.session_factory() as session:
                plates = session.scalars(select(Plate).where(Plate.id.in_(plate_ids))).all()
                by_id = {plate.id: plate for plate in plates}
                candidates = [by_id[plate_id].normalized_plate for plate_id in plate_ids if plate_id in by_id]
            stopped = self.service_factory().run(
                candidates,
                on_result=save_result,
                on_batch=update_batch,
                on_state=update_state,
                should_stop=self._stop_event.is_set,
            )
            with self.session_factory() as session:
                run = session.get(CheckingRun, run_id)
                if run:
                    run.status = "stopped" if stopped else "completed"
                    run.completed_at = datetime.now(timezone.utc)
                    session.commit()
        except Exception as exc:
            with self.session_factory() as session:
                run = session.get(CheckingRun, run_id)
                if run:
                    run.status = "failed"
                    run.completed_at = datetime.now(timezone.utc)
                    run.error_message = str(exc)
                    session.commit()
