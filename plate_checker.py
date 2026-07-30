#!/usr/bin/env python3
"""Conservative Playwright automation for the FLHSMV personalized plate checker.

This script uses a visible Chromium browser and the FLHSMV web form only. It
does not make direct HTTP requests to the site.
"""

from __future__ import annotations

import csv
import os
import random
import re
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from playwright.sync_api import (
    Browser,
    Locator,
    Page,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


# ------------------------------ Configuration -----------------------------

URL: Final = "https://services.flhsmv.gov/MVCheckPersonalPlate/PlateInquiryView.aspx"
INPUT_FILENAME: Final = "plates.txt"
OUTPUT_FILENAME: Final = "plate_results.csv"
CHECKED_FILENAME: Final = "checked_plates.txt"
HEADLESS: Final = False
MIN_DELAY_SECONDS: Final = 5.0
MAX_DELAY_SECONDS: Final = 10.0
NAVIGATION_TIMEOUT_MS: Final = 45_000
MAX_RETRIES: Final = 3
MAX_BATCH_SIZE: Final = 5

# The live page inspected on 2026-07-30 has maxlength="7" on every input.
# This value is checked again at runtime against the form's actual maxlength.
MAX_PLATE_LENGTH: Final = 7

DEBUG_DIRECTORY: Final = Path("plate_checker_debug")


# Verified on the live page. The aria-label fallback protects against a minor
# class-name change while still selecting the intended visible text inputs.
FIELD_SELECTOR: Final = "#inquiry input.inputText[type='text']"
FIELD_FALLBACK_SELECTOR: Final = "#inquiry input[type='text'][aria-label^='Plate configuration']"
SUBMIT_SELECTOR: Final = "#MainContent_btnSubmit"
SUBMIT_FALLBACK_SELECTOR: Final = "input[type='submit'][value='Submit']"
RESULT_ROW_SELECTOR: Final = "#inquiry tr"

ALLOWED_CANDIDATE: Final = re.compile(r"^[A-Z0-9 -]+$")
COMPLETED_STATUSES: Final = frozenset({"Available", "Not available", "Invalid", "Unknown"})
CSV_COLUMNS: Final = ("plate", "status", "raw_result", "checked_at", "batch_number")

CAPTCHA_TERMS: Final = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "human verification",
    "security check",
)
BLOCKING_TERMS: Final = (
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
    """Raised when the page no longer has the expected checker controls."""


class ResultExtractionError(RuntimeError):
    """Raised when submitted plates cannot be paired with result rows."""


class TransientCheckError(RuntimeError):
    """Raised when a submission times out and can safely be retried."""


class SafetyStop(RuntimeError):
    """Raised for rate limits, access denials, or maintenance pages."""


@dataclass(frozen=True)
class PlateResult:
    """One row written to the results CSV."""

    plate: str
    status: str
    raw_result: str
    checked_at: str
    batch_number: int


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp without microseconds."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_candidate(line: str) -> str:
    """Normalize outer whitespace and capitalization without changing contents."""

    return line.strip().upper()


def read_candidates(input_path: Path) -> tuple[list[str], list[PlateResult]]:
    """Read, de-duplicate, and locally flag malformed candidates.

    Invalid candidates are returned as result rows so they are visible in the
    CSV and will not be retried on later runs.
    """

    if not input_path.exists():
        raise FileNotFoundError(
            f"Input file not found: {input_path}. Create it with one plate per line."
        )

    candidates: list[str] = []
    invalid_results: list[PlateResult] = []
    seen: set[str] = set()

    for line_number, raw_line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), 1):
        plate = normalize_candidate(raw_line)
        if not plate or plate in seen:
            continue
        seen.add(plate)

        if not ALLOWED_CANDIDATE.fullmatch(plate):
            invalid_results.append(
                PlateResult(
                    plate=plate,
                    status="Invalid",
                    raw_result=(
                        f"Rejected locally on input line {line_number}: only letters, "
                        "numbers, spaces, and hyphens are permitted."
                    ),
                    checked_at=utc_timestamp(),
                    batch_number=0,
                )
            )
        elif len(plate) > MAX_PLATE_LENGTH:
            invalid_results.append(
                PlateResult(
                    plate=plate,
                    status="Invalid",
                    raw_result=(
                        f"Rejected locally on input line {line_number}: {len(plate)} characters "
                        f"exceeds the configured/current page maximum of {MAX_PLATE_LENGTH}."
                    ),
                    checked_at=utc_timestamp(),
                    batch_number=0,
                )
            )
        else:
            candidates.append(plate)

    return candidates, invalid_results


def load_completed_plates(checked_path: Path, results_path: Path) -> set[str]:
    """Load resume state from both durable files.

    Reading the CSV as well covers the small interruption window after a CSV
    row is flushed but before its checked-list line is appended.
    """

    completed: set[str] = set()
    if checked_path.exists():
        completed.update(
            normalize_candidate(line)
            for line in checked_path.read_text(encoding="utf-8").splitlines()
            if normalize_candidate(line)
        )

    if results_path.exists():
        try:
            with results_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
                for row in csv.DictReader(csv_file):
                    plate = normalize_candidate(row.get("plate", ""))
                    if plate and row.get("status", "").strip() in COMPLETED_STATUSES:
                        completed.add(plate)
        except csv.Error as exc:
            print(f"Warning: could not fully read {results_path}: {exc}", file=sys.stderr)

    return completed


def append_result(result_path: Path, result: PlateResult) -> None:
    """Append and sync a result row immediately."""

    needs_header = not result_path.exists() or result_path.stat().st_size == 0
    try:
        with result_path.open("a", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
            if needs_header:
                writer.writeheader()
            writer.writerow(
                {
                    "plate": result.plate,
                    "status": result.status,
                    "raw_result": result.raw_result,
                    "checked_at": result.checked_at,
                    "batch_number": result.batch_number,
                }
            )
            csv_file.flush()
            os.fsync(csv_file.fileno())
    except PermissionError as exc:
        raise RuntimeError(
            f"Cannot write {result_path}. Close it in Excel or another spreadsheet program, then retry."
        ) from exc


def mark_checked(checked_path: Path, plate: str) -> None:
    """Persist a completed candidate immediately."""

    with checked_path.open("a", encoding="utf-8") as checked_file:
        checked_file.write(f"{plate}\n")
        checked_file.flush()
        os.fsync(checked_file.fileno())


def persist_completed(result_path: Path, checked_path: Path, results: Iterable[PlateResult]) -> None:
    """Write each finished result before adding it to the resume list."""

    for result in results:
        append_result(result_path, result)
        if result.status in COMPLETED_STATUSES:
            mark_checked(checked_path, result.plate)


def page_text(page: Page) -> str:
    """Return visible text for narrow safety checks."""

    try:
        return page.locator("body").inner_text(timeout=5_000).lower()
    except PlaywrightTimeoutError:
        return ""


def detect_safety_page(page: Page) -> None:
    """Stop before continuing if the site clearly indicates a hard block."""

    text = page_text(page)
    for term in BLOCKING_TERMS:
        if term in text:
            raise SafetyStop(f"FLHSMV page shows '{term}'. Stopping without further requests.")


def handle_captcha_if_present(page: Page) -> None:
    """Pause for a user to complete a human-verification challenge manually."""

    text = page_text(page)
    if any(term in text for term in CAPTCHA_TERMS):
        print("\nHuman verification or CAPTCHA detected.")
        print("Complete it manually in the visible Chromium window. No CAPTCHA is solved by this script.")
        input("When the checker page is ready, press Enter here to continue...")
        detect_safety_page(page)


def save_debug_artifacts(page: Page, reason: str) -> tuple[Path | None, Path | None]:
    """Save screenshot and HTML to aid selector maintenance after a failure."""

    DEBUG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "_", reason).strip("_")[:50] or "debug"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = DEBUG_DIRECTORY / f"{stamp}_{safe_reason}.png"
    html_path = DEBUG_DIRECTORY / f"{stamp}_{safe_reason}.html"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception as exc:  # A failed debug capture must not hide the original error.
        print(f"Warning: could not save screenshot: {exc}", file=sys.stderr)
        screenshot_path = None

    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception as exc:
        print(f"Warning: could not save HTML snapshot: {exc}", file=sys.stderr)
        html_path = None

    return screenshot_path, html_path


def find_plate_fields(page: Page) -> list[Locator]:
    """Find the live page's ordered personalized-plate fields."""

    fields = page.locator(FIELD_SELECTOR).all()
    if not fields:
        fields = page.locator(FIELD_FALLBACK_SELECTOR).all()
    if not fields:
        screenshot, html = save_debug_artifacts(page, "no_input_fields")
        raise PageStructureError(
            "No personalized-plate input fields were found. "
            f"Debug screenshot: {screenshot}; HTML snapshot: {html}"
        )
    return fields


def find_submit_button(page: Page) -> Locator:
    """Find a uniquely identifiable submit control."""

    submit = page.locator(SUBMIT_SELECTOR)
    if submit.count() != 1:
        submit = page.locator(SUBMIT_FALLBACK_SELECTOR)
    if submit.count() != 1:
        screenshot, html = save_debug_artifacts(page, "submit_button_missing")
        raise PageStructureError(
            "The checker Submit button was not uniquely found. "
            f"Debug screenshot: {screenshot}; HTML snapshot: {html}"
        )
    return submit


def configured_field_limit(fields: Sequence[Locator]) -> int:
    """Read the page maxlength values and return the strictest usable limit."""

    limits: list[int] = []
    for field in fields:
        value = field.get_attribute("maxlength")
        if value and value.isdigit() and int(value) > 0:
            limits.append(int(value))
    return min(limits, default=MAX_PLATE_LENGTH)


def wait_for_checker_form(page: Page) -> list[Locator]:
    """Wait for the form itself, not a fixed delay, after navigation."""

    page.locator("#inquiry").wait_for(state="visible", timeout=NAVIGATION_TIMEOUT_MS)
    handle_captcha_if_present(page)
    detect_safety_page(page)
    return find_plate_fields(page)


def open_checker_with_retries(page: Page) -> list[Locator]:
    """Open the checker and retry temporary navigation failures."""

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"Opening FLHSMV checker (attempt {attempt}/{MAX_RETRIES})...")
            page.goto(URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            return wait_for_checker_form(page)
        except SafetyStop:
            raise
        except (PlaywrightTimeoutError, PlaywrightError, PageStructureError) as exc:
            last_error = exc
            if isinstance(exc, PageStructureError):
                raise
            print(f"Navigation attempt {attempt} failed: {exc}", file=sys.stderr)
            if attempt < MAX_RETRIES:
                time.sleep(min(2 * attempt, 5))
    raise RuntimeError(f"Could not open the checker after {MAX_RETRIES} attempts: {last_error}")


def wait_for_results(page: Page, submitted: Sequence[str]) -> None:
    """Wait until every submitted candidate has a non-empty paired status."""

    try:
        page.wait_for_function(
            """
            (expected) => {
              const rows = [...document.querySelectorAll('#inquiry tr')];
              return expected.every((plate) => rows.some((row) => {
                const input = row.querySelector("input[type='text']");
                const result = row.querySelector('span.outputText');
                return input && result && input.value.trim().toUpperCase() === plate
                  && result.textContent.trim().length > 0;
              }));
            }
            """,
            arg=list(submitted),
            timeout=NAVIGATION_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError as exc:
        raise ResultExtractionError(
            "Timed out waiting for a non-empty availability result paired with every submitted plate."
        ) from exc


def extract_paired_results(page: Page, submitted: Sequence[str], batch_number: int) -> list[PlateResult]:
    """Extract outputText only from the same table row as each submitted input."""

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
    missing = [plate for plate in submitted if plate not in by_plate or not by_plate[plate]]
    if missing:
        raise ResultExtractionError(
            "Could not verify the result-row association for: " + ", ".join(missing)
        )

    checked_at = utc_timestamp()
    return [
        PlateResult(
            plate=plate,
            status=classify_status(by_plate[plate]),
            raw_result=by_plate[plate],
            checked_at=checked_at,
            batch_number=batch_number,
        )
        for plate in submitted
    ]


def classify_status(raw_result: str) -> str:
    """Classify the raw status, checking negative phrases before Available."""

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


def submit_batch(page: Page, batch: Sequence[str], batch_number: int) -> list[PlateResult]:
    """Fill a verified group of fields, submit it, and extract its paired rows."""

    fields = open_checker_with_retries(page)
    field_limit = configured_field_limit(fields)
    too_long = [plate for plate in batch if len(plate) > field_limit]
    if too_long:
        raise PageStructureError(
            f"The current page maxlength changed to {field_limit}; cannot safely submit: "
            f"{', '.join(too_long)}"
        )

    usable_count = min(len(fields), MAX_BATCH_SIZE)
    if not usable_count:
        raise PageStructureError("The page supplied no usable personalized-plate fields.")
    if len(batch) > usable_count:
        raise PageStructureError(
            f"The page now has only {usable_count} usable fields for a {len(batch)}-plate batch."
        )

    # A final batch can have fewer candidates than the page's five fields.
    for field, plate in zip(fields[: len(batch)], batch, strict=True):
        field.fill(plate, timeout=NAVIGATION_TIMEOUT_MS)

    submit = find_submit_button(page)
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS):
            submit.click(timeout=NAVIGATION_TIMEOUT_MS)
    except PlaywrightTimeoutError as exc:
        raise TransientCheckError("Submitting the batch did not complete a page navigation in time.") from exc

    handle_captcha_if_present(page)
    detect_safety_page(page)
    wait_for_results(page, batch)
    return extract_paired_results(page, batch, batch_number)


def chunked(items: Sequence[str], size: int) -> Iterable[list[str]]:
    """Yield consecutive batches without concurrent site requests."""

    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def run_checker(candidates: list[str], result_path: Path, checked_path: Path) -> None:
    """Run serial batches in a visible Chromium instance."""

    with sync_playwright() as playwright:
        browser: Browser | None = None
        try:
            try:
                browser = playwright.chromium.launch(headless=HEADLESS)
            except PlaywrightError as exc:
                first_line = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
                raise RuntimeError(
                    "Could not start Playwright Chromium. Run `python -m playwright install chromium` "
                    f"with the same Python environment, then retry. Details: {first_line}"
                ) from exc
            page = browser.new_page()

            # Detect the actual field count once before calculating batches.
            initial_fields = open_checker_with_retries(page)
            batch_size = min(len(initial_fields), MAX_BATCH_SIZE)
            if batch_size == 0:
                raise PageStructureError("No usable fields were detected on the FLHSMV form.")

            live_max_length = configured_field_limit(initial_fields)
            runtime_invalid = [plate for plate in candidates if len(plate) > live_max_length]
            if runtime_invalid:
                print(
                    f"Saving {len(runtime_invalid)} candidate(s) rejected by the live form's "
                    f"{live_max_length}-character limit..."
                )
                persist_completed(
                    result_path,
                    checked_path,
                    [
                        PlateResult(
                            plate=plate,
                            status="Invalid",
                            raw_result=(
                                f"Rejected locally: {len(plate)} characters exceeds the current "
                                f"FLHSMV form maxlength of {live_max_length}."
                            ),
                            checked_at=utc_timestamp(),
                            batch_number=0,
                        )
                        for plate in runtime_invalid
                    ],
                )
                candidates = [plate for plate in candidates if plate not in set(runtime_invalid)]
            if not candidates:
                print("No valid candidates remain after checking the live form limit.")
                return

            total_batches = (len(candidates) + batch_size - 1) // batch_size
            for batch_number, batch in enumerate(chunked(candidates, batch_size), start=1):
                print(
                    f"Checking batch {batch_number}/{total_batches}: "
                    + ", ".join(batch)
                )
                results: list[PlateResult] | None = None
                try:
                    for attempt in range(1, MAX_RETRIES + 1):
                        try:
                            results = submit_batch(page, batch, batch_number)
                            break
                        except TransientCheckError as exc:
                            print(
                                f"Batch {batch_number} submission timed out "
                                f"(attempt {attempt}/{MAX_RETRIES}): {exc}",
                                file=sys.stderr,
                            )
                            if attempt < MAX_RETRIES:
                                time.sleep(min(2 * attempt, 5))
                except (PageStructureError, ResultExtractionError) as exc:
                    screenshot, html = save_debug_artifacts(page, "batch_failure")
                    raise RuntimeError(
                        f"Batch {batch_number} stopped safely: {exc}\n"
                        f"Debug screenshot: {screenshot}\nDebug HTML: {html}"
                    ) from exc
                if results is None:
                    raise RuntimeError(
                        f"Batch {batch_number} could not be submitted after {MAX_RETRIES} attempts."
                    )

                persist_completed(result_path, checked_path, results)
                for result in results:
                    print(f"  {result.plate}: {result.status} ({result.raw_result})")

                if batch_number < total_batches:
                    delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
                    print(f"Waiting {delay:.1f} seconds before the next batch...")
                    time.sleep(delay)
        finally:
            if browser is not None:
                browser.close()


def main() -> int:
    """Load work, persist local validation failures, then check remaining plates."""

    base = Path.cwd()
    input_path = base / INPUT_FILENAME
    result_path = base / OUTPUT_FILENAME
    checked_path = base / CHECKED_FILENAME

    try:
        candidates, invalid_results = read_candidates(input_path)
        completed = load_completed_plates(checked_path, result_path)

        pending_invalid = [result for result in invalid_results if result.plate not in completed]
        if pending_invalid:
            print(f"Saving {len(pending_invalid)} locally rejected candidate(s)...")
            persist_completed(result_path, checked_path, pending_invalid)
            completed.update(result.plate for result in pending_invalid)

        pending = [plate for plate in candidates if plate not in completed]
        print(
            f"Loaded {len(candidates)} valid unique candidate(s); "
            f"{len(completed)} already completed; {len(pending)} to check."
        )
        if not pending:
            print("Nothing to check. Results are already up to date.")
            return 0

        run_checker(pending, result_path, checked_path)
        print(f"Finished. Results saved incrementally to {result_path}.")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted. Previously completed results remain saved.", file=sys.stderr)
        return 130
    except (FileNotFoundError, RuntimeError, SafetyStop, ValueError, PageStructureError) as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
