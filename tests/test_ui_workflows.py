from datetime import datetime, timezone
from pathlib import Path
import re
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import routes
from app.models import CheckingRun, Plate


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class StubRunManager:
    def __init__(self, active=None) -> None:
        self.active = active
        self.started_ids: list[int] = []

    def active_run(self, _session: Session):
        return self.active

    def start(self, plate_ids: list[int]):
        self.started_ids = list(plate_ids)
        return SimpleNamespace(id=42)


def test_add_and_check_includes_new_and_waiting_but_skips_checked(
    db_session: Session, monkeypatch
) -> None:
    waiting = Plate(plate="BEACH7", normalized_plate="BEACH7")
    checked = Plate(
        plate="ROAD99",
        normalized_plate="ROAD99",
        last_checked_at=datetime.now(timezone.utc),
        current_status="Not available",
    )
    db_session.add_all([waiting, checked])
    db_session.commit()
    manager = StubRunManager()
    monkeypatch.setattr(routes, "run_manager", manager)

    response = routes._complete_plate_add(
        db_session,
        selected=["SUNSET", "BEACH7", "ROAD99", "SUNSET"],
        action="check_now",
        include_checked=False,
        confirm_large=True,
        source="manual",
    )

    stored = db_session.scalars(select(Plate).order_by(Plate.id)).all()
    sunset = next(plate for plate in stored if plate.normalized_plate == "SUNSET")
    assert manager.started_ids == [sunset.id, waiting.id]
    assert checked.id not in manager.started_ids
    assert len([plate for plate in stored if plate.normalized_plate == "SUNSET"]) == 1
    assert response.status_code == 303
    assert "Checking%20run%20%2342" in response.headers["location"]


def test_active_run_blocks_add_and_check_without_saving(db_session: Session, monkeypatch) -> None:
    manager = StubRunManager(active=SimpleNamespace(id=7))
    monkeypatch.setattr(routes, "run_manager", manager)

    response = routes._complete_plate_add(
        db_session,
        selected=["COAST1"],
        action="check_now",
        include_checked=False,
        confirm_large=True,
        source="manual",
    )

    assert db_session.scalar(select(Plate).where(Plate.normalized_plate == "COAST1")) is None
    assert "already%20active" in response.headers["location"]
    assert manager.started_ids == []


def test_add_to_library_saves_without_starting(db_session: Session, monkeypatch) -> None:
    manager = StubRunManager()
    monkeypatch.setattr(routes, "run_manager", manager)

    response = routes._complete_plate_add(
        db_session,
        selected=["BLUE42"],
        action="library",
        include_checked=False,
        confirm_large=False,
        source="manual",
    )

    assert db_session.scalar(select(Plate).where(Plate.normalized_plate == "BLUE42"))
    assert manager.started_ids == []
    assert response.headers["location"].startswith("/results?ids=")
    assert "not%20been%20checked" in response.headers["location"]


def test_dashboard_summary_reflects_completed_run(db_session: Session) -> None:
    db_session.add_all(
        [
            Plate(plate="SUNSET", normalized_plate="SUNSET", current_status="Available"),
            Plate(
                plate="ROAD99",
                normalized_plate="ROAD99",
                current_status="Not available",
            ),
            CheckingRun(
                status="completed",
                total_candidates=2,
                checked_count=2,
                available_count=1,
                unavailable_count=1,
            ),
        ]
    )
    db_session.commit()

    summary = routes._dashboard_summary(db_session)

    assert summary["stats"]["total"] == 2
    assert summary["stats"]["available"] == 1
    assert summary["latest_run"]["status"] == "completed"
    assert summary["latest_run"]["checked_count"] == 2


def test_ui_uses_check_recheck_and_manual_add_wording() -> None:
    dashboard = (PROJECT_ROOT / "templates" / "dashboard.html").read_text()
    library = (PROJECT_ROOT / "templates" / "results.html").read_text()
    script = (PROJECT_ROOT / "static" / "app.js").read_text()

    assert "Add and check now" in dashboard
    assert "Add to library" in dashboard
    assert "Review plate list" in dashboard
    assert "Import and check now" in dashboard
    assert "{{ 'Recheck' if plate.last_checked_at else 'Check' }}" in library
    assert "Check all {{ untested_count }} untested" in library
    assert "Saved locally and waiting to be checked" in library
    assert "checkedBefore === 0" in script
    assert "checkedBefore === selected.length" in script
    assert "Check selected plates" in script


def test_generator_shows_only_relevant_field_groups_and_neutral_defaults() -> None:
    generator = (PROJECT_ROOT / "templates" / "generator.html").read_text()
    styles = (PROJECT_ROOT / "static" / "styles.css").read_text()
    script = (PROJECT_ROOT / "static" / "app.js").read_text()

    assert generator.count('class="pattern-option"') == 10
    assert generator.count('class="pattern-option__content"') == 10
    assert generator.count('class="pattern-option__title"') == 10
    assert generator.count('class="pattern-option__description"') == 10
    assert generator.count('class="pattern-option__example"') == 10
    assert ".pattern-option.selected" in styles
    assert "grid-template-columns: auto minmax(0, 1fr) auto" in styles
    assert "radio.closest('.pattern-option')" in script
    assert 'data-for="prefix_number"' in generator
    assert 'data-for="custom_template"' in generator
    assert 'data-for="keyword_variations"' in generator
    assert "field.disabled = !visible" in script
    assert "SUNSET, BEACH, COAST, ROAD" in generator
    assert "Add and check selected" in generator
    assert "Add selected to library" in generator


def test_public_ui_contains_no_personal_placeholder_names() -> None:
    public_files = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "plates.example.txt",
        *sorted((PROJECT_ROOT / "templates").glob("*.html")),
    ]
    forbidden = ("DAN" + "YAL", "TA" + "RIQ", "R" + "HM", "T" + "AM")
    public_text = "\n".join(path.read_text() for path in public_files).upper()
    assert all(re.search(rf"\b{name}\b", public_text) is None for name in forbidden)


def test_terminal_run_refreshes_dashboard_and_library() -> None:
    script = (PROJECT_ROOT / "static" / "app.js").read_text()
    assert "/api/dashboard-summary" in script
    assert "wasActive && !isActive" in script
    assert "window.location.reload()" in script
    assert "refreshDashboardSummary" in script


def test_header_has_no_redundant_mobile_menu_toggle() -> None:
    base = (PROJECT_ROOT / "templates" / "base.html").read_text()
    styles = (PROJECT_ROOT / "static" / "styles.css").read_text()
    script = (PROJECT_ROOT / "static" / "app.js").read_text()

    assert "nav-toggle" not in base
    assert "data-nav-toggle" not in base
    assert "data-primary-nav" not in base
    assert "nav-toggle" not in styles
    assert "wireNavigation" not in script
    assert "data-nav-toggle" not in script
