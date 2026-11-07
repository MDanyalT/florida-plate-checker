"""Reusable conservative Playwright service for the official FLHSMV form."""

from __future__ import annotations

import random
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import (
    Browser,
    Error as PlaywrightError,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from app.settings import Settings, settings


MetricCallback = Callable[[str, float], None]


FIELD_SELECTOR = "#inquiry input.inputText[type='text']"
FIELD_FALLBACK_SELECTOR = "#inquiry input[type='text'][aria-label^='Plate configuration']"
SUBMIT_SELECTOR = "#MainContent_btnSubmit"
SUBMIT_FALLBACK_SELECTOR = "input[type='submit'][value='Submit']"
RESULT_ROW_SELECTOR = "#inquiry tr"

CAPTCHA_TERMS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "human verification",
    "security check",
)
BLOCKING_TERMS = (
    "access denied",
    "rate limit",
    "too many requests",
    "request blocked",
    "service unavailable",
    "site maintenance",
    "under maintenance",
    "temporarily unavailable",
)


class PageStructureError(RuntimeError):
    pass


class ResultExtractionError(RuntimeError):
    pass


class TransientCheckError(RuntimeError):
    pass


class SafetyStop(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckResult:
    plate: str
    status: str
    raw_result: str
    checked_at: datetime
    batch_number: int


def classify_status(raw_result: str) -> str:
    normalized = " ".join(raw_result.upper().split())
    if any(phrase in normalized for phrase in ("NOT AVAILABLE", "UNAVAILABLE", "NOT ELIGIBLE")):
        return "Not available"
    if any(phrase in normalized for phrase in ("INVALID", "NOT VALID", "REJECTED")):
        return "Invalid"
    if any(phrase in normalized for phrase in ("ERROR", "FAILED", "UNABLE TO")):
        return "Error"
    if "AVAILABLE" in normalized:
        return "Available"
    return "Unknown"


class CheckerService:
    """Runs one serial, visible-browser checking session."""

    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    def run(
        self,
        candidates: Sequence[str],
        *,
        on_result: Callable[[CheckResult], None] | None = None,
        on_batch_results: Callable[[Sequence[CheckResult]], None] | None = None,
        on_batch: Callable[[int, Sequence[str]], None] | None = None,
        on_state: Callable[[str], None] | None = None,
        on_metric: MetricCallback | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> bool:
        """Check candidates and return True when stopped before completion."""

        if on_result is None and on_batch_results is None:
            raise ValueError("A result callback is required.")
        should_stop = should_stop or (lambda: False)
        with sync_playwright() as playwright:
            browser: Browser | None = None
            try:
                try:
                    browser = playwright.chromium.launch(headless=self.config.headless)
                except PlaywrightError as exc:
                    first_line = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
                    raise RuntimeError(
                        "Could not start Playwright Chromium. Run `python -m playwright install chromium` "
                        f"in the same environment. Details: {first_line}"
                    ) from exc
                page = browser.new_page()
                fields = self._open_checker_with_retries(page, on_state, on_metric)
                batch_size = min(len(fields), self.config.max_batch_size, 5)
                if batch_size < 1:
                    raise PageStructureError("No usable personalized-plate fields were detected.")
                live_limit = self._configured_field_limit(fields)
                over_limit = [plate for plate in candidates if len(plate) > live_limit]
                if over_limit:
                    raise PageStructureError(
                        f"The live form maxlength is {live_limit}; cannot submit: {', '.join(over_limit)}"
                    )

                total_batches = (len(candidates) + batch_size - 1) // batch_size
                for batch_number, start in enumerate(range(0, len(candidates), batch_size), 1):
                    if should_stop():
                        return True
                    batch = list(candidates[start : start + batch_size])
                    if on_batch:
                        on_batch(batch_number, batch)
                    results = self._check_batch_with_retries(
                        page, batch, batch_number, on_state, on_metric
                    )
                    if on_batch_results:
                        on_batch_results(results)
                    elif on_result:
                        for result in results:
                            on_result(result)
                    if on_metric:
                        on_metric("batch_completed", 1.0)
                    if batch_number < total_batches:
                        delay = random.uniform(
                            self.config.min_delay_seconds, self.config.max_delay_seconds
                        )
                        deadline = time.monotonic() + delay
                        while time.monotonic() < deadline:
                            if should_stop():
                                return True
                            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
                return False
            finally:
                if browser is not None:
                    browser.close()

    def _check_batch_with_retries(
        self,
        page: Page,
        batch: Sequence[str],
        batch_number: int,
        on_state: Callable[[str], None] | None,
        on_metric: MetricCallback | None,
    ) -> list[CheckResult]:
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                return self._submit_batch(
                    page,
                    batch,
                    batch_number,
                    on_state,
                    on_metric,
                    force_reload=attempt > 1,
                )
            except (TransientCheckError, ResultExtractionError) as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    if on_metric:
                        on_metric("retry", 1.0)
                    time.sleep(self.config.retry_delay_seconds)
        raise RuntimeError(
            f"Batch {batch_number} failed after {self.config.max_retries} attempts: {last_error}"
        )

    def _page_text(self, page: Page) -> str:
        try:
            return page.locator("body").inner_text(timeout=5_000).lower()
        except PlaywrightTimeoutError:
            return ""

    def _detect_safety_page(self, page: Page) -> None:
        text = self._page_text(page)
        for term in BLOCKING_TERMS:
            if term in text:
                raise SafetyStop(f"FLHSMV displayed '{term}'. The run was stopped safely.")

    def _handle_captcha(
        self,
        page: Page,
        on_state: Callable[[str], None] | None,
        on_metric: MetricCallback | None = None,
    ) -> None:
        text = self._page_text(page)
        if any(term in text for term in CAPTCHA_TERMS):
            if on_state:
                on_state("captcha")
            print("\nCAPTCHA or human verification detected.")
            print("Complete it manually in the visible browser. This application will not solve it.")
            pause_started = time.monotonic()
            input("Press Enter here when the FLHSMV checker is ready...")
            if on_metric:
                on_metric("captcha_pause", time.monotonic() - pause_started)
            self._detect_safety_page(page)
            if on_state:
                on_state("running")

    def _save_debug(self, page: Page, reason: str) -> tuple[Path | None, Path | None]:
        self.config.debug_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_reason = re.sub(r"[^A-Za-z0-9_-]+", "_", reason)[:50]
        screenshot = self.config.debug_directory / f"{stamp}_{safe_reason}.png"
        html = self.config.debug_directory / f"{stamp}_{safe_reason}.html"
        screenshot_result: Path | None = screenshot
        html_result: Path | None = html
        try:
            page.screenshot(path=str(screenshot), full_page=True)
        except Exception as exc:
            print(f"Could not save debug screenshot: {exc}", file=sys.stderr)
            screenshot_result = None
        try:
            html.write_text(page.content(), encoding="utf-8")
        except Exception as exc:
            print(f"Could not save debug HTML: {exc}", file=sys.stderr)
            html_result = None
        return screenshot_result, html_result

    def _find_fields(self, page: Page) -> list[Locator]:
        fields = page.locator(FIELD_SELECTOR).all()
        if not fields:
            fields = page.locator(FIELD_FALLBACK_SELECTOR).all()
        if not fields:
            screenshot, html = self._save_debug(page, "no_input_fields")
            raise PageStructureError(
                f"No plate fields detected. Debug screenshot: {screenshot}; HTML: {html}"
            )
        return fields

    def _find_submit(self, page: Page) -> Locator:
        submit = page.locator(SUBMIT_SELECTOR)
        if submit.count() != 1:
            submit = page.locator(SUBMIT_FALLBACK_SELECTOR)
        if submit.count() != 1:
            screenshot, html = self._save_debug(page, "submit_missing")
            raise PageStructureError(
                f"Submit button not uniquely detected. Debug screenshot: {screenshot}; HTML: {html}"
            )
        return submit

    def _configured_field_limit(self, fields: Sequence[Locator]) -> int:
        limits: list[int] = []
        for field in fields:
            value = field.get_attribute("maxlength")
            if value and value.isdigit() and int(value) > 0:
                limits.append(int(value))
        return min(limits, default=self.config.max_plate_length)

    def _open_checker_with_retries(
        self,
        page: Page,
        on_state: Callable[[str], None] | None,
        on_metric: MetricCallback | None = None,
    ) -> list[Locator]:
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                page.goto(
                    self.config.flhsmv_url,
                    wait_until="domcontentloaded",
                    timeout=self.config.navigation_timeout_ms,
                )
                page.locator("#inquiry").wait_for(
                    state="visible", timeout=self.config.navigation_timeout_ms
                )
                self._handle_captcha(page, on_state, on_metric)
                self._detect_safety_page(page)
                return self._find_fields(page)
            except SafetyStop:
                raise
            except PageStructureError:
                raise
            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    if on_metric:
                        on_metric("retry", 1.0)
                    time.sleep(self.config.retry_delay_seconds)
        raise RuntimeError(
            f"Could not open the checker after {self.config.max_retries} attempts: {last_error}"
        )

    def _submit_batch(
        self,
        page: Page,
        batch: Sequence[str],
        batch_number: int,
        on_state: Callable[[str], None] | None,
        on_metric: MetricCallback | None,
        *,
        force_reload: bool,
    ) -> list[CheckResult]:
        if force_reload:
            fields = self._open_checker_with_retries(page, on_state, on_metric)
        else:
            try:
                self._detect_safety_page(page)
                self._handle_captcha(page, on_state, on_metric)
                fields = self._find_fields(page)
                self._find_submit(page)
            except PageStructureError:
                fields = self._open_checker_with_retries(page, on_state, on_metric)
        usable_count = min(len(fields), self.config.max_batch_size, 5)
        if len(batch) > usable_count:
            raise PageStructureError(
                f"The live page now has {usable_count} fields for a {len(batch)}-plate batch."
            )
        for field in fields[:usable_count]:
            field.fill("", timeout=self.config.navigation_timeout_ms)
        for field, plate in zip(fields[: len(batch)], batch, strict=True):
            field.fill(plate, timeout=self.config.navigation_timeout_ms)
        submit = self._find_submit(page)
        try:
            with page.expect_navigation(
                wait_until="domcontentloaded", timeout=self.config.navigation_timeout_ms
            ):
                submit.click(timeout=self.config.navigation_timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise TransientCheckError("Submission navigation timed out.") from exc

        self._handle_captcha(page, on_state, on_metric)
        self._detect_safety_page(page)
        self._wait_for_results(page, batch)
        return self._extract_results(page, batch, batch_number)

    def _wait_for_results(self, page: Page, submitted: Sequence[str]) -> None:
        try:
            page.wait_for_function(
                """
                (expected) => {
                  const rows = [...document.querySelectorAll('#inquiry tr')];
                  return expected.every((plate) => rows.some((row) => {
                    const input = row.querySelector("input[type='text']");
                    const output = row.querySelector('span.outputText');
                    return input && output && input.value.trim().toUpperCase() === plate
                      && output.textContent.trim().length > 0;
                  }));
                }
                """,
                arg=list(submitted),
                timeout=int(self.config.result_timeout_seconds * 1000),
            )
        except PlaywrightTimeoutError as exc:
            screenshot, html = self._save_debug(page, "result_timeout")
            raise ResultExtractionError(
                f"Result pairing timed out. Debug screenshot: {screenshot}; HTML: {html}"
            ) from exc

    def _extract_results(
        self, page: Page, submitted: Sequence[str], batch_number: int
    ) -> list[CheckResult]:
        row_data = page.locator(RESULT_ROW_SELECTOR).evaluate_all(
            """
            (rows) => rows.map((row) => {
              const input = row.querySelector("input[type='text']");
              const output = row.querySelector('span.outputText');
              if (!input || !output) return null;
              return {
                plate: input.value.trim().toUpperCase(),
                raw_result: output.textContent.trim()
              };
            }).filter(Boolean)
            """
        )
        by_plate = {item["plate"]: item["raw_result"] for item in row_data if item["plate"]}
        missing = [plate for plate in submitted if not by_plate.get(plate)]
        if missing:
            screenshot, html = self._save_debug(page, "result_association")
            raise ResultExtractionError(
                f"Could not associate results for {', '.join(missing)}. "
                f"Debug screenshot: {screenshot}; HTML: {html}"
            )
        checked_at = datetime.now(timezone.utc)
        return [
            CheckResult(
                plate=plate,
                status=classify_status(by_plate[plate]),
                raw_result=by_plate[plate],
                checked_at=checked_at,
                batch_number=batch_number,
            )
            for plate in submitted
        ]
