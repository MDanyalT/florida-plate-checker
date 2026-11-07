from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_visible_checkbox_selection_and_submission_in_chromium() -> None:
    """Exercise the real selection JavaScript without contacting FLHSMV."""

    markup = """
    <form id="bulk-run" action="/safe-submit" method="post"
          data-large-run-form data-visible-plate-selection
          data-threshold="100" data-max-plates="1000" data-development="false">
      <input type="hidden" name="confirm_large" value="no">
    </form>
    <label><input type="checkbox" data-table-select-all> Select this page</label>
    <button id="bulk-run-label" type="submit" form="bulk-run">Check selected</button>
    <span id="bulk-selection-count">0 selected</span>
    <span id="bulk-run-error" role="alert" hidden></span>
    <input type="checkbox" name="plate_ids" value="11" form="bulk-run"
           data-row-check data-plate-id="11" data-checked="false" aria-label="Select ALPHA">
    <input type="checkbox" name="plate_ids" value="12" form="bulk-run"
           data-row-check data-plate-id="12" data-checked="true" aria-label="Select BRAVO">
    <input type="checkbox" name="plate_ids" value="13" form="bulk-run"
           data-row-check data-plate-id="13" data-checked="false" aria-label="Select CHARLIE">
    <input type="checkbox" name="plate_ids" value="14" form="bulk-run"
           data-row-check data-plate-id="14" data-checked="false" disabled
           aria-label="Select DISABLED">
    """

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError as bundled_error:
            try:
                browser = playwright.chromium.launch(headless=True, channel="chrome")
            except PlaywrightError as system_error:
                pytest.skip(
                    "Neither Playwright Chromium nor system Chrome is available: "
                    f"{bundled_error}; {system_error}"
                )
        try:
            page = browser.new_page()
            page.set_content(markup)
            page.add_script_tag(path=str(PROJECT_ROOT / "static" / "app.js"))
            page.evaluate(
                """
                document.querySelector('#bulk-run').addEventListener('submit', (event) => {
                  window.__submittedPlateIds = [...new FormData(event.currentTarget).getAll('plate_ids')];
                  event.preventDefault();
                });
                """
            )

            page.get_by_role("button", name="Check selected").click()
            assert page.get_by_role("alert").inner_text() == "Select at least one plate first."

            page.get_by_role("checkbox", name="Select ALPHA").check()
            assert page.locator("#bulk-selection-count").inner_text() == "1 selected"
            page.get_by_role("button", name="Check selected").click()
            assert page.evaluate("window.__submittedPlateIds") == ["11"]

            page.get_by_role("checkbox", name="Select BRAVO").check()
            page.get_by_role("button", name="Check selected plates").click()
            assert page.evaluate("window.__submittedPlateIds") == ["11", "12"]

            select_page = page.get_by_role("checkbox", name="Select this page")
            select_page.check()
            assert page.locator("#bulk-selection-count").inner_text() == "3 selected"
            assert page.get_by_role("checkbox", name="Select DISABLED").is_checked() is False

            page.get_by_role("checkbox", name="Select BRAVO").uncheck()
            assert page.locator("#bulk-selection-count").inner_text() == "2 selected"
            assert select_page.is_checked() is False
            assert page.evaluate(
                "document.querySelector('[data-table-select-all]').indeterminate"
            ) is True

            select_page.check()
            select_page.uncheck()
            assert page.locator("#bulk-selection-count").inner_text() == "0 selected"
        finally:
            browser.close()
