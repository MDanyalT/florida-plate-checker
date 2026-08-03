"""FastAPI HTML, import, export, and polling routes."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload
from starlette.datastructures import UploadFile

from app.checker_service import CheckerService
from app.database import SessionLocal, get_db
from app.exporter import rows_to_csv
from app.generator import generate_candidates
from app.importer import inspect_csv, parse_text_content
from app.models import CheckHistory, CheckingRun, Plate
from app.plate_utils import analyze_candidates
from app.run_manager import ACTIVE_STATUSES, RunManager
from app.schemas import RunProgress
from app.settings import PROJECT_ROOT, settings


router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
run_manager = RunManager(SessionLocal, lambda: CheckerService(settings))


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%b %d, %Y · %I:%M %p")


templates.env.filters["datetime"] = _format_datetime


def _redirect(path: str, message: str, kind: str = "success") -> RedirectResponse:
    separator = "&" if "?" in path else "?"
    return RedirectResponse(
        f"{path}{separator}message={quote(message)}&kind={quote(kind)}",
        status_code=303,
    )


def _safe_return_url(value: str | None, default: str = "/results") -> str:
    return value if value and value.startswith("/") and not value.startswith("//") else default


def _dashboard_context(session: Session, request: Request, **extra: Any) -> dict[str, Any]:
    status_counts = dict(
        session.execute(
            select(Plate.current_status, func.count(Plate.id)).group_by(Plate.current_status)
        ).all()
    )
    today_start = datetime.combine(date.today(), time.min).replace(tzinfo=timezone.utc)
    latest_run = session.scalar(select(CheckingRun).order_by(CheckingRun.id.desc()).limit(1))
    recent_changes = session.scalars(
        select(Plate)
        .where(Plate.status_changed_at.is_not(None))
        .order_by(Plate.status_changed_at.desc())
        .limit(8)
    ).all()
    recent_plates = session.scalars(select(Plate).order_by(Plate.created_at.desc()).limit(8)).all()
    context: dict[str, Any] = {
        "request": request,
        "message": request.query_params.get("message"),
        "message_kind": request.query_params.get("kind", "success"),
        "stats": {
            "total": session.scalar(select(func.count(Plate.id))) or 0,
            "available": status_counts.get("Available", 0),
            "unavailable": status_counts.get("Not available", 0),
            "invalid": status_counts.get("Invalid", 0),
            "unknown": status_counts.get("Unknown", 0),
            "error": status_counts.get("Error", 0),
            "favorites": session.scalar(
                select(func.count(Plate.id)).where(Plate.favorite.is_(True))
            )
            or 0,
            "today": session.scalar(
                select(func.count(Plate.id)).where(Plate.last_checked_at >= today_start)
            )
            or 0,
        },
        "latest_run": latest_run,
        "recent_changes": recent_changes,
        "recent_plates": recent_plates,
        "max_plate_length": settings.max_plate_length,
        "max_upload_bytes": settings.max_upload_bytes,
        "large_run_threshold": settings.large_run_confirmation_threshold,
    }
    context.update(extra)
    return context


def _render_dashboard(session: Session, request: Request, **extra: Any) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=_dashboard_context(session, request, **extra),
    )


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    return _render_dashboard(session, request)


@router.post("/imports/manual/preview", response_class=HTMLResponse)
async def preview_manual_import(
    request: Request, session: Session = Depends(get_db)
) -> HTMLResponse:
    form = await request.form()
    text = str(form.get("plates_text", ""))
    report = analyze_candidates(text.splitlines(), settings.max_plate_length)
    return _render_dashboard(session, request, import_report=report, import_source="manual")


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
        return _render_dashboard(session, request, import_report=report, import_source=upload.filename)

    try:
        inspection = inspect_csv(content)
    except ValueError as exc:
        return _render_dashboard(session, request, upload_error=str(exc))
    if inspection.selected_column:
        report = analyze_candidates(inspection.values, settings.max_plate_length)
        return _render_dashboard(session, request, import_report=report, import_source=upload.filename)
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
        return _render_dashboard(session, request, import_report=report, import_source=filename)
    except ValueError as exc:
        return _render_dashboard(session, request, upload_error=str(exc))


@router.post("/imports/confirm")
async def confirm_import(request: Request, session: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()
    selected = [str(value) for value in form.getlist("plates")]
    report = analyze_candidates(selected, settings.max_plate_length)
    existing = set(
        session.scalars(
            select(Plate.normalized_plate).where(Plate.normalized_plate.in_(report.valid))
        ).all()
    )
    added = 0
    for normalized in report.valid:
        if normalized in existing:
            continue
        session.add(Plate(plate=normalized, normalized_plate=normalized))
        added += 1
    session.commit()
    skipped = len(report.valid) - added
    return _redirect("/results", f"Imported {added} plate(s); skipped {skipped} already stored.")


def _filtered_plate_query(params: Any) -> Select[tuple[Plate]]:
    query = select(Plate)
    search = str(params.get("q", "")).strip().upper()
    if search:
        query = query.where(Plate.normalized_plate.contains(search))
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
    date_from = str(params.get("date_from", ""))
    date_to = str(params.get("date_to", ""))
    if date_from:
        query = query.where(Plate.last_checked_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.where(
            Plate.last_checked_at < datetime.combine(date.fromisoformat(date_to), time.max)
        )
    return query


@router.get("/results", response_class=HTMLResponse)
def results(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    query = _filtered_plate_query(request.query_params)
    sort_name = request.query_params.get("sort", "updated")
    direction = request.query_params.get("direction", "desc")
    sort_columns = {
        "plate": Plate.normalized_plate,
        "status": Plate.current_status,
        "checked": Plate.last_checked_at,
        "changed": Plate.status_changed_at,
        "count": Plate.check_count,
        "updated": Plate.updated_at,
    }
    sort_column = sort_columns.get(sort_name, Plate.updated_at)
    query = query.order_by(sort_column.asc() if direction == "asc" else sort_column.desc())
    page = max(1, int(request.query_params.get("page", "1") or 1))
    per_page = 25
    count_query = select(func.count()).select_from(_filtered_plate_query(request.query_params).subquery())
    total = session.scalar(count_query) or 0
    plates = session.scalars(query.offset((page - 1) * per_page).limit(per_page)).all()
    query_dict = dict(request.query_params)
    query_dict.pop("page", None)
    pagination_query = urlencode(query_dict)
    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={
            "request": request,
            "plates": plates,
            "total": total,
            "page": page,
            "pages": max(1, (total + per_page - 1) // per_page),
            "pagination_query": pagination_query,
            "message": request.query_params.get("message"),
            "message_kind": request.query_params.get("kind", "success"),
            "statuses": ["Available", "Not available", "Invalid", "Unknown", "Error", "Never checked"],
            "max_plate_length": settings.max_plate_length,
            "large_run_threshold": settings.large_run_confirmation_threshold,
        },
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
    return RedirectResponse(_safe_return_url(str(form.get("return_url", "/results"))), status_code=303)


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
        _safe_return_url(str(form.get("return_url", "/results"))), "Notes saved."
    )


@router.post("/plates/{plate_id}/delete")
async def delete_plate(
    plate_id: int, request: Request, session: Session = Depends(get_db)
) -> RedirectResponse:
    plate = session.get(Plate, plate_id)
    if plate:
        session.delete(plate)
        session.commit()
    form = await request.form()
    return _redirect(
        _safe_return_url(str(form.get("return_url", "/results"))), "Plate deleted locally."
    )


@router.get("/generator", response_class=HTMLResponse)
def generator_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="generator.html",
        context={
            "request": request,
            "generation": None,
            "form_values": {},
            "max_plate_length": settings.max_plate_length,
        },
    )


@router.post("/generator/preview", response_class=HTMLResponse)
async def generator_preview(request: Request) -> HTMLResponse:
    form = await request.form()
    form_values = {key: str(value) for key, value in form.items()}
    try:
        generation = generate_candidates(
            str(form.get("pattern_type", "")),
            start=int(str(form.get("start", "0")) or 0),
            end=int(str(form.get("end", "9")) or 9),
            prefix=str(form.get("prefix", "")),
            length=int(str(form.get("length", "4")) or 4),
            template=str(form.get("template", "")),
            word=str(form.get("word", "")),
            keywords=str(form.get("keywords", "")),
            substitutions=form.get("substitutions") == "1",
            max_length=settings.max_plate_length,
        )
        error = None
    except ValueError as exc:
        generation = None
        error = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="generator.html",
        context={
            "request": request,
            "generation": generation,
            "generator_error": error,
            "form_values": form_values,
            "max_plate_length": settings.max_plate_length,
        },
    )


@router.post("/generator/import")
async def import_generated(request: Request, session: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()
    selected = [str(value) for value in form.getlist("plates")]
    if len(selected) > 500 and form.get("confirm_large") != "yes":
        return _redirect("/generator", "Confirm imports larger than 500 plates.", "error")
    report = analyze_candidates(selected, settings.max_plate_length)
    existing = set(
        session.scalars(
            select(Plate.normalized_plate).where(Plate.normalized_plate.in_(report.valid))
        ).all()
    )
    for normalized in report.valid:
        if normalized not in existing:
            session.add(Plate(plate=normalized, normalized_plate=normalized))
    session.commit()
    return _redirect(
        "/results", f"Imported {len(report.valid) - len(existing)} generated plate(s)."
    )


@router.post("/runs/start")
async def start_run(request: Request) -> RedirectResponse:
    form = await request.form()
    try:
        plate_ids = [int(value) for value in form.getlist("plate_ids")]
    except ValueError:
        return _redirect("/results", "Invalid plate selection.", "error")
    if len(plate_ids) > settings.max_candidates_per_run:
        return _redirect(
            "/results",
            f"A run may contain at most {settings.max_candidates_per_run} plates.",
            "error",
        )
    if (
        len(plate_ids) > settings.large_run_confirmation_threshold
        and form.get("confirm_large") != "yes"
    ):
        return _redirect(
            "/results",
            f"Runs above {settings.large_run_confirmation_threshold} plates require confirmation.",
            "error",
        )
    try:
        run = run_manager.start(plate_ids)
        return _redirect("/", f"Checking run #{run.id} started in visible Chromium.")
    except (RuntimeError, ValueError) as exc:
        return _redirect("/results", str(exc), "error")


@router.post("/runs/stop")
def stop_run() -> RedirectResponse:
    run = run_manager.stop()
    message = f"Stop requested for run #{run.id}." if run else "No active run to stop."
    return _redirect("/", message, "warning")


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


@router.get("/history", response_class=HTMLResponse)
def history(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    plate_id = request.query_params.get("plate_id")
    query = (
        select(CheckHistory)
        .options(selectinload(CheckHistory.plate), selectinload(CheckHistory.run))
        .order_by(CheckHistory.checked_at.desc())
    )
    selected_plate = None
    if plate_id and plate_id.isdigit():
        query = query.where(CheckHistory.plate_id == int(plate_id))
        selected_plate = session.get(Plate, int(plate_id))
    entries = session.scalars(query.limit(500)).all()
    runs = session.scalars(select(CheckingRun).order_by(CheckingRun.id.desc()).limit(30)).all()
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "request": request,
            "entries": entries,
            "runs": runs,
            "selected_plate": selected_plate,
        },
    )


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
