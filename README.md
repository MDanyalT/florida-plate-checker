# Florida personalized plate checker

`plate_checker.py` checks plate candidates through the official FLHSMV web form using Playwright with a visible Chromium browser. It sends no direct HTTP requests and runs batches serially.

## Install and run

### macOS

1. Open Terminal in this folder.
2. Create and activate a virtual environment:

   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   ```

3. Install Python dependencies and Chromium:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   python -m playwright install chromium
   ```

4. Edit `plates.txt`, then run:

   ```bash
   python plate_checker.py
   ```

### Windows (PowerShell)

1. Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/), selecting **Add Python to PATH** during setup.
2. Open PowerShell in this folder.
3. Create and activate a virtual environment:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, run this only for the current session and then activate again:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```

4. Install Python dependencies and Chromium:

   ```powershell
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   python -m playwright install chromium
   ```

5. Edit `plates.txt`, then run:

   ```powershell
   python .\plate_checker.py
   ```

## Output and resuming

- `plate_results.csv` is appended and flushed after every result, with `plate`, `status`, `raw_result`, `checked_at`, and `batch_number` columns.
- `checked_plates.txt` is updated after each completed plate. The script also reads completed rows from the CSV on startup to cover an interruption between the two writes.
- Locally rejected input is saved with `Invalid` status and batch number `0`.
- `Error` results are deliberately not added to `checked_plates.txt`, so they can be retried on the next run.

## Selector maintenance

The script was based on the live page structure inspected on 2026-07-30:

- Inputs: `#inquiry input.inputText[type='text']`, with an aria-label fallback.
- Submit: `#MainContent_btnSubmit`, with a submit-value fallback.
- Results: `span.outputText` in the same `#inquiry tr` as the submitted input.

If FLHSMV changes the page, the script stops safely and writes a screenshot plus an HTML snapshot in `plate_checker_debug/`. Inspect that HTML in a browser, then adjust `FIELD_SELECTOR`, `FIELD_FALLBACK_SELECTOR`, `SUBMIT_SELECTOR`, `SUBMIT_FALLBACK_SELECTOR`, or `RESULT_ROW_SELECTOR` near the top of `plate_checker.py`. Keep the result extraction tied to the same row as each input so statuses cannot be associated with the wrong plate.

## Troubleshooting

### Playwright browser installation fails

Run `python -m playwright install chromium` again from the activated virtual environment. If the `playwright` command is not found, always use `python -m playwright ...` so the installed package is used.

### Chromium does not open

Make sure you run the script with the same activated virtual environment used for installation: `python -m playwright install chromium`, then `python plate_checker.py`. On macOS, launch it from Terminal rather than a restricted automation sandbox; visible Chromium needs normal desktop permissions.

### No input fields detected

The form may have changed, be temporarily unavailable, or show a verification page. Check the newest files in `plate_checker_debug/`; they contain the screenshot and HTML captured at the failure. Update the selectors as described above only after verifying the live markup.

### Result parsing failure

The checker returned a page but the script could not match every submitted input to a non-empty status in the same row. The batch is not marked checked. Review the saved debug files and update the row/result selectors if the page changed.

### Timeout

Try again later; temporary navigation failures are retried up to `MAX_RETRIES`. You can increase `NAVIGATION_TIMEOUT_MS` near the top of the script for a slow connection. Do not decrease the 5–10 second inter-batch delay.

### CAPTCHA or human verification

The script pauses with Chromium visible. Complete the challenge manually in that browser and press Enter in the terminal. It does not use CAPTCHA-solving services or bypass access controls.

### Access denied, rate limit, or maintenance message

The script stops without further requests. Wait until the service is available again before retrying; do not try to bypass the restriction.

### CSV file locked by Excel

Close `plate_results.csv` in Excel (and any preview pane or other spreadsheet application), then run the script again. Completed rows are preserved and will be skipped.
