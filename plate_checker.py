#!/usr/bin/env python3
"""Command-line wrapper for the shared conservative Playwright checker."""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.checker_service import CheckResult, CheckerService, SafetyStop, classify_status
from app.plate_utils import analyze_candidates, normalize_plate


INPUT_FILENAME = "plates.txt"
OUTPUT_FILENAME = "plate_results.csv"
CHECKED_FILENAME = "checked_plates.txt"
CSV_COLUMNS = ("plate", "status", "raw_result", "checked_at", "batch_number")
COMPLETED_STATUSES = {"Available", "Not available", "Invalid", "Unknown"}


def load_completed(checked_path: Path, results_path: Path) -> set[str]:
    completed: set[str] = set()
    if checked_path.exists():
        completed.update(
            normalize_plate(line)
            for line in checked_path.read_text(encoding="utf-8").splitlines()
            if normalize_plate(line)
        )
    if results_path.exists():
        with results_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                plate = normalize_plate(row.get("plate", ""))
                if plate and row.get("status", "") in COMPLETED_STATUSES:
                    completed.add(plate)
    return completed


def append_result(result_path: Path, result: CheckResult) -> None:
    needs_header = not result_path.exists() or result_path.stat().st_size == 0
    with result_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        if needs_header:
            writer.writeheader()
        writer.writerow(
            {
                "plate": result.plate,
                "status": result.status,
                "raw_result": result.raw_result,
                "checked_at": result.checked_at.isoformat(),
                "batch_number": result.batch_number,
            }
        )
        handle.flush()
        os.fsync(handle.fileno())


def mark_checked(checked_path: Path, plate: str) -> None:
    with checked_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{plate}\n")
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    base = Path.cwd()
    input_path = base / INPUT_FILENAME
    output_path = base / OUTPUT_FILENAME
    checked_path = base / CHECKED_FILENAME
    if not input_path.exists():
        print(f"Stopped: create {input_path} with one plate per line.", file=sys.stderr)
        return 1

    report = analyze_candidates(input_path.read_text(encoding="utf-8").splitlines())
    completed = load_completed(checked_path, output_path)
    now = datetime.now(timezone.utc)
    for failure in report.failures:
        if failure.normalized in completed:
            continue
        result = CheckResult(
            plate=failure.normalized,
            status="Invalid",
            raw_result=f"Rejected locally: {failure.reason}",
            checked_at=now,
            batch_number=0,
        )
        append_result(output_path, result)
        mark_checked(checked_path, result.plate)
        completed.add(result.plate)

    pending = [plate for plate in report.valid if plate not in completed]
    print(
        f"Loaded {len(report.valid)} valid unique candidate(s); "
        f"{len(pending)} remain to check."
    )
    if not pending:
        print("Nothing to check.")
        return 0

    def persist(result: CheckResult) -> None:
        append_result(output_path, result)
        if result.status in COMPLETED_STATUSES:
            mark_checked(checked_path, result.plate)
        print(f"  {result.plate}: {result.status} ({result.raw_result})")

    try:
        stopped = CheckerService().run(
            pending,
            on_result=persist,
            on_batch=lambda number, batch: print(
                f"Checking batch {number}: {', '.join(batch)}"
            ),
        )
        if stopped:
            print("Stopped safely. Completed results remain saved.")
            return 130
        print(f"Finished. Results saved to {output_path}.")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted. Completed results remain saved.", file=sys.stderr)
        return 130
    except (RuntimeError, SafetyStop, ValueError) as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
