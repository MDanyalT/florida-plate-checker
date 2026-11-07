from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import routes
from app.checker_service import CheckerService, CheckResult, SafetyStop
from app.settings import SPEED_PROFILES, settings
from app.speed import (
    MIN_DELAY_FLOOR_SECONDS,
    current_speed_profile,
    save_speed_profile,
    saved_speed_profile,
    settings_for_run,
)


@pytest.fixture()
def config(tmp_path):
    return replace(settings, data_directory=tmp_path, debug_directory=tmp_path / "debug")


def test_saved_speed_overrides_env_timing(config) -> None:
    slow_env = replace(config, check_delay_min_seconds=9.0, check_delay_max_seconds=12.0)
    assert saved_speed_profile(slow_env) is None
    assert settings_for_run(slow_env).check_delay_min_seconds == 9.0

    save_speed_profile(slow_env, "faster")
    run_config = settings_for_run(slow_env)
    assert current_speed_profile(slow_env) == "faster"
    assert run_config.check_delay_min_seconds == float(SPEED_PROFILES["faster"]["delay_min"])
    assert run_config.check_delay_max_seconds == float(SPEED_PROFILES["faster"]["delay_max"])
    assert run_config.max_batch_size <= 5


def test_unknown_speed_is_rejected_and_corrupt_file_is_ignored(config) -> None:
    with pytest.raises(ValueError):
        save_speed_profile(config, "turbo")
    (config.data_directory / "preferences.json").write_text("{not json", encoding="utf-8")
    assert saved_speed_profile(config) is None
    assert current_speed_profile(config) == config.check_speed_profile


def test_safety_floors_apply_even_to_edited_env(config) -> None:
    reckless = replace(
        config,
        check_delay_min_seconds=0.0,
        check_delay_max_seconds=0.0,
        result_timeout_seconds=1.0,
        retry_delay_seconds=0.0,
        max_retries=0,
        max_batch_size=50,
    )
    safe = settings_for_run(reckless)
    assert safe.check_delay_min_seconds >= MIN_DELAY_FLOOR_SECONDS
    assert safe.check_delay_max_seconds >= safe.check_delay_min_seconds
    assert safe.result_timeout_seconds >= 15
    assert safe.max_retries >= 1
    assert safe.max_batch_size == 5


def test_speed_route_saves_choice(config, monkeypatch) -> None:
    monkeypatch.setattr(routes, "settings", config)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    ok = client.post("/settings/speed", data={"check_speed": "balanced"}, follow_redirects=False)
    assert ok.status_code == 303 and "kind=success" in ok.headers["location"]
    assert saved_speed_profile(config) == "balanced"
    bad = client.post("/settings/speed", data={"check_speed": "turbo"}, follow_redirects=False)
    assert "kind=error" in bad.headers["location"]
    assert saved_speed_profile(config) == "balanced"


def test_retry_or_captcha_slows_the_rest_of_the_run(config) -> None:
    save_speed_profile(config, "faster")
    service = CheckerService(settings_for_run(config))
    fast_low, fast_high = service._batch_delay_range()
    service.cautious = True
    slow_low, slow_high = service._batch_delay_range()
    assert fast_low < slow_low == float(SPEED_PROFILES["conservative"]["delay_min"])
    assert fast_high < slow_high == float(SPEED_PROFILES["conservative"]["delay_max"])


class FakeField:
    def __init__(self) -> None:
        self.value = "OLD"

    def fill(self, value, timeout=None) -> None:
        self.value = value


class FakeSubmit:
    def click(self, timeout=None) -> None:
        pass


class FakePage:
    url = settings.flhsmv_url

    def expect_navigation(self, **_kwargs):
        return nullcontext()


def make_service(config, fields):
    service = CheckerService(settings_for_run(config))
    calls = {"open": 0, "inspect": 0}

    def fake_open(page, on_state, on_metric=None):
        calls["open"] += 1
        return fields

    def fake_inspect(page, on_state, on_metric):
        calls["inspect"] += 1

    service._open_checker_with_retries = fake_open
    service._reusable_fields = lambda page, needed: fields if len(fields) >= needed else None
    service._find_submit = lambda page: FakeSubmit()
    service._inspect_page = fake_inspect
    service._wait_for_results = lambda page, batch: None
    service._extract_results = lambda page, batch, number: [
        CheckResult(plate=p, status="Available", raw_result="AVAILABLE", checked_at=None, batch_number=number)
        for p in batch
    ]
    return service, calls


def test_open_page_is_reused_between_batches_and_old_values_cleared(config) -> None:
    fields = [FakeField() for _ in range(5)]
    service, calls = make_service(config, fields)
    page = FakePage()

    service._submit_batch(page, ["AAA", "BBB", "CCC", "DDD", "EEE"], 1, None, None, force_reload=False)
    service._submit_batch(page, ["FFF", "GGG"], 2, None, None, force_reload=False)

    assert calls["open"] == 0
    assert [field.value for field in fields] == ["FFF", "GGG", "", "", ""]
    # Block/CAPTCHA inspection still runs after every submission.
    assert calls["inspect"] == 2


def test_retry_reloads_the_page(config) -> None:
    fields = [FakeField() for _ in range(5)]
    service, calls = make_service(config, fields)
    service._submit_batch(FakePage(), ["AAA"], 1, None, None, force_reload=True)
    assert calls["open"] == 1


def test_unusable_page_falls_back_to_reload(config) -> None:
    fields = [FakeField() for _ in range(5)]
    service, calls = make_service(config, fields)
    service._reusable_fields = lambda page, needed: None
    service._submit_batch(FakePage(), ["AAA"], 1, None, None, force_reload=False)
    assert calls["open"] == 1


def test_block_page_still_stops_and_captcha_still_waits_for_a_human(config, monkeypatch) -> None:
    service = CheckerService(settings_for_run(config))
    monkeypatch.setattr(service, "_page_text", lambda page: "access denied")
    with pytest.raises(SafetyStop):
        service._inspect_page(FakePage(), None, None)

    texts = iter(["please complete the captcha", "plate inquiry"])
    monkeypatch.setattr(service, "_page_text", lambda page: next(texts))
    prompts: list[str] = []
    monkeypatch.setattr("builtins.input", lambda message="": prompts.append(message) or "")
    states: list[str] = []
    service._inspect_page(FakePage(), states.append, None)
    assert prompts and states == ["captcha", "running"]
