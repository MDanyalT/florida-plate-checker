import time
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import routes
from app.checker_service import CheckResult
from app.database import get_db
from app.models import CheckingRun, Plate
from app.settings import PROJECT_ROOT


class FakeChecker:
    def run(self, candidates, *, on_batch_results=None, on_result=None, **_callbacks):
        results = [
            CheckResult(plate=plate, status="Available", raw_result="AVAILABLE",
                        checked_at=datetime.now(timezone.utc), batch_number=1)
            for plate in candidates
        ]
        if on_batch_results:
            on_batch_results(results)
        else:
            for result in results:
                on_result(result)
        return False


@pytest.fixture()
def client(session_factory, monkeypatch):
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")
    app.include_router(routes.router)

    def override():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(routes.run_manager, "session_factory", session_factory)
    monkeypatch.setattr(routes.run_manager, "service_factory", FakeChecker)
    return TestClient(app)


def wait_for_run(session_factory):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with session_factory() as session:
            run = session.scalar(select(CheckingRun).order_by(CheckingRun.id.desc()))
            if run and run.status not in ("queued", "running"):
                return run
        time.sleep(0.02)
    raise AssertionError("run did not finish")


PAGES = ["/", "/explore", "/explore?mode=builder", "/explore?mode=patterns", "/generator",
         "/saved", "/saved?view=list", "/results", "/saved?show=favorites", "/history", "/activity", "/tools"]


@pytest.mark.parametrize("url", PAGES)
def test_pages_render(client, url) -> None:
    response = client.get(url)
    assert response.status_code == 200
    assert "Florida Plate Finder" in response.text


def test_quick_check_validates_and_starts_one_run(client, session_factory) -> None:
    bad = client.post("/check", data={"plate": "TOO-LONG-1", "action": "check"})
    assert bad.status_code == 200 and 'aria-invalid="true"' in bad.text
    response = client.post("/check", data={"plate": " sunny ", "action": "check"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"].startswith("/plates/")
    run = wait_for_run(session_factory)
    assert run.status == "completed" and run.total_candidates == 1
    detail = client.get(response.headers["location"].split("?")[0])
    assert "Available when last checked" in detail.text


def test_save_api_lookup_and_bulk_actions(client, session_factory) -> None:
    saved = client.post("/api/plates/save", json={"plates": ["sun1", "SUN2", "bad!"], "favorite": True}).json()
    assert saved["added"] == 2 and set(saved["ids"]) == {"SUN1", "SUN2"}
    lookup = client.get("/api/plates/lookup?plate=sun1").json()
    assert lookup["saved"] and lookup["favorite"] and lookup["status"]["key"] == "unchecked"
    ids = list(saved["ids"].values())
    response = client.post("/plates/bulk", data={"bulk_action": "unfavorite", "plate_ids": ids})
    assert response.status_code == 200
    unconfirmed = client.post("/plates/bulk", data={"bulk_action": "delete", "plate_ids": ids}, follow_redirects=False)
    assert "confirmation" in unconfirmed.headers["location"]
    client.post("/plates/bulk", data={"bulk_action": "delete", "plate_ids": ids, "confirm_delete": "yes"})
    with session_factory() as session:
        assert session.scalar(select(Plate)) is None


def test_generation_preview_does_not_save_or_check(client, session_factory) -> None:
    response = client.post("/explore/preview", data={
        "pattern_type": "pattern_builder",
        "slots": '[{"kind":"fixed","value":"SUN"},{"kind":"digit"},{"kind":"digit"}]',
    })
    assert response.status_code == 200 and "SUN00" in response.text
    with session_factory() as session:
        assert session.scalar(select(Plate)) is None
        assert session.scalar(select(CheckingRun)) is None


def test_estimate_endpoint(client) -> None:
    data = client.post("/api/generator/estimate", data={"pattern_type": "prefix_number", "prefix": "SUN", "start": "0", "end": "99"}).json()
    assert data["count"] == 100 and data["examples"][0] == "SUN0"
    bad = client.post("/api/generator/estimate", data={"pattern_type": "prefix_number", "start": "x"}).json()
    assert bad["count"] is None and bad["error"]


def test_bulk_run_requires_confirmation_above_threshold(client, session_factory) -> None:
    threshold = routes.settings.large_run_confirmation_threshold
    plates = [f"T{n}" for n in range(threshold + 1)]
    ids = list(client.post("/api/plates/save", json={"plates": plates}).json()["ids"].values())
    response = client.post("/runs/start", data={"plate_ids": ids, "return_url": "/saved"}, follow_redirects=False)
    assert "kind=error" in response.headers["location"]
    with session_factory() as session:
        assert session.scalar(select(CheckingRun)) is None
    confirmed = client.post("/runs/start", data={"plate_ids": ids, "confirm_large": "yes"}, follow_redirects=False)
    assert "kind=success" in confirmed.headers["location"]
    assert wait_for_run(session_factory).checked_count == threshold + 1


def test_backup_download_and_restore(client) -> None:
    client.post("/api/plates/save", json={"plates": ["BEACH"], "favorite": True})
    backup = client.get("/backup.json")
    assert backup.status_code == 200 and backup.json()["counts"]["plates"] == 1
    restored = client.post("/backup/restore", files={"backup_file": ("b.json", backup.content, "application/json")}, follow_redirects=False)
    assert "Restore%20complete" in restored.headers["location"]
    bad = client.post("/backup/restore", files={"backup_file": ("b.json", b"nope", "application/json")}, follow_redirects=False)
    assert "kind=error" in bad.headers["location"]


def test_exports_still_work(client) -> None:
    client.post("/api/plates/save", json={"plates": ["PALM"]})
    for url in ["/exports/plates.csv?scope=all", "/exports/plates.csv?scope=filtered&show=unchecked", "/exports/history.csv"]:
        response = client.get(url)
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert "PALM" in client.get("/exports/plates.csv?scope=filtered&show=unchecked").text
