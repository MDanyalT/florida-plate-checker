"""Safe text and CSV plate-list parsing."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass


@dataclass(frozen=True)
class CSVInspection:
    columns: list[str]
    selected_column: str | None
    values: list[str]


def parse_text_content(content: str) -> list[str]:
    return content.splitlines()


def inspect_csv(content: str, selected_column: str | None = None) -> CSVInspection:
    stream = io.StringIO(content.lstrip("\ufeff"))
    reader = csv.DictReader(stream)
    if not reader.fieldnames:
        raise ValueError("CSV file has no header row.")
    raw_columns = [column for column in reader.fieldnames if column and column.strip()]
    columns = [column.strip() for column in raw_columns]
    if not columns:
        raise ValueError("CSV file has no usable columns.")

    if selected_column is None:
        selected_column = next((column for column in columns if column.lower() == "plate"), None)
    if selected_column is not None and selected_column not in columns:
        raise ValueError("The selected CSV column does not exist.")

    raw_selected = next(
        (raw for raw in raw_columns if raw.strip() == selected_column), None
    ) if selected_column else None
    rows = list(reader)
    values = [row.get(raw_selected, "") for row in rows] if raw_selected else []
    return CSVInspection(columns=columns, selected_column=selected_column, values=values)
