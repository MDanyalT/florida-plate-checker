from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app import routes
from app.database import get_db
from app.models import Plate


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class StubRunManager:
    def __init__(self) -> None:
        self.started_ids: list[int] = []
        self.active_plate_ids: set[int] = set()

    def active_run(self, _session):
        return None

    def start(self, plate_ids: list[int]):
        self.started_ids = list(plate_ids)
        return SimpleNamespace(id=77, total_candidates=len(plate_ids))


@pytest.fixture()
def selection_client(session_factory: sessionmaker[Session], monkeypatch):
    application = FastAPI()
    application.mount(
        "/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static"
    )
    application.include_router(routes.router)

    def override_db():
        with session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    manager = StubRunManager()
    monkeypatch.setattr(routes, "run_manager", manager)
    return TestClient(application), manager


def add_plates(session_factory: sessionmaker[Session], count: int) -> list[Plate]:
    with session_factory() as session:
        plates = [
            Plate(plate=f"TEST{i:03d}", normalized_plate=f"TEST{i:03d}")
            for i in range(count)
        ]
        session.add_all(plates)
        session.commit()
        return plates


def test_selecting_one_row_submits_that_record(
    selection_client, session_factory: sessionmaker[Session]
) -> None:
    client, manager = selection_client
    plate = add_plates(session_factory, 1)[0]
    response = client.post(
        "/runs/start", data={"plate_ids": str(plate.id)}, follow_redirects=False
    )
    assert response.status_code == 303
    assert manager.started_ids == [plate.id]


def test_multiple_and_duplicate_ids_are_deduplicated_in_order(
    selection_client, session_factory: sessionmaker[Session]
) -> None:
    client, manager = selection_client
    plates = add_plates(session_factory, 3)
    response = client.post(
        "/runs/start",
        data={"plate_ids": [str(plates[1].id), str(plates[0].id), str(plates[1].id)]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert manager.started_ids == [plates[1].id, plates[0].id]


def test_no_selection_is_rejected_without_starting(selection_client) -> None:
    client, manager = selection_client
    response = client.post("/runs/start", data={}, follow_redirects=False)
    assert response.status_code == 303
    assert "Select%20at%20least%20one%20plate%20first" in response.headers["location"]
    assert manager.started_ids == []


@pytest.mark.parametrize("bad_value", ["missing", "0", "-2", "999999"])
def test_invalid_or_missing_record_ids_reject_the_whole_selection(
    selection_client, session_factory: sessionmaker[Session], bad_value: str
) -> None:
    client, manager = selection_client
    plate = add_plates(session_factory, 1)[0]
    response = client.post(
        "/runs/start",
        data={"plate_ids": [str(plate.id), bad_value]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "invalid%20or%20missing" in response.headers["location"]
    assert manager.started_ids == []


def test_never_checked_and_previously_checked_records_are_both_accepted(
    selection_client, session_factory: sessionmaker[Session]
) -> None:
    client, manager = selection_client
    with session_factory() as session:
        waiting = Plate(plate="WAITING", normalized_plate="WAITING")
        checked = Plate(
            plate="CHECKED",
            normalized_plate="CHECKED",
            last_checked_at=datetime.now(timezone.utc),
            current_status="Not available",
        )
        session.add_all([waiting, checked])
        session.commit()
        ids = [waiting.id, checked.id]
    response = client.post(
        "/runs/start", data={"plate_ids": [str(value) for value in ids]}, follow_redirects=False
    )
    assert response.status_code == 303
    assert manager.started_ids == ids


def test_configured_limit_is_enforced_without_truncation(
    selection_client, session_factory: sessionmaker[Session], monkeypatch
) -> None:
    client, manager = selection_client
    plates = add_plates(session_factory, 2)
    monkeypatch.setattr(routes, "settings", replace(routes.settings, max_plates_per_run=1))
    response = client.post(
        "/runs/start",
        data={"plate_ids": [str(plate.id) for plate in plates]},
        follow_redirects=False,
    )
    assert "selected%202%20plates" in response.headers["location"]
    assert "maximum%20is%201" in response.headers["location"]
    assert manager.started_ids == []


def test_filtered_paginated_results_expose_only_visible_database_ids(
    selection_client, session_factory: sessionmaker[Session]
) -> None:
    client, _manager = selection_client
    add_plates(session_factory, 30)
    response = client.get("/results?q=TEST&page=2&sort=plate&direction=asc")
    visible_ids = re.findall(r'name="plate_ids" value="(\d+)" form="bulk-form"', response.text)
    assert response.status_code == 200
    assert len(visible_ids) == 6  # 30 plates, 24 cards per page
    assert len(set(visible_ids)) == 6
    assert "Page 2 of 2" in response.text
