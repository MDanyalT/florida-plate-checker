import csv
import io

import pytest

from app.exporter import rows_to_csv
from app.importer import inspect_csv, parse_text_content


def test_text_import_preserves_one_value_per_line() -> None:
    assert parse_text_content("ABC\n\nFLA-1\n") == ["ABC", "", "FLA-1"]


def test_csv_import_detects_plate_column() -> None:
    inspection = inspect_csv("name,plate\nOne,ABC\nTwo,FLA-1\n")
    assert inspection.selected_column == "plate"
    assert inspection.values == ["ABC", "FLA-1"]


def test_csv_import_allows_column_selection() -> None:
    inspection = inspect_csv("candidate,label\nABC,one\n", "candidate")
    assert inspection.values == ["ABC"]


def test_csv_import_rejects_missing_header() -> None:
    with pytest.raises(ValueError):
        inspect_csv("")


def test_csv_export_quotes_values() -> None:
    content = rows_to_csv(("plate", "notes"), [{"plate": "ABC", "notes": "one, two"}])
    parsed = list(csv.DictReader(io.StringIO(content)))
    assert parsed == [{"plate": "ABC", "notes": "one, two"}]

