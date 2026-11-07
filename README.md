# Florida Plate Finder

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

Florida Plate Finder is a private, local web app for discovering, saving, and checking Florida personalized license plates. It stores your plates, their last known availability, full check history, favorites, and notes in a local SQLite database.

Availability checks use a **visible Playwright Chromium browser** and the official [FLHSMV Personalized Plate Inquiry](https://services.flhsmv.gov/MVCheckPersonalPlate/PlateInquiryView.aspx). The application does not replay ASP.NET requests directly and does not bypass CAPTCHA, rate limits, blocks, or other access controls. It cannot reserve or order plates.

## What's included

- **Home**: type a plate, see a live plate preview, and check it in one click. If you've checked it before, its last result and date appear as you type.
- **Explore Plates** has three modes:
  - *Plate ideas*: rule-based variations of a word, name, or phrase (similar, shorter, add numbers, look-alike substitutions, shuffled "surprise me"). No AI is involved; results are deterministic.
  - *Pattern builder*: choose what goes in each spot (fixed text, any letter, any digit, letter or digit, your own character list), mark spots optional, or make a spot repeat an earlier one. You see an exact combination count (or a clearly labeled upper-bound estimate for very large patterns) and examples before generating anything.
  - *Ready-made patterns*: all ten original generators (letter + number, number + letter, word + number, letters around a number, repeated, mirrored, and sequential digits, two letters, custom `{L}{N}{NN}{WORD}` templates, and keyword variations), each showing only its relevant settings.
- Generated results are previewed page by page with search, filters, sorting, and bulk selection. Saving and checking are separate, explicit actions.
- **Saved Plates**: card or list view, quick filters (available, unavailable, never checked, needs verification, favorites, recently changed), advanced filters, bulk favorite/delete/check, and a details page per plate with notes and a timeline.
- **Check history**: plain-language summaries of each check session, with technical details (run number, batches, speed, raw responses) one click away.
- **More tools**: bulk import (paste or `.txt`/`.csv` upload), CSV exports, JSON backup and non-destructive restore, and statistics.
- The original command-line workflow through `plate_checker.py`.

## Responsible-use safeguards

The first version intentionally has no parallel checking, direct HTTP form replay, CAPTCHA solving, proxy or IP rotation, automatic reservation, continuous polling, scheduled monitoring, or hidden checking. Every run requires a user action. The default run limit is 1,000 candidates, and runs above 100 require an extra confirmation.

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

## Launch the app

Activate the virtual environment, then run:

```bash
python app.py
```

Open this address in your browser:

```text
http://127.0.0.1:8000
```

The dashboard is bound to the local computer only. Leave the terminal window open while using it. Press `Ctrl+C` in the terminal to shut it down.

## Check a single plate

On **Home**, type the plate and choose **Check availability**. The plate is saved, a visible Chromium window opens on the official FLHSMV site, and the plate's details page refreshes with the result when the check finishes. **Save for later** stores it without checking.

## Add or upload many plates

Open **More → Bulk import** (`/tools#import`). Paste one plate per line or upload a file, then review valid values, duplicates, and validation failures before anything is saved.

- `.txt`: each nonblank line is treated as one plate.
- `.csv`: a column named `plate` is used automatically. If one is not present, you'll be asked which column to use.
- Files are treated only as UTF-8 text and are never executed. The default upload limit is 2 MB.

## Explore and generate plates

Open **Explore Plates**, pick a mode, and watch the live count and examples. Choose **Preview combinations** (or **Show ideas**) to generate. Nothing is saved or checked at this point. Select the results you like, then choose **Save to my plates**, **Favorite**, or **Check availability**. A single preview is limited to 300,000 combinations; larger patterns show an estimate and ask you to narrow them.

Custom templates (Ready-made patterns → Custom template) support:

- `{L}`: one letter
- `{N}`: one digit
- `{NN}`: two digits
- `{WORD}`: the supplied word

For example, `{WORD}{NN}` with `SUN` produces `SUN00` through `SUN99`, subject to the seven-character limit.

## Start, watch, and stop a checking run

1. Open **Saved Plates** (or select results in Explore).
2. Select plates with the checkboxes.
3. Choose **Check availability** and confirm.

Only one run can be active, and a run is capped at 500 plates (runs above 100 need an extra confirmation). The application opens visible Chromium, submits at most five configurations per FLHSMV form, and waits a random five to ten seconds between batches. A progress banner appears at the top of every page.

Choose **Stop safely** to request a stop. The current browser step finishes, Chromium closes, and every completed result stays saved.

## CAPTCHA and blocks

If FLHSMV displays CAPTCHA or human verification, the progress banner says *Action needed*. Complete the challenge manually in visible Chromium, return to the terminal that launched `python app.py`, and press Enter. The application never solves or bypasses CAPTCHA.

Access-denied, rate-limit, maintenance, and repeated-failure messages stop the run and record the reason. Wait before trying again; do not attempt to evade the restriction.

## Statuses, freshness, and history

Statuses describe what the official site reported *when last checked*: **Available when last checked**, **Unavailable when last checked**, **Not yet checked**, **Checking**, or **Needs verification** (invalid, unrecognized, or errored responses). Each shows when it was checked, and results older than a week are flagged for re-checking. Every completed check also creates an immutable history record, and status changes are tracked.

## CSV exports, backup, and restore

**More → Export data** downloads CSVs of all plates, available plates, favorites, changed plates, and full history. On Saved Plates, **Export this list** downloads exactly the filtered view.

**More → Backup & restore** downloads one JSON file containing every plate, note, favorite, history record, and run. Restoring merges a backup: missing records are added, newer results win, favorites and notes are merged, and nothing is deleted.

The old URLs (`/results`, `/generator`) still work.

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
CHECK_SPEED_PROFILE=conservative
MAX_BATCH_SIZE=5
MAX_PLATES_PER_RUN=1000
```

Keep `HEADLESS=false` for normal responsible use. Do not point `FLHSMV_URL` at unofficial services.

`MAX_PLATES_PER_RUN` controls the longest run the interface and server will accept. The default is 1,000. Increasing it does not add parallelism; it only permits a longer serial browser session.

Checking-speed profiles retain one visible Chromium page, use the official form's available fields (up to five), and keep CAPTCHA handling manual:

| Profile | Batch delay | Result timeout | Retry delay | Retries |
| --- | ---: | ---: | ---: | ---: |
| `conservative` (default) | 5–10 seconds | 45 seconds | 3 seconds | 3 |
| `balanced` | 3–6 seconds | 30 seconds | 2 seconds | 3 |
| `faster` | 2–4 seconds | 25 seconds | 1.5 seconds | 2 |

Set `CHECK_SPEED_PROFILE=balanced` or `CHECK_SPEED_PROFILE=faster` in `.env`. For individual control, set `CHECK_DELAY_MIN_SECONDS`, `CHECK_DELAY_MAX_SECONDS`, `RESULT_TIMEOUT_SECONDS`, `RETRY_DELAY_SECONDS`, or `MAX_RETRIES`. Older `MIN_DELAY_SECONDS`, `MAX_DELAY_SECONDS`, and `MAX_CANDIDATES_PER_RUN` values remain recognized for compatibility; remove them from an older `.env` when switching to profile-based timing.

The checker reuses one browser page for the complete run, clears every official form field between batches, waits for submitted plate/result rows instead of network-idle, retries transient failures, and commits results once per batch. Run history records elapsed time, completed batches, average active seconds per plate, retries, errors, and manual CAPTCHA pause time separately.

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
