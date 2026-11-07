"""FastAPI HTML, import, export, generator, backup, and polling routes."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload
from starlette.datastructures import UploadFile

from app.backup import build_backup, restore_backup
from app.checker_service import CheckerService
from app.data_paths import create_database_backup
from app.database import SessionLocal, get_db
from app.exporter import rows_to_csv
from app.generator import IDEA_OPTIONS, MAX_PREVIEW_COMBINATIONS, estimate_generation, generate_candidates
from app.importer import inspect_csv, parse_text_content
from app.models import CheckHistory, CheckingRun, Plate
from app.plate_utils import analyze_candidates, normalize_plate, validate_plate
from app.run_manager import ACTIVE_STATUSES, RunManager
from app.schemas import RunProgress
from app.settings import PROJECT_ROOT, settings


router = APIRouter()
logger = logging.getLogger(__name__)
if settings.development_mode:
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        development_handler = logging.StreamHandler()
        development_handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(development_handler)
    logger.propagate = False
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
run_manager = RunManager(SessionLocal, lambda: CheckerService(settings))

STALE_AFTER = timedelta(days=7)
REVIEW_STATUSES = ("Invalid", "Unknown", "Error")


# ---------------------------------------------------------------------------
# Presentation helpers (template filters and globals)
# ---------------------------------------------------------------------------


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    return _aware(value).astimezone().strftime("%b %d, %Y · %I:%M %p")  # type: ignore[union-attr]


def _format_date(value: datetime | None) -> str:
    if value is None:
        return "—"
    local = _aware(value).astimezone()  # type: ignore[union-attr]
    today = datetime.now().astimezone()
    label = f"{local:%b} {local.day}"
    return label if local.year == today.year else f"{label}, {local.year}"


def _time_ago(value: datetime | None) -> str:
    if value is None:
        return "never"
    delta = datetime.now(timezone.utc) - _aware(value)  # type: ignore[operator]
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} min ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = delta.days
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    return f"on {_format_date(value)}"


def status_info(plate: Plate, checking: bool = False) -> dict[str, Any]:
    """Plain-language, freshness-aware availability label for a saved plate."""

    status = plate.current_status
    checked = plate.last_checked_at
    stale = bool(checked and datetime.now(timezone.utc) - _aware(checked) > STALE_AFTER)  # type: ignore[operator]
    if checking:
        return {"key": "checking", "short": "Checking…", "label": "Checking now", "icon": "↻",
                "detail": "This plate is in the current checking run.", "stale": False}
    if status is None:
        return {"key": "unchecked", "short": "Not checked", "label": "Not yet checked", "icon": "○",
                "detail": "Check it to see what the official FLHSMV site reports.", "stale": False}
    if status == "Available":
        return {"key": "available", "short": "Available", "label": "Available when last checked", "icon": "✓",
                "detail": "Availability can change at any time. Verify before ordering.", "stale": stale}
    if status == "Not available":
        return {"key": "unavailable", "short": "Unavailable", "label": "Unavailable when last checked", "icon": "✕",
                "detail": "Someone may already have this plate, or it isn't allowed.", "stale": stale}
    details = {
        "Invalid": "The official site said this configuration isn't valid.",
        "Unknown": "The official response wasn't recognized. Check it again or verify on the official site.",
        "Error": "The last check hit an error. Try checking again.",
    }
    return {"key": "review", "short": "Needs verification", "label": "Needs verification", "icon": "!",
            "detail": details.get(status, "Verify this result on the official site."), "stale": stale}


RUN_LABELS = {
    "queued": ("Starting", "active"),
    "running": ("Checking", "active"),
    "captcha": ("Waiting for you", "attention"),
    "stopping": ("Stopping", "active"),
    "completed": ("Finished", "good"),
    "stopped": ("Stopped early", "neutral"),
    "failed": ("Didn't finish", "bad"),
    "interrupted": ("Interrupted", "neutral"),
}


def run_info(run: CheckingRun) -> dict[str, Any]:
    label, tone = RUN_LABELS.get(run.status, (run.status.title(), "neutral"))
    end = _aware(run.completed_at) or datetime.now(timezone.utc)
    duration = max(0.0, (end - _aware(run.started_at)).total_seconds())  # type: ignore[operator]
    minutes, seconds = divmod(int(duration), 60)
    per_minute = (run.checked_count / (duration / 60)) if duration >= 1 and run.checked_count else 0.0
    needs_review = run.invalid_count + run.unknown_count + run.error_count
    return {
        "label": label,
        "tone": tone,
        "active": run.status in ACTIVE_STATUSES,
        "percent": round(run.checked_count / run.total_candidates * 100) if run.total_candidates else 0,
        "needs_review": needs_review,
        "duration": f"{minutes} min {seconds:02d} s" if minutes else f"{seconds} s",
        "per_minute": f"{per_minute:.1f}",
        "remaining": max(0, run.total_candidates - run.checked_count),
    }


templates.env.filters["datetime"] = _format_datetime
templates.env.filters["shortdate"] = _format_date
templates.env.filters["timeago"] = _time_ago
templates.env.globals["status_info"] = status_info
templates.env.globals["run_info"] = run_info
templates.env.globals["flhsmv_url"] = settings.flhsmv_url
templates.env.globals["max_plate_length"] = settings.max_plate_length
templates.env.globals["large_run_threshold"] = settings.large_run_confirmation_threshold
templates.env.globals["max_run_size"] = settings.max_plates_per_run


def _redirect(path: str, message: str, kind: str = "success") -> RedirectResponse:
    base_path, marker, fragment = path.partition("#")
    separator = "&" if "?" in base_path else "?"
    suffix = f"#{fragment}" if marker else ""
    return RedirectResponse(
        f"{base_path}{separator}message={quote(message)}&kind={quote(kind)}{suffix}",
        status_code=303,
    )


def _safe_return_url(value: str | None, default: str = "/saved") -> str:
    return value if value and value.startswith("/") and not value.startswith("//") else default


def _page(request: Request, name: str, **context: Any) -> HTMLResponse:
    base = {
        "request": request,
        "message": request.query_params.get("message"),
        "message_kind": request.query_params.get("kind", "success"),
    }
    base.update(context)
    return templates.TemplateResponse(request=request, name=name, context=base)


def _checking_ids(session: Session) -> set[int]:
    """Plates in the active run that have not been checked yet during that run."""

    ids = run_manager.active_plate_ids
    if not ids:
        return set()
    run = run_manager.active_run(session)
    if run is None:
        return set()
    started = _aware(run.started_at)
    plates = session.execute(
        select(Plate.id, Plate.last_checked_at).where(Plate.id.in_(ids))
    ).all()
    return {
        plate_id
        for plate_id, checked in plates
        if checked is None or _aware(checked) < started  # type: ignore[operator]
    }


def _status_counts(session: Session) -> dict[str, int]:
    status_counts = dict(
        session.execute(
            select(Plate.current_status, func.count(Plate.id)).group_by(Plate.current_status)
        ).all()
    )
    return {
        "total": session.scalar(select(func.count(Plate.id))) or 0,
        "available": status_counts.get("Available", 0),
        "unavailable": status_counts.get("Not available", 0),
        "invalid": status_counts.get("Invalid", 0),
        "unknown": status_counts.get("Unknown", 0),
        "error": status_counts.get("Error", 0),
        "unchecked": status_counts.get(None, 0),
        "favorites": session.scalar(select(func.count(Plate.id)).where(Plate.favorite.is_(True))) or 0,
        "changed": session.scalar(
            select(func.count(Plate.id)).where(Plate.status_changed_at.is_not(None))
        )
        or 0,
    }


# ---------------------------------------------------------------------------
# Home and quick single-plate check
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    return _render_home(session, request)


def _render_home(session: Session, request: Request, **extra: Any) -> HTMLResponse:
    stats = _status_counts(session)
    favorites = session.scalars(
        select(Plate).where(Plate.favorite.is_(True)).order_by(Plate.updated_at.desc()).limit(6)
    ).all()
    recent = session.scalars(select(Plate).order_by(Plate.updated_at.desc()).limit(6)).all()
    recent_changes = session.scalars(
        select(Plate)
        .where(Plate.status_changed_at.is_not(None))
        .order_by(Plate.status_changed_at.desc())
        .limit(4)
    ).all()
    return _page(
        request,
        "home.html",
        stats=stats,
        favorites=favorites,
        recent=recent,
        recent_changes=recent_changes,
        checking_ids=_checking_ids(session),
        **{"check_value": request.query_params.get("plate", ""), **extra},
    )


@router.post("/check")
async def quick_check(request: Request, session: Session = Depends(get_db)) -> Response:
    form = await request.form()
    raw = str(form.get("plate", ""))
    action = str(form.get("action", "check"))
    normalized = normalize_plate(raw)
    error = validate_plate(normalized, settings.max_plate_length)
    if error:
        return _render_home(session, request, check_error=error, check_value=raw)
    plate = session.scalar(select(Plate).where(Plate.normalized_plate == normalized))
    created = plate is None
    if plate is None:
        plate = Plate(plate=normalized, normalized_plate=normalized)
        session.add(plate)
    if action == "favorite":
        plate.favorite = True
    session.commit()
    if action in {"save", "favorite"}:
        message = f"Saved {normalized} to your plates." if created else f"{normalized} is already in your plates."
        return _redirect(f"/plates/{plate.id}", message)
    try:
        run_manager.start([plate.id])
    except (RuntimeError, ValueError) as exc:
        return _redirect(
            f"/plates/{plate.id}",
            f"{normalized} is saved, but it can't be checked right now: {exc} "
            "Check it again when the current run finishes.",
            "warning",
        )
    return _redirect(
        f"/plates/{plate.id}",
        f"Checking {normalized}. A browser window with the official FLHSMV site will open on this computer.",
    )


@router.get("/api/plates/lookup")
def lookup_plate(request: Request, session: Session = Depends(get_db)) -> JSONResponse:
    normalized = normalize_plate(request.query_params.get("plate", ""))
    error = validate_plate(normalized, settings.max_plate_length) if normalized else None
    plate = (
        session.scalar(select(Plate).where(Plate.normalized_plate == normalized))
        if normalized and not error
        else None
    )
    payload: dict[str, Any] = {"plate": normalized, "error": error, "saved": plate is not None}
    if plate is not None:
        info = status_info(plate, plate.id in _checking_ids(session))
        payload.update(
            id=plate.id,
            favorite=plate.favorite,
            status=info,
            last_checked=_time_ago(plate.last_checked_at) if plate.last_checked_at else None,
        )
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# Advanced tools: statistics, bulk import, exports, backup
# ---------------------------------------------------------------------------


def _tools_context(session: Session) -> dict[str, Any]:
    today_start = datetime.combine(date.today(), time.min).replace(tzinfo=timezone.utc)
    stats = _status_counts(session)
    stats["today"] = (
        session.scalar(select(func.count(Plate.id)).where(Plate.last_checked_at >= today_start)) or 0
    )
    stats["history"] = session.scalar(select(func.count(CheckHistory.id))) or 0
    stats["runs"] = session.scalar(select(func.count(CheckingRun.id))) or 0
    return {
        "stats": stats,
        "latest_run": session.scalar(select(CheckingRun).order_by(CheckingRun.id.desc()).limit(1)),
        "max_upload_bytes": settings.max_upload_bytes,
    }


def _render_dashboard(session: Session, request: Request, **extra: Any) -> HTMLResponse:
    """Render the tools page (formerly the dashboard), which hosts bulk import."""

    return _page(request, "tools.html", **_tools_context(session), **extra)


@router.get("/tools", response_class=HTMLResponse)
def tools(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    return _render_dashboard(session, request)


@router.get("/dashboard")
def legacy_dashboard() -> RedirectResponse:
    return RedirectResponse("/tools", status_code=307)


@router.post("/backups/create")
def create_backup() -> FileResponse:
    """Create and download a consistent local copy of the research database."""

    backup_path = create_database_backup(settings.database_path, settings.backups_directory)
    return FileResponse(
        backup_path,
        media_type="application/vnd.sqlite3",
        filename=backup_path.name,
    )


@router.post("/imports/manual/preview", response_class=HTMLResponse)
async def preview_manual_import(
    request: Request, session: Session = Depends(get_db)
) -> HTMLResponse:
    form = await request.form()
    text = str(form.get("plates_text", ""))
    report = analyze_candidates(text.splitlines(), settings.max_plate_length)
    return _render_dashboard(session, request, import_report=report, import_source="typed list")


@router.post("/imports/upload/preview", response_class=HTMLResponse)
async def preview_upload(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    form = await request.form()
    upload = form.get("plate_file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return _render_dashboard(session, request, upload_error="Choose a .txt or .csv file.")
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in {".txt", ".csv"}:
        return _render_dashboard(
            session, request, upload_error="Unsupported file type. Upload a .txt or .csv file."
        )
    raw = await upload.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        return _render_dashboard(
            session,
            request,
            upload_error=f"File exceeds the {settings.max_upload_bytes // 1024 // 1024} MB limit.",
        )
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _render_dashboard(session, request, upload_error="File must be UTF-8 text.")

    if suffix == ".txt":
        report = analyze_candidates(parse_text_content(content), settings.max_plate_length)
        return _render_dashboard(
            session,
            request,
            import_report=report,
            import_source=upload.filename,
            review_kind="upload",
        )

    try:
        inspection = inspect_csv(content)
    except ValueError as exc:
        return _render_dashboard(session, request, upload_error=str(exc))
    if inspection.selected_column:
        report = analyze_candidates(inspection.values, settings.max_plate_length)
        return _render_dashboard(
            session,
            request,
            import_report=report,
            import_source=upload.filename,
            review_kind="upload",
        )
    return _render_dashboard(
        session,
        request,
        csv_columns=inspection.columns,
        csv_content=content,
        csv_filename=upload.filename,
    )


@router.post("/imports/upload/select-column", response_class=HTMLResponse)
async def select_csv_column(
    request: Request, session: Session = Depends(get_db)
) -> HTMLResponse:
    form = await request.form()
    content = str(form.get("csv_content", ""))
    column = str(form.get("csv_column", ""))
    filename = str(form.get("csv_filename", "uploaded.csv"))
    try:
        inspection = inspect_csv(content, column)
        report = analyze_candidates(inspection.values, settings.max_plate_length)
        return _render_dashboard(
            session,
            request,
            import_report=report,
            import_source=filename,
            review_kind="upload",
        )
    except ValueError as exc:
        return _render_dashboard(session, request, upload_error=str(exc))


def _save_plates(session: Session, values: list[str]) -> tuple[int, int, dict[str, int]]:
    """Insert valid, new plates. Returns (added, already_saved, {plate: id})."""

    report = analyze_candidates(values, settings.max_plate_length)
    existing = {
        plate.normalized_plate: plate
        for plate in session.scalars(
            select(Plate).where(Plate.normalized_plate.in_(report.valid))
        ).all()
    } if len(report.valid) < 30_000 else {
        plate.normalized_plate: plate for plate in session.scalars(select(Plate)).all()
    }
    added: list[Plate] = []
    for normalized in report.valid:
        if normalized in existing:
            continue
        plate = Plate(plate=normalized, normalized_plate=normalized)
        session.add(plate)
        existing[normalized] = plate
        added.append(plate)
    session.commit()
    ids = {name: plate.id for name, plate in existing.items() if name in set(report.valid)}
    return len(added), len(report.valid) - len(added), ids


@router.post("/imports/confirm")
async def confirm_import(request: Request, session: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()
    selected = [str(value) for value in form.getlist("plates")]
    added, skipped, _ = _save_plates(session, selected)
    return _redirect("/saved", f"Added {added} plate(s); {skipped} were already saved.")


# ---------------------------------------------------------------------------
# Saved plates library
# ---------------------------------------------------------------------------

SHOW_FILTERS = {
    "all": "All plates",
    "available": "Available",
    "unavailable": "Unavailable",
    "unchecked": "Never checked",
    "review": "Needs verification",
    "favorites": "Favorites",
    "changed": "Recently changed",
}


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _filtered_plate_query(params: Any) -> Select[tuple[Plate]]:
    query = select(Plate)
    ids = [value for value in str(params.get("ids", "")).split(",") if value.isdigit()]
    if ids:
        query = query.where(Plate.id.in_([int(value) for value in ids]))
    search = str(params.get("q", "")).strip().upper()
    if search:
        query = query.where(Plate.normalized_plate.contains(search))
    show = str(params.get("show", ""))
    if show == "available":
        query = query.where(Plate.current_status == "Available")
    elif show == "unavailable":
        query = query.where(Plate.current_status == "Not available")
    elif show == "unchecked":
        query = query.where(Plate.current_status.is_(None))
    elif show == "review":
        query = query.where(Plate.current_status.in_(REVIEW_STATUSES))
    elif show == "favorites":
        query = query.where(Plate.favorite.is_(True))
    elif show == "changed":
        query = query.where(Plate.status_changed_at.is_not(None))
    status = str(params.get("status", ""))
    if status == "Never checked":
        query = query.where(Plate.current_status.is_(None))
    elif status:
        query = query.where(Plate.current_status == status)
    if params.get("favorite") == "1":
        query = query.where(Plate.favorite.is_(True))
    if params.get("changed") == "1":
        query = query.where(Plate.status_changed_at.is_not(None))
    if params.get("never_checked") == "1":
        query = query.where(Plate.last_checked_at.is_(None))
    length = str(params.get("length", ""))
    if length.isdigit():
        query = query.where(func.length(Plate.normalized_plate) == int(length))
    date_from = _parse_date(str(params.get("date_from", "")))
    date_to = _parse_date(str(params.get("date_to", "")))
    if date_from:
        query = query.where(Plate.last_checked_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.where(Plate.last_checked_at < datetime.combine(date_to, time.max))
    return query


SORT_OPTIONS = {
    "updated": ("Recently updated", "desc"),
    "plate": ("Plate A–Z", "asc"),
    "checked": ("Recently checked", "desc"),
    "changed": ("Recently changed", "desc"),
    "status": ("Status", "asc"),
    "count": ("Most checked", "desc"),
}


@router.get("/saved", response_class=HTMLResponse)
@router.get("/results", response_class=HTMLResponse)
def results(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    params = request.query_params
    query = _filtered_plate_query(params)
    sort_name = params.get("sort") or ("changed" if params.get("show") == "changed" else "updated")
    if sort_name not in SORT_OPTIONS:
        sort_name = "updated"
    direction = params.get("direction") or SORT_OPTIONS[sort_name][1]
    sort_columns = {
        "plate": Plate.normalized_plate,
        "status": Plate.current_status,
        "checked": Plate.last_checked_at,
        "changed": Plate.status_changed_at,
        "count": Plate.check_count,
        "updated": Plate.updated_at,
    }
    sort_column = sort_columns[sort_name]
    ordered = sort_column.asc() if direction == "asc" else sort_column.desc()
    query = query.order_by(ordered.nulls_last(), Plate.normalized_plate)
    view = "list" if params.get("view") == "list" else "cards"
    try:
        page = max(1, int(params.get("page", "1") or 1))
    except ValueError:
        page = 1
    per_page = 24 if view == "cards" else 50
    total = session.scalar(select(func.count()).select_from(_filtered_plate_query(params).subquery())) or 0
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    plates = session.scalars(query.offset((page - 1) * per_page).limit(per_page)).all()
    query_dict = dict(params)
    for key in ("page", "message", "kind"):
        query_dict.pop(key, None)
    advanced_keys = ("status", "length", "date_from", "date_to", "favorite", "changed", "never_checked")
    return _page(
        request,
        "saved.html",
        plates=plates,
        total=total,
        page=page,
        pages=pages,
        view=view,
        show=params.get("show", "all") if params.get("show") in SHOW_FILTERS else "all",
        show_filters=SHOW_FILTERS,
        sort_name=sort_name,
        direction=direction,
        sort_options=SORT_OPTIONS,
        query_dict=query_dict,
        pagination_query=urlencode(query_dict),
        filter_query=urlencode({k: v for k, v in query_dict.items() if k not in {"view"}}),
        advanced_active=any(params.get(key) for key in advanced_keys),
        counts=_status_counts(session),
        statuses=["Available", "Not available", "Invalid", "Unknown", "Error", "Never checked"],
        checking_ids=_checking_ids(session),
        return_url=str(request.url.path) + (f"?{urlencode(query_dict)}" if query_dict else ""),
    )


@router.get("/plates/{plate_id}", response_class=HTMLResponse)
def plate_detail(plate_id: int, request: Request, session: Session = Depends(get_db)) -> Response:
    plate = session.get(Plate, plate_id)
    if plate is None:
        return _redirect("/saved", "That plate isn't in your saved plates.", "warning")
    history = session.scalars(
        select(CheckHistory)
        .where(CheckHistory.plate_id == plate.id)
        .order_by(CheckHistory.checked_at.desc())
        .limit(100)
    ).all()
    return _page(
        request,
        "plate_detail.html",
        plate=plate,
        history=history,
        checking=plate.id in _checking_ids(session),
    )


@router.post("/plates/{plate_id}/favorite")
async def toggle_favorite(
    plate_id: int, request: Request, session: Session = Depends(get_db)
) -> RedirectResponse:
    plate = session.get(Plate, plate_id)
    if plate:
        plate.favorite = not plate.favorite
        session.commit()
    form = await request.form()
    return RedirectResponse(_safe_return_url(str(form.get("return_url", "/saved"))), status_code=303)


@router.post("/plates/{plate_id}/notes")
async def update_notes(
    plate_id: int, request: Request, session: Session = Depends(get_db)
) -> RedirectResponse:
    plate = session.get(Plate, plate_id)
    form = await request.form()
    if plate:
        plate.notes = str(form.get("notes", ""))[:2000]
        session.commit()
    return _redirect(
        _safe_return_url(str(form.get("return_url", "/saved"))), "Notes saved."
    )


@router.post("/plates/{plate_id}/delete")
async def delete_plate(
    plate_id: int, request: Request, session: Session = Depends(get_db)
) -> RedirectResponse:
    plate = session.get(Plate, plate_id)
    name = plate.normalized_plate if plate else "Plate"
    if plate:
        session.delete(plate)
        session.commit()
    form = await request.form()
    target = _safe_return_url(str(form.get("return_url", "/saved")))
    if target.startswith(f"/plates/{plate_id}"):
        target = "/saved"
    return _redirect(target, f"{name} and its check history were removed.")


@router.post("/plates/bulk")
async def bulk_plates(request: Request, session: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()
    action = str(form.get("bulk_action", ""))
    return_url = _safe_return_url(str(form.get("return_url", "/saved")))
    try:
        plate_ids = {int(value) for value in form.getlist("plate_ids")}
    except ValueError:
        return _redirect(return_url, "Invalid plate selection.", "error")
    if not plate_ids:
        return _redirect(return_url, "Select at least one plate first.", "warning")
    plates = session.scalars(select(Plate).where(Plate.id.in_(plate_ids))).all()
    if action in {"favorite", "unfavorite"}:
        for plate in plates:
            plate.favorite = action == "favorite"
        session.commit()
        verb = "Added to" if action == "favorite" else "Removed from"
        return _redirect(return_url, f"{verb} favorites: {len(plates)} plate(s).")
    if action == "delete":
        if form.get("confirm_delete") != "yes":
            return _redirect(return_url, "Deleting plates needs confirmation.", "error")
        for plate in plates:
            session.delete(plate)
        session.commit()
        return _redirect(return_url, f"Removed {len(plates)} plate(s) and their history.")
    return _redirect(return_url, "Choose an action for the selected plates.", "warning")


@router.post("/api/plates/save")
async def api_save_plates(request: Request, session: Session = Depends(get_db)) -> JSONResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Malformed request."}, status_code=400)
    values = [str(value) for value in (payload.get("plates") or [])]
    if not values:
        return JSONResponse({"error": "Select at least one plate."}, status_code=400)
    if len(values) > MAX_PREVIEW_COMBINATIONS:
        return JSONResponse({"error": "Too many plates in one request."}, status_code=400)
    added, existing, ids = _save_plates(session, values)
    if payload.get("favorite") is not None and ids:
        for plate in session.scalars(select(Plate).where(Plate.id.in_(list(ids.values())))).all():
            plate.favorite = bool(payload["favorite"])
        session.commit()
    return JSONResponse({"added": added, "existing": existing, "ids": ids})


# ---------------------------------------------------------------------------
# Explore: plate ideas, pattern builder, ready-made patterns
# ---------------------------------------------------------------------------

GENERATOR_MODES = ("ideas", "builder", "patterns")
PRESET_PATTERNS = (
    "single_letter_numbers",
    "number_letter",
    "prefix_number",
    "letter_number_letter",
    "repeated_digits",
    "mirrored_numbers",
    "sequential_numbers",
    "two_letters",
    "custom_template",
    "keyword_variations",
)


def _int_field(form: Any, name: str, default: int, label: str) -> int:
    value = str(form.get(name, "") or "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a whole number.") from exc


def _generation_kwargs(form: Any) -> tuple[str, dict[str, Any]]:
    pattern_type = str(form.get("pattern_type", ""))
    slots: Any = None
    if pattern_type == "pattern_builder":
        try:
            slots = json.loads(str(form.get("slots", "[]")) or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError("The pattern couldn't be read. Try rebuilding it.") from exc
    options = form.getlist("idea_options") if hasattr(form, "getlist") else form.get("idea_options", [])
    kwargs: dict[str, Any] = {
        "start": _int_field(form, "start", 0, "The first number"),
        "end": _int_field(form, "end", 9, "The last number"),
        "prefix": str(form.get("prefix", "")),
        "length": _int_field(form, "length", 4, "Length"),
        "template": str(form.get("template", "")),
        "word": str(form.get("word", "")),
        "keywords": str(form.get("keywords", "")),
        "substitutions": str(form.get("substitutions", "")) in {"1", "true", "on"},
        "max_length": settings.max_plate_length,
        "slots": slots,
        "idea_options": tuple(str(option) for option in options if str(option) in IDEA_OPTIONS),
        "seed": _int_field(form, "seed", 0, "Shuffle"),
    }
    return pattern_type, kwargs


def _known_plates(session: Session, candidates: list[str]) -> dict[str, dict[str, Any]]:
    wanted = set(candidates)
    rows = session.execute(
        select(
            Plate.id,
            Plate.normalized_plate,
            Plate.current_status,
            Plate.last_checked_at,
            Plate.favorite,
        )
    ).all()
    known: dict[str, dict[str, Any]] = {}
    for plate_id, name, status, checked, favorite in rows:
        if name in wanted:
            known[name] = {
                "id": plate_id,
                "status": status,
                "checked": _format_date(checked) if checked else None,
                "favorite": favorite,
            }
    return known


def _render_explore(request: Request, session: Session | None, **extra: Any) -> HTMLResponse:
    mode = extra.pop("mode", None) or request.query_params.get("mode", "ideas")
    if mode not in GENERATOR_MODES:
        mode = "ideas"
    form_values: dict[str, Any] = extra.pop("form_values", {})
    if not form_values and request.query_params.get("text"):
        form_values = {"word": request.query_params["text"]}
    generation = extra.get("generation")
    generation_json = None
    if generation is not None and session is not None:
        generation_json = {
            "candidates": generation.candidates,
            "known": _known_plates(session, generation.candidates),
            "rejected": generation.rejected[:200],
            "rejectedCount": len(generation.rejected),
            "duplicates": generation.duplicate_count,
            "generated": generation.total_before_validation,
        }
    return _page(
        request,
        "explore.html",
        mode=mode,
        form_values=form_values,
        idea_values=form_values.get("idea_options_list", ["similar", "shorter", "numbers"]),
        generation_json=generation_json,
        preset_patterns=PRESET_PATTERNS,
        **extra,
    )


@router.get("/explore", response_class=HTMLResponse)
@router.get("/generator", response_class=HTMLResponse)
def generator_page(request: Request) -> HTMLResponse:
    return _render_explore(request, None, generation=None)


@router.post("/explore/preview", response_class=HTMLResponse)
@router.post("/generator/preview", response_class=HTMLResponse)
async def generator_preview(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    form = await request.form()
    form_values: dict[str, Any] = {key: str(value) for key, value in form.items()}
    form_values["idea_options_list"] = [str(value) for value in form.getlist("idea_options")]
    pattern_type = form_values.get("pattern_type", "")
    mode = (
        "ideas" if pattern_type == "plate_ideas"
        else "builder" if pattern_type == "pattern_builder"
        else "patterns"
    )
    try:
        pattern_type, kwargs = _generation_kwargs(form)
        generation = generate_candidates(pattern_type, **kwargs)
        error = None
    except ValueError as exc:
        generation = None
        error = str(exc)
    return _render_explore(
        request,
        session,
        mode=mode,
        generation=generation,
        generator_error=error,
        form_values=form_values,
    )


@router.post("/api/generator/estimate")
async def generator_estimate(request: Request) -> JSONResponse:
    form = await request.form()
    try:
        pattern_type, kwargs = _generation_kwargs(form)
        return JSONResponse(estimate_generation(pattern_type, **kwargs))
    except ValueError as exc:
        return JSONResponse({"error": str(exc), "count": None, "examples": []})


@router.post("/generator/import")
async def import_generated(request: Request, session: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()
    selected = [str(value) for value in form.getlist("plates")]
    if len(selected) > 500 and form.get("confirm_large") != "yes":
        return _redirect("/explore", "Confirm saving more than 500 plates.", "error")
    added, _, _ = _save_plates(session, selected)
    return _redirect("/saved", f"Saved {added} new plate(s).")


# ---------------------------------------------------------------------------
# Checking runs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlateIdSelection:
    ids: list[int]
    invalid_values: list[str]
    missing_ids: list[int]


def _validate_plate_id_selection(session: Session, raw_values: list[str]) -> PlateIdSelection:
    ids: list[int] = []
    invalid_values: list[str] = []
    seen: set[int] = set()
    for raw_value in raw_values:
        value = raw_value.strip()
        if not value.isdigit() or int(value) < 1:
            invalid_values.append(raw_value)
            continue
        plate_id = int(value)
        if plate_id not in seen:
            ids.append(plate_id)
            seen.add(plate_id)
    existing = set(
        session.scalars(select(Plate.id).where(Plate.id.in_(ids))).all()
    ) if ids else set()
    return PlateIdSelection(
        ids=ids,
        invalid_values=invalid_values,
        missing_ids=[plate_id for plate_id in ids if plate_id not in existing],
    )




@router.post("/runs/start")
async def start_run(
    request: Request, session: Session = Depends(get_db)
) -> RedirectResponse:
    form = await request.form()
    raw_values = [str(value) for value in form.getlist("plate_ids")]
    return_url = _safe_return_url(str(form.get("return_url", "/saved")))
    selection = _validate_plate_id_selection(session, raw_values)
    if settings.development_mode:
        logger.info(
            "Run selection received=%d raw=%s accepted=%d ids=%s invalid=%s missing=%s",
            len(raw_values),
            raw_values,
            len(selection.ids) - len(selection.missing_ids),
            selection.ids,
            selection.invalid_values,
            selection.missing_ids,
        )
    if not raw_values:
        return _redirect(return_url, "Select at least one plate first.", "error")
    if selection.invalid_values or selection.missing_ids:
        return _redirect(
            return_url,
            "The selection contained an invalid or missing plate ID. Nothing was started.",
            "error",
        )
    plate_ids = selection.ids
    if not plate_ids:
        return _redirect(return_url, "Select at least one plate first.", "error")
    if len(plate_ids) > settings.max_plates_per_run:
        return _redirect(
            return_url,
            f"You selected {len(plate_ids)} plates; the configured maximum is "
            f"{settings.max_plates_per_run}.",
            "error",
        )
    if (
        len(plate_ids) > settings.large_run_confirmation_threshold
        and form.get("confirm_large") != "yes"
    ):
        return _redirect(
            return_url,
            f"Checking more than {settings.large_run_confirmation_threshold} plates needs confirmation.",
            "error",
        )
    try:
        run = run_manager.start(plate_ids)
        count = run.total_candidates
        return _redirect(
            return_url,
            f"Checking {count} plate{'s' if count != 1 else ''}. A browser window with the official "
            "FLHSMV site will open on this computer.",
        )
    except (RuntimeError, ValueError) as exc:
        return _redirect(return_url, str(exc), "error")


@router.post("/runs/stop")
async def stop_run(request: Request) -> RedirectResponse:
    form = await request.form()
    run = run_manager.stop()
    message = (
        "Stopping safely after the current step. Results so far are saved."
        if run
        else "There's no check in progress."
    )
    return _redirect(_safe_return_url(str(form.get("return_url", "/history")), "/history"), message, "warning")


@router.get("/api/runs/current")
def current_run(session: Session = Depends(get_db)) -> JSONResponse:
    run = session.scalar(
        select(CheckingRun)
        .where(CheckingRun.status.in_(ACTIVE_STATUSES))
        .order_by(CheckingRun.id.desc())
        .limit(1)
    )
    if run is None:
        run = session.scalar(select(CheckingRun).order_by(CheckingRun.id.desc()).limit(1))
    if run is None:
        return JSONResponse({"run": None})
    return JSONResponse({"run": RunProgress.model_validate(run).model_dump(mode="json")})


@router.get("/activity", response_class=HTMLResponse)
@router.get("/history", response_class=HTMLResponse)
def history(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    plate_id = request.query_params.get("plate_id")
    run_id = request.query_params.get("run_id")
    query = (
        select(CheckHistory)
        .options(selectinload(CheckHistory.plate), selectinload(CheckHistory.run))
        .order_by(CheckHistory.checked_at.desc())
    )
    selected_plate = None
    selected_run = None
    if plate_id and plate_id.isdigit():
        query = query.where(CheckHistory.plate_id == int(plate_id))
        selected_plate = session.get(Plate, int(plate_id))
    if run_id and run_id.isdigit():
        query = query.where(CheckHistory.run_id == int(run_id))
        selected_run = session.get(CheckingRun, int(run_id))
    entries = session.scalars(query.limit(500)).all()
    runs = session.scalars(select(CheckingRun).order_by(CheckingRun.id.desc()).limit(30)).all()
    return _page(
        request,
        "history.html",
        entries=entries,
        runs=runs,
        selected_plate=selected_plate,
        selected_run=selected_run,
        total_history=session.scalar(select(func.count(CheckHistory.id))) or 0,
    )


# ---------------------------------------------------------------------------
# Exports, backup, restore
# ---------------------------------------------------------------------------

PLATE_EXPORT_COLUMNS = (
    "plate",
    "current_status",
    "previous_status",
    "raw_result",
    "first_checked_at",
    "last_checked_at",
    "status_changed_at",
    "check_count",
    "favorite",
    "notes",
)


@router.get("/exports/plates.csv")
def export_plates(request: Request, session: Session = Depends(get_db)) -> Response:
    scope = request.query_params.get("scope", "all")
    query = _filtered_plate_query(request.query_params) if scope == "filtered" else select(Plate)
    if scope == "available":
        query = query.where(Plate.current_status == "Available")
    elif scope == "favorites":
        query = query.where(Plate.favorite.is_(True))
    elif scope == "changed":
        query = query.where(Plate.status_changed_at.is_not(None))
    plates = session.scalars(query.order_by(Plate.normalized_plate)).all()
    rows = [
        {
            "plate": plate.normalized_plate,
            "current_status": plate.current_status or "Never checked",
            "previous_status": plate.previous_status or "",
            "raw_result": plate.raw_result or "",
            "first_checked_at": plate.first_checked_at.isoformat() if plate.first_checked_at else "",
            "last_checked_at": plate.last_checked_at.isoformat() if plate.last_checked_at else "",
            "status_changed_at": plate.status_changed_at.isoformat() if plate.status_changed_at else "",
            "check_count": plate.check_count,
            "favorite": plate.favorite,
            "notes": plate.notes,
        }
        for plate in plates
    ]
    return Response(
        rows_to_csv(PLATE_EXPORT_COLUMNS, rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="florida-plates-{scope}.csv"'},
    )


@router.get("/exports/history.csv")
def export_history(session: Session = Depends(get_db)) -> Response:
    entries = session.scalars(
        select(CheckHistory)
        .options(selectinload(CheckHistory.plate))
        .order_by(CheckHistory.checked_at.desc())
    ).all()
    columns = ("plate", "status", "raw_result", "checked_at", "batch_number", "run_id")
    rows = [
        {
            "plate": entry.plate.normalized_plate,
            "status": entry.status,
            "raw_result": entry.raw_result,
            "checked_at": entry.checked_at.isoformat(),
            "batch_number": entry.batch_number,
            "run_id": entry.run_id or "",
        }
        for entry in entries
    ]
    return Response(
        rows_to_csv(columns, rows),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="florida-plate-history.csv"'},
    )


@router.get("/backup.json")
def download_backup(session: Session = Depends(get_db)) -> Response:
    stamp = datetime.now().strftime("%Y-%m-%d")
    return Response(
        json.dumps(build_backup(session), indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="florida-plates-backup-{stamp}.json"'},
    )


@router.post("/backup/restore")
async def restore(request: Request, session: Session = Depends(get_db)) -> Response:
    form = await request.form()
    upload = form.get("backup_file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return _redirect("/tools#backup", "Choose a backup file to restore.", "error")
    if run_manager.active_run(session) is not None:
        return _redirect("/tools#backup", "Wait for the current check to finish before restoring.", "error")
    raw = await upload.read(50 * 1024 * 1024 + 1)
    if len(raw) > 50 * 1024 * 1024:
        return _redirect("/tools#backup", "Backup file is larger than 50 MB.", "error")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
        summary = restore_backup(session, payload, settings.max_plate_length)
    except (UnicodeDecodeError, json.JSONDecodeError):
        session.rollback()
        return _redirect("/tools#backup", "That file isn't a valid backup (expected JSON).", "error")
    except ValueError as exc:
        session.rollback()
        return _redirect("/tools#backup", str(exc), "error")
    return _redirect(
        "/tools#backup",
        f"Restore complete: {summary['plates_added']} plates added, {summary['plates_updated']} updated, "
        f"{summary['history_added']} history records and {summary['runs_added']} runs added. "
        "Nothing was deleted.",
    )
