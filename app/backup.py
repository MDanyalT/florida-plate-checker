"""JSON backup and non-destructive restore for the local plate database.

A backup contains every plate (with favorites and notes), every check-history
record, and every checking run. Restoring *merges* a backup into the current
database: nothing that already exists is deleted or overwritten with older data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CheckHistory, CheckingRun, Plate
from app.plate_utils import normalize_plate, validate_plate


BACKUP_FORMAT = "florida-plate-finder-backup"
BACKUP_VERSION = 1

PLATE_FIELDS = (
    "plate",
    "normalized_plate",
    "current_status",
    "raw_result",
    "first_checked_at",
    "last_checked_at",
    "previous_status",
    "status_changed_at",
    "check_count",
    "favorite",
    "notes",
    "created_at",
    "updated_at",
)
RUN_FIELDS = (
    "id",
    "started_at",
    "completed_at",
    "status",
    "total_candidates",
    "checked_count",
    "available_count",
    "unavailable_count",
    "invalid_count",
    "unknown_count",
    "error_count",
    "current_batch",
    "last_processed_plate",
    "error_message",
)
DATETIME_FIELDS = {
    "first_checked_at",
    "last_checked_at",
    "status_changed_at",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
    "checked_at",
}


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def build_backup(session: Session) -> dict[str, Any]:
    plates = session.scalars(select(Plate).order_by(Plate.id)).all()
    runs = session.scalars(select(CheckingRun).order_by(CheckingRun.id)).all()
    history = session.scalars(select(CheckHistory).order_by(CheckHistory.id)).all()
    plate_names = {plate.id: plate.normalized_plate for plate in plates}
    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "counts": {"plates": len(plates), "history": len(history), "runs": len(runs)},
        "plates": [{field: _serialize(getattr(plate, field)) for field in PLATE_FIELDS} for plate in plates],
        "runs": [{field: _serialize(getattr(run, field)) for field in RUN_FIELDS} for run in runs],
        "history": [
            {
                "plate": plate_names[entry.plate_id],
                "status": entry.status,
                "raw_result": entry.raw_result,
                "checked_at": _serialize(entry.checked_at),
                "batch_number": entry.batch_number,
                "run_id": entry.run_id,
            }
            for entry in history
            if entry.plate_id in plate_names
        ],
    }


def restore_backup(session: Session, payload: Any, max_plate_length: int = 7) -> dict[str, int]:
    """Merge a backup into the database and return counts of what was added/updated."""

    if not isinstance(payload, dict) or payload.get("format") != BACKUP_FORMAT:
        raise ValueError("This file is not a Florida Plate Finder backup.")
    if int(payload.get("version", 0)) > BACKUP_VERSION:
        raise ValueError("This backup was made by a newer version of the app.")

    summary = {"plates_added": 0, "plates_updated": 0, "history_added": 0, "runs_added": 0, "skipped": 0}

    # Runs: keep existing ids when free, otherwise give the run a new id.
    run_id_map: dict[int, int] = {}
    existing_runs = {
        (_aware(run.started_at), run.total_candidates): run.id
        for run in session.scalars(select(CheckingRun)).all()
    }
    for raw in payload.get("runs", []) or []:
        try:
            started = _parse_datetime(raw.get("started_at"))
            key = (started, int(raw.get("total_candidates", 0)))
            old_id = int(raw["id"])
        except (KeyError, TypeError, ValueError):
            summary["skipped"] += 1
            continue
        if key in existing_runs:
            run_id_map[old_id] = existing_runs[key]
            continue
        status = str(raw.get("status") or "interrupted")
        if status in {"queued", "running", "captcha", "stopping"}:
            status = "interrupted"
        run = CheckingRun(
            **{
                field: (_parse_datetime(raw.get(field)) if field in DATETIME_FIELDS else raw.get(field))
                for field in RUN_FIELDS
                if field not in {"id", "status"} and raw.get(field) is not None
            },
            status=status,
        )
        session.add(run)
        session.flush()
        run_id_map[old_id] = run.id
        existing_runs[key] = run.id
        summary["runs_added"] += 1

    plates_by_name = {plate.normalized_plate: plate for plate in session.scalars(select(Plate)).all()}
    for raw in payload.get("plates", []) or []:
        name = normalize_plate(str(raw.get("normalized_plate") or raw.get("plate") or ""))
        if validate_plate(name, max(max_plate_length, len(name) if name else 0)):
            summary["skipped"] += 1
            continue
        incoming_checked = _parse_datetime(raw.get("last_checked_at"))
        plate = plates_by_name.get(name)
        if plate is None:
            values = {
                field: (_parse_datetime(raw.get(field)) if field in DATETIME_FIELDS else raw.get(field))
                for field in PLATE_FIELDS
                if raw.get(field) is not None
            }
            values["plate"] = name
            values["normalized_plate"] = name
            values["check_count"] = int(values.get("check_count") or 0)
            values["favorite"] = bool(values.get("favorite"))
            values["notes"] = str(values.get("notes") or "")[:2000]
            plate = Plate(**values)
            session.add(plate)
            plates_by_name[name] = plate
            summary["plates_added"] += 1
            continue
        changed = False
        if raw.get("favorite") and not plate.favorite:
            plate.favorite = True
            changed = True
        incoming_notes = str(raw.get("notes") or "").strip()
        if incoming_notes and incoming_notes not in plate.notes:
            plate.notes = (f"{plate.notes}\n{incoming_notes}" if plate.notes else incoming_notes)[:2000]
            changed = True
        current_checked = _aware(plate.last_checked_at)
        if incoming_checked and (current_checked is None or incoming_checked > current_checked):
            for field in ("current_status", "raw_result", "previous_status"):
                setattr(plate, field, raw.get(field))
            plate.last_checked_at = incoming_checked
            plate.status_changed_at = _parse_datetime(raw.get("status_changed_at"))
            plate.check_count = max(plate.check_count, int(raw.get("check_count") or 0))
            changed = True
        incoming_first = _parse_datetime(raw.get("first_checked_at"))
        if incoming_first and (plate.first_checked_at is None or incoming_first < _aware(plate.first_checked_at)):
            plate.first_checked_at = incoming_first
            changed = True
        if changed:
            summary["plates_updated"] += 1
    session.flush()

    existing_history = {
        (entry.plate_id, _aware(entry.checked_at), entry.status)
        for entry in session.scalars(select(CheckHistory)).all()
    }
    for raw in payload.get("history", []) or []:
        plate = plates_by_name.get(normalize_plate(str(raw.get("plate", ""))))
        try:
            checked_at = _parse_datetime(raw.get("checked_at"))
        except ValueError:
            checked_at = None
        if plate is None or checked_at is None or not raw.get("status"):
            summary["skipped"] += 1
            continue
        key = (plate.id, checked_at, str(raw["status"]))
        if key in existing_history:
            continue
        old_run = raw.get("run_id")
        session.add(
            CheckHistory(
                plate_id=plate.id,
                status=str(raw["status"]),
                raw_result=str(raw.get("raw_result") or ""),
                checked_at=checked_at,
                batch_number=int(raw.get("batch_number") or 0),
                run_id=run_id_map.get(int(old_run)) if old_run not in (None, "") else None,
            )
        )
        existing_history.add(key)
        summary["history_added"] += 1
    session.commit()
    return summary
