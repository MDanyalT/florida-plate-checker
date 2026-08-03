"""CSV serialization helpers shared by export routes and tests."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping, Sequence


def rows_to_csv(columns: Sequence[str], rows: Iterable[Mapping[str, object]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()

