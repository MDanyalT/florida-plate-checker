"""Deterministic Florida plate candidate generators."""

from __future__ import annotations

import itertools
import re
import string
from dataclasses import dataclass, field

from app.plate_utils import normalize_plate, validate_plate


LETTERS = string.ascii_uppercase
DIGITS = string.digits
PLACEHOLDER = re.compile(r"\{(L|N|NN|WORD)\}")


@dataclass
class GenerationResult:
    candidates: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    duplicate_count: int = 0
    total_before_validation: int = 0

    @property
    def large_warning(self) -> bool:
        return len(self.candidates) > 500


def _finalize(values: list[str], max_length: int) -> GenerationResult:
    result = GenerationResult(total_before_validation=len(values))
    seen: set[str] = set()
    for value in values:
        plate = normalize_plate(value)
        error = validate_plate(plate, max_length)
        if error:
            result.rejected.append(f"{plate or '(blank)'} — {error}")
        elif plate in seen:
            result.duplicate_count += 1
        else:
            seen.add(plate)
            result.candidates.append(plate)
    return result


def _range(start: int, end: int) -> range:
    if end < start:
        start, end = end, start
    if end - start > 10_000:
        raise ValueError("Numeric range is too large; use 10,001 values or fewer.")
    return range(start, end + 1)


def custom_template_values(template: str, word: str = "") -> list[str]:
    parts: list[list[str]] = []
    position = 0
    for match in PLACEHOLDER.finditer(template.upper()):
        if match.start() > position:
            parts.append([template.upper()[position : match.start()]])
        token = match.group(1)
        choices = {
            "L": list(LETTERS),
            "N": list(DIGITS),
            "NN": [f"{number:02d}" for number in range(100)],
            "WORD": [normalize_plate(word)],
        }[token]
        parts.append(choices)
        position = match.end()
    if position < len(template):
        parts.append([template.upper()[position:]])
    if not parts:
        return [template]
    combinations = 1
    for choices in parts:
        combinations *= len(choices)
    if combinations > 20_000:
        raise ValueError("Template expands beyond 20,000 candidates; make it more specific.")
    return ["".join(items) for items in itertools.product(*parts)]


def keyword_variations(
    keywords: str,
    suffix_start: int,
    suffix_end: int,
    substitutions: bool,
) -> list[str]:
    values: list[str] = []
    translation_options = {"A": "4", "E": "3", "I": "1", "O": "0", "S": "5", "T": "7"}
    for raw in re.split(r"[,\n]+", keywords):
        word = normalize_plate(raw)
        if not word:
            continue
        bases = {word, word[:5], word[:3], "".join(char for char in word if char not in "AEIOU")}
        if substitutions:
            bases.add("".join(translation_options.get(char, char) for char in word))
            for index, char in enumerate(word):
                replacement = translation_options.get(char)
                if replacement:
                    bases.add(f"{word[:index]}{replacement}{word[index + 1:]}")
        for base in sorted(bases):
            if not base:
                continue
            values.append(base)
            for suffix in _range(suffix_start, suffix_end):
                values.append(f"{base}{suffix}")
    return values


def generate_candidates(
    pattern_type: str,
    *,
    start: int = 0,
    end: int = 9,
    prefix: str = "",
    length: int = 4,
    template: str = "",
    word: str = "",
    keywords: str = "",
    substitutions: bool = False,
    max_length: int = 7,
) -> GenerationResult:
    numbers = _range(start, end)
    values: list[str]
    if pattern_type == "single_letter_numbers":
        values = [f"{letter}{number}" for letter in LETTERS for number in numbers]
    elif pattern_type == "number_letter":
        values = [f"{number}{letter}" for number in numbers for letter in LETTERS]
    elif pattern_type == "prefix_number":
        values = [f"{normalize_plate(prefix)}{number}" for number in numbers]
    elif pattern_type == "letter_number_letter":
        values = [f"{left}{number}{right}" for left in LETTERS for number in numbers for right in LETTERS]
    elif pattern_type == "repeated_digits":
        safe_length = max(1, min(length, max_length))
        values = [digit * safe_length for digit in DIGITS]
    elif pattern_type == "mirrored_numbers":
        safe_length = max(2, min(length, max_length))
        half_length = (safe_length + 1) // 2
        halves = (f"{number:0{half_length}d}" for number in range(10**half_length))
        values = [
            half + (half[:-1] if safe_length % 2 else half)[::-1]
            for half in halves
        ]
    elif pattern_type == "sequential_numbers":
        safe_length = max(2, min(length, max_length))
        values = ["".join(str((start_digit + offset) % 10) for offset in range(safe_length)) for start_digit in range(10)]
    elif pattern_type == "two_letters":
        values = [left + right for left in LETTERS for right in LETTERS]
    elif pattern_type == "custom_template":
        values = custom_template_values(template, word)
    elif pattern_type == "keyword_variations":
        values = keyword_variations(keywords, start, end, substitutions)
    else:
        raise ValueError("Unknown generator pattern.")
    return _finalize(values, max_length)
