# Florida Plate Research

## Quick start

Florida Plate Research runs only on your own computer; it is not an online service. Your plate ideas, results, notes, favorites, and history stay local unless you choose to copy or share them. Internet access is needed during setup and whenever you check the official FLHSMV website.

### macOS

1. Download **Florida-Plate-Research-macOS.zip** from GitHub Releases.
2. Extract the ZIP.
3. Double-click **Setup Plate Research.command**.
4. If macOS blocks it, right-click the setup file, choose **Open**, then confirm **Open**. Do not disable Gatekeeper.
5. After setup, double-click **Open Plate Research.command**.
6. The dashboard opens automatically in your default browser.
7. Keep the Terminal window open while using the app. Closing it or pressing Control+C stops the local app.

### Windows

1. Download **Florida-Plate-Research-Windows.zip** from GitHub Releases.
2. Extract the ZIP.
3. Double-click **Setup Plate Research.bat**.
4. Approve a normal Windows security prompt only when the ZIP came from the official repository.
5. After setup, double-click **Open Plate Research.bat**.
6. The dashboard opens automatically in your default browser.
7. Keep the command window open while using the app. Closing it or pressing Control+C stops the local app.

The first setup may take several minutes because it creates a private Python environment and installs Chromium. Python 3.11 or newer must already be installed from [python.org](https://www.python.org/downloads/). During a plate check, visible Chromium may open. If FLHSMV shows a CAPTCHA, complete it yourself; the app never bypasses human verification.

Use **Stop Plate Research** only when you need to stop a copy whose launcher window is unavailable. It validates the saved process first and never broadly stops other Python programs.

## About the application

Florida Plate Research is a private, local dashboard for building and checking Florida personalized-license-plate shortlists. It stores candidates, current availability, full check history, favorites, notes, and status changes in a local SQLite database.

Availability checks use a **visible Playwright Chromium browser** and the official [FLHSMV Personalized Plate Inquiry](https://services.flhsmv.gov/MVCheckPersonalPlate/PlateInquiryView.aspx). The application does not replay ASP.NET requests directly and does not bypass CAPTCHA, rate limits, blocks, or other access controls.

## What the dashboard includes

- Manual plate entry with normalization, duplicate detection, and validation review
- `.txt` and `.csv` uploads with automatic `plate` column detection
- Ten plate-generation patterns, including custom placeholders and keyword variations
- Searchable, sortable, paginated plate library with filters, favorites, and notes
- Clear Check actions for untested plates and Recheck actions for prior results
- Live progress refreshed every two seconds and a safe Stop button
- Full per-plate check history and status-change detection
- CSV exports for all plates, available plates, favorites, filtered results, changed plates, and complete history
- The original command-line workflow through `plate_checker.py`

## Responsible-use safeguards

The first version intentionally has no parallel checking, direct HTTP form replay, CAPTCHA solving, proxy or IP rotation, automatic reservation, continuous polling, scheduled monitoring, or hidden checking. Every run requires a user action. The default run limit is 500 candidates, and runs above 100 require an extra confirmation.

## Required software

- Python 3.11 or newer
- A normal desktop session capable of showing Chromium
- Internet access while checking plates or installing Chromium

## Developer installation on macOS

Open Terminal in this project folder and run:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

If `python3.11` is unavailable but `python3 --version` reports 3.11 or newer, use `python3 -m venv .venv` for the first command.

## Developer installation on Windows

Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/) and select **Add Python to PATH**. Open PowerShell in the project folder and run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

If PowerShell blocks virtual-environment activation, allow it only for the current window and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Launch the local dashboard

Activate the virtual environment, then run:

```bash
python app.py
```

Open this address in your browser:

```text
http://127.0.0.1:8000
```

The dashboard is bound to the local computer only. Leave the terminal window open while using it. Press `Ctrl+C` in the terminal to shut it down.

## Add or upload plates

On the **Dashboard**, paste one candidate per line and choose **Review plate list**. The review shows valid values, duplicates, and specific validation failures before anything is saved. Choose **Add and check now** to save the selected plates and immediately start a visible-browser run, or **Add to library** to save without checking.

For uploads:

- `.txt`: each nonblank line is treated as one plate.
- `.csv`: a column named `plate` is used automatically. If one is not present, the dashboard asks which column to use.
- Files are treated only as UTF-8 text and are never executed.
- The default upload limit is 2 MB.

## Generate plate combinations

Open **Generate plates**, choose a pattern, enter only the fields shown for that pattern, and select **Preview candidates**. A preview does not save or check anything. After selecting candidates, choose **Add and check selected** or **Add selected to library**. More than 500 valid candidates displays a warning and requires confirmation.

Custom templates support:

- `{L}` — one letter
- `{N}` — one digit
- `{NN}` — two digits
- `{WORD}` — the supplied word

For example, `{WORD}{NN}` with `SUN` produces `SUN00` through `SUN99`, subject to the seven-character limit.

## Start, watch, and stop a checking run

1. Open **Plate library**.
2. Select the requested plates with the checkboxes.
3. Choose **Check selected** for never-checked plates or **Recheck selected** for prior results.
4. Confirm the run when it includes more than 100 candidates.

Only one run can be active. The application opens visible Chromium, submits at most five configurations per FLHSMV form, and waits a random five to ten seconds between batches. The progress bar shows the batch, checked count, result counts, and last processed plate.

Choose **Stop safely** to request a stop. The current browser step finishes safely, Chromium closes, and every result already completed remains saved. To resume, select the remaining plates and start another explicit run.

## CAPTCHA and blocks

If FLHSMV displays CAPTCHA or human verification, the run changes to `captcha`. Complete the challenge manually in visible Chromium, return to the terminal that launched `python app.py`, and press Enter. The application never solves or bypasses CAPTCHA.

Access-denied, rate-limit, maintenance, and repeated-failure messages stop the run and record the reason. Wait before trying again; do not attempt to evade the restriction.

## Plate library, run history, and status changes

The **Plate library** stores one current row for each normalized plate. Every completed check also creates an immutable history row. When a status changes, the prior status is preserved and the change timestamp appears on the Dashboard and in the Changed filter.

The **Run history** page shows recent check rows and checking-run summaries. It can be filtered to a single plate from the Plate library.

## CSV exports

The Plate library toolbar provides exports for:

- All plates
- Available plates
- Favorites
- The current filtered result set
- Plates with a recorded status change
- Full check history

Exports are generated locally from SQLite and contain timestamps, notes, statuses, and raw FLHSMV result text where applicable.

## Local data and privacy

The application stores its database at:

```text
user_data/plates.db
```

It also keeps backups, exports, and debugging captures under `user_data/`. Git and the release builder exclude that entire folder. If an older `data/plates.db` exists and the new database does not, the app uses SQLite's backup mechanism to copy it safely into `user_data/plates.db`; the original is retained as a fallback. A custom `DATABASE_PATH` remains supported.

Choose **Back up my data** on the Dashboard to create a timestamped SQLite copy in `user_data/backups/` and download the same copy through your browser. To reset the dashboard, stop the application and move `user_data/plates.db` somewhere safe; a new empty database is created on the next launch.

## Safe updates for ZIP installations

Double-click **Update Plate Research** for your operating system. It creates a database backup when setup is available, then shows the safe manual update steps. Download the newest release into a new folder, copy your existing `user_data/` folder into it, and run the new setup launcher. Never replace or delete `user_data/` during an update.

The updater intentionally does not assume Git is installed and does not download or overwrite application files automatically.

## Build the release ZIP files

From a developer environment, run:

```bash
python scripts/build_releases.py
```

The script creates `dist/Florida-Plate-Research-macOS.zip` and `dist/Florida-Plate-Research-Windows.zip`. The archives contain shared application files plus only the correct operating-system launchers. They exclude `.git`, `.venv`, `.env`, tests, databases, personal inputs, results, caches, exports, backups, and debug files. Python and Chromium binaries are not bundled.

## Optional configuration

Copy `.env.example` to `.env` and edit only the values you need. Safe defaults include:

```text
DATA_DIRECTORY=user_data
DATABASE_PATH=user_data/plates.db
HEADLESS=false
MIN_DELAY_SECONDS=5
MAX_DELAY_SECONDS=10
MAX_BATCH_SIZE=5
MAX_CANDIDATES_PER_RUN=500
```

Keep `HEADLESS=false` for normal responsible use. Do not point `FLHSMV_URL` at unofficial services.

## Original command-line checker

Create a private `plates.txt` with one candidate per line. A safe sample is provided as `plates.example.txt`. Then run:

```bash
cp plates.example.txt plates.txt       # macOS
python plate_checker.py
```

Windows PowerShell:

```powershell
Copy-Item plates.example.txt plates.txt
python .\plate_checker.py
```

The CLI saves `plate_results.csv` and `checked_plates.txt` incrementally and uses the same shared Playwright service as the dashboard.

## Run automated tests

Tests use temporary SQLite databases and a mocked checker service. They never contact FLHSMV:

```bash
python -m pytest -q
```

## Troubleshooting

### `ModuleNotFoundError`

Activate `.venv` and run `python -m pip install -r requirements.txt`. Use the same `python` command for installation and launch.

### Playwright or Chromium is missing

Run this from the activated environment:

```bash
python -m playwright install chromium
```

### Chromium does not open

Launch `python app.py` from a normal macOS Terminal or Windows PowerShell desktop session. Restricted or remote shells may not have permission to display a visible browser.

### No input fields detected or result parsing fails

The FLHSMV page may have changed. The run stops and writes a screenshot and HTML snapshot to `user_data/debug/`. The verified selectors are in `app/checker_service.py`: plate fields are currently within `#inquiry`, Submit uses `#MainContent_btnSubmit`, and each result is paired with the text input in the same table row.

### Timeout

Temporary navigation problems are retried a finite number of times. Try later or increase `NAVIGATION_TIMEOUT_MS` in `.env` for a slow connection. Do not remove the inter-batch delay.

### Access denied or rate limited

Stop and wait until FLHSMV allows normal access again. The application deliberately contains no evasion features.

### Database is locked

Run only one copy of `python app.py`. Close database viewers that hold a write lock, then restart the application.

### An exported CSV is locked by Excel

Export to a new filename or close the existing CSV in Excel before overwriting it.

## Version-one limitations

- Availability is informational and may change before an in-person reservation.
- CAPTCHA completion requires the visible browser and the launch terminal.
- Runs do not automatically resume after an application restart; completed results remain saved and the interrupted run is recorded.
- There are no notifications, schedules, automatic monitoring, reservations, purchases, or multi-user accounts.
