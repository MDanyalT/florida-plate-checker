"""Plate normalization, validation, and duplicate reporting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


ALLOWED_PLATE = re.compile(r"^[A-Z0-9 -]+$")


@dataclass(frozen=True)
class ValidationFailure:
    original: str
    normalized: str
    reason: str
    line_number: int | None = None


@dataclass
class CandidateReport:
    valid: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    failures: list[ValidationFailure] = field(default_factory=list)


def normalize_plate(value: str) -> str:
    return value.strip().upper()


def validate_plate(value: str, max_length: int = 7) -> str | None:
    if not value:
        return "Plate is blank."
    if not ALLOWED_PLATE.fullmatch(value):
        return "Only letters, numbers, spaces, and hyphens are allowed."
    if len(value) > max_length:
        return f"Plate has {len(value)} characters; the maximum is {max_length}."
    return None


def analyze_candidates(values: Iterable[str], max_length: int = 7) -> CandidateReport:
    report = CandidateReport()
    seen: set[str] = set()
    for line_number, original in enumerate(values, 1):
        normalized = normalize_plate(original)
        if not normalized:
            continue
        error = validate_plate(normalized, max_length)
        if error:
            report.failures.append(
                ValidationFailure(original, normalized, error, line_number=line_number)
            )
        elif normalized in seen:
            report.duplicates.append(normalized)
        else:
            seen.add(normalized)
            report.valid.append(normalized)
    return report

