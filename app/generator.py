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
    slots: object = None,
    idea_options: tuple[str, ...] | list[str] | set[str] = (),
    seed: int = 0,
) -> GenerationResult:
    values: list[str]
    if pattern_type == "pattern_builder":
        parsed = parse_slots(slots)
        if pattern_raw_count(parsed) > MAX_PREVIEW_COMBINATIONS:
            raise ValueError(
                f"This pattern has more than {MAX_PREVIEW_COMBINATIONS:,} combinations. "
                "Fix a few more positions or narrow the allowed characters."
            )
        return _finalize(pattern_values(parsed), max_length)
    if pattern_type == "plate_ideas":
        return _finalize(idea_variations(word, idea_options, max_length=max_length, seed=seed), max_length)

    numbers = _range(start, end)
    raw = raw_pattern_count(
        pattern_type, start=start, end=end, length=length, template=template, max_length=max_length
    )
    if raw is not None and raw > MAX_PREVIEW_COMBINATIONS:
        raise ValueError(
            f"This pattern would create {raw:,} combinations (limit {MAX_PREVIEW_COMBINATIONS:,}). "
            "Use a smaller number range."
        )
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


# ---------------------------------------------------------------------------
# Visual pattern builder
# ---------------------------------------------------------------------------

# Hard ceiling on how many raw combinations a single preview may enumerate.
# Anything larger is reported as a bounded estimate and must be narrowed first.
MAX_PREVIEW_COMBINATIONS = 300_000

SLOT_CHOICES: dict[str, str] = {
    "letter": LETTERS,
    "digit": DIGITS,
    "alnum": LETTERS + DIGITS,
}


@dataclass(frozen=True)
class PatternSlot:
    """One position (or fixed block) of a builder pattern.

    ``kind`` is one of ``fixed``, ``letter``, ``digit``, ``alnum`` or ``custom``.
    ``link`` points at an earlier slot index whose value this slot repeats.
    ``optional`` slots may also be left blank.
    """

    kind: str
    value: str = ""
    optional: bool = False
    link: int | None = None

    def choices(self) -> list[str]:
        if self.kind == "fixed":
            options = [normalize_plate(self.value)]
        elif self.kind == "custom":
            cleaned = "".join(dict.fromkeys(c for c in self.value.upper() if c.isalnum()))
            if not cleaned:
                raise ValueError("A custom position needs at least one letter or number.")
            options = list(cleaned)
        elif self.kind in SLOT_CHOICES:
            options = list(SLOT_CHOICES[self.kind])
        else:
            raise ValueError(f"Unknown position type: {self.kind}.")
        if self.optional and "" not in options:
            options = [*options, ""]
        return options


def parse_slots(raw_slots: object) -> list[PatternSlot]:
    """Validate the JSON slot list submitted by the pattern builder."""

    if not isinstance(raw_slots, list) or not raw_slots:
        raise ValueError("Add at least one position to your pattern.")
    if len(raw_slots) > 12:
        raise ValueError("Patterns can have at most 12 positions.")
    slots: list[PatternSlot] = []
    for index, raw in enumerate(raw_slots):
        if not isinstance(raw, dict):
            raise ValueError("Pattern positions are malformed.")
        kind = str(raw.get("kind", "")).strip()
        value = str(raw.get("value", ""))
        link_raw = raw.get("link")
        link: int | None = None
        if link_raw not in (None, "", -1, "-1"):
            try:
                link = int(link_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise ValueError("A linked position is malformed.") from exc
            if not 0 <= link < index:
                raise ValueError("A position can only repeat an earlier position.")
            if slots[link].link is not None:
                link = slots[link].link
        if kind == "fixed":
            text = normalize_plate(value)
            if not text:
                raise ValueError(f"Position {index + 1} is fixed text but is empty.")
            error = validate_plate(text, 99)
            if error:
                raise ValueError(f"Position {index + 1}: {error}")
        slot = PatternSlot(kind=kind, value=value, optional=bool(raw.get("optional")), link=link)
        if link is None:
            slot.choices()  # validates kind/custom characters early
        slots.append(slot)
    return slots


def pattern_raw_count(slots: list[PatternSlot]) -> int:
    """Upper bound: every independent position multiplied together."""

    total = 1
    for slot in slots:
        if slot.link is None:
            total *= len(slot.choices())
    return total


def pattern_values(slots: list[PatternSlot]) -> list[str]:
    independent = [index for index, slot in enumerate(slots) if slot.link is None]
    choice_lists = [slots[index].choices() for index in independent]
    values: list[str] = []
    for combo in itertools.product(*choice_lists):
        chosen = dict(zip(independent, combo))
        values.append(
            "".join(chosen[index] if slot.link is None else chosen[slot.link] for index, slot in enumerate(slots))
        )
    return values


def describe_slots(slots: list[PatternSlot]) -> str:
    """Compact human-readable summary, e.g. ``SUN + digit + digit``."""

    labels = {
        "letter": "any letter",
        "digit": "any digit",
        "alnum": "any letter or digit",
    }
    parts: list[str] = []
    for index, slot in enumerate(slots):
        if slot.link is not None:
            label = f"same as position {slot.link + 1}"
        elif slot.kind == "fixed":
            label = normalize_plate(slot.value)
        elif slot.kind == "custom":
            label = f"one of {''.join(dict.fromkeys(slot.value.upper()))}"
        else:
            label = labels[slot.kind]
        if slot.optional:
            label += " (optional)"
        parts.append(label)
    return " + ".join(parts)


# ---------------------------------------------------------------------------
# Plate ideas (deterministic, rule-based — no AI involved)
# ---------------------------------------------------------------------------

IDEA_OPTIONS = ("similar", "shorter", "numbers", "substitutions", "surprise")

LEET = {"A": "4", "E": "3", "I": "1", "O": "0", "S": "5", "T": "7", "B": "8", "G": "6"}
SOUND_ALIKES = (
    ("THROUGH", "THRU"),
    ("NIGHT", "NITE"),
    ("LIGHT", "LITE"),
    ("GREAT", "GR8"),
    ("LOVE", "LUV"),
    ("WAIT", "W8"),
    ("LATE", "L8"),
    ("FOR", "4"),
    ("ATE", "8"),
    ("TOO", "2"),
    ("TWO", "2"),
    ("YOU", "U"),
    ("ARE", "R"),
    ("SEE", "C"),
    ("SEA", "C"),
    ("ONE", "1"),
    ("WON", "1"),
    ("WHY", "Y"),
    ("AND", "N"),
    ("EYE", "I"),
    ("TO", "2"),
    ("BE", "B"),
    ("OH", "O"),
    ("EX", "X"),
    ("CK", "K"),
    ("PH", "F"),
)
# Popular plate numbers plus Florida area codes, used by the "Add numbers" option.
IDEA_NUMBERS = (
    "1", "2", "3", "7", "8", "9", "11", "13", "21", "22", "23", "24", "33", "77", "88", "99",
    "305", "321", "352", "386", "407", "561", "727", "772", "786", "813", "850", "863", "904", "941", "954",
)


def _words(text: str) -> list[str]:
    return [word for word in re.split(r"[^A-Z0-9]+", text.upper()) if word]


def _no_vowels(word: str) -> str:
    if len(word) <= 2:
        return word
    return word[0] + "".join(char for char in word[1:] if char not in "AEIOU")


def _collapse_doubles(word: str) -> str:
    return re.sub(r"(.)\1+", r"\1", word)


def _similar(words: list[str]) -> list[str]:
    compact = "".join(words)
    values = [compact]
    if len(words) > 1:
        values += [" ".join(words), "-".join(words), *words]
    values += [f"MY{compact}", f"{compact}S", f"{compact}Z", f"{compact}FL", f"FL{compact}", f"I{compact}"]
    if compact and compact[-1] not in "AEIOUY":
        values.append(f"{compact}Y")
    return values


def _shorter(words: list[str], max_length: int) -> list[str]:
    compact = "".join(words)
    values = [_no_vowels(compact), _collapse_doubles(compact), "".join(_no_vowels(w) for w in words)]
    if len(words) > 1:
        values.append("".join(word[0] for word in words))
        values.append(words[0] + "".join(word[0] for word in words[1:]))
        values.append("".join(word[:2] for word in words))
        values.append("".join(word[:3] for word in words))
    for size in range(3, max_length + 1):
        if size < len(compact):
            values.append(compact[:size])
    return values


def _sound_alike(word: str) -> str:
    for original, replacement in SOUND_ALIKES:
        word = word.replace(original, replacement)
    return word


def _substitutions(base: str) -> list[str]:
    values: list[str] = []
    for word, replacement in SOUND_ALIKES:
        if word in base:
            values.append(base.replace(word, replacement))
    values.append(_sound_alike(base))
    for index, char in enumerate(base):
        if char in LEET:
            values.append(f"{base[:index]}{LEET[char]}{base[index + 1:]}")
    values.append("".join(LEET.get(char, char) for char in base))
    return [value for value in values if value != base]


def idea_variations(
    text: str,
    options: set[str] | list[str] | tuple[str, ...],
    *,
    max_length: int = 7,
    seed: int = 0,
) -> list[str]:
    """Rule-based plate ideas for a word, name, phrase, or comma-separated themes."""

    chosen = set(options) or {"similar"}
    unknown = chosen - set(IDEA_OPTIONS)
    if unknown:
        raise ValueError("Unknown idea option.")
    phrases = [phrase for phrase in re.split(r"[,\n;]+", text) if _words(phrase)]
    if not phrases:
        raise ValueError("Type a word, name, or phrase to get ideas.")
    if len(phrases) > 10:
        raise ValueError("Use up to 10 words or phrases at a time.")

    surprise = "surprise" in chosen
    active = set(IDEA_OPTIONS[:4]) if surprise else chosen
    values: list[str] = []
    for phrase in phrases:
        words = _words(phrase)
        compact = "".join(words)
        bases = [compact]
        if "similar" in active:
            values += _similar(words)
        else:
            values.append(compact)
        if "shorter" in active:
            short = _shorter(words, max_length)
            values += short
            bases += [value for value in short if 2 <= len(value) <= max_length - 1]
        if "substitutions" in active:
            for base in list(dict.fromkeys(bases)):
                values += _substitutions(base)
            sounded = [_sound_alike(word) for word in words]
            values.append("".join(sounded))
            values.append("".join(_no_vowels(word) if len(word) > 3 else word for word in sounded))
            if len(words) > 1:
                values += [word for word, original in zip(sounded, words) if word != original]
        if "numbers" in active:
            for base in list(dict.fromkeys(bases)):
                for number in IDEA_NUMBERS:
                    if len(base) + len(number) <= max_length:
                        values.append(f"{base}{number}")
                if len(base) < max_length:
                    values += [f"{number}{base}" for number in ("1", "2", "4")]

    if surprise:
        import random

        fitting = [value for value in dict.fromkeys(values) if len(value) <= max_length]
        rng = random.Random(f"{normalize_plate(text)}|{seed}")
        rng.shuffle(fitting)
        return fitting[:48]
    return values


# ---------------------------------------------------------------------------
# Counting before generation
# ---------------------------------------------------------------------------


def raw_pattern_count(
    pattern_type: str,
    *,
    start: int = 0,
    end: int = 9,
    length: int = 4,
    template: str = "",
    max_length: int = 7,
) -> int | None:
    """Fast arithmetic upper bound for preset patterns (None when not cheap to know)."""

    span = abs(end - start) + 1
    if pattern_type == "single_letter_numbers" or pattern_type == "number_letter":
        return 26 * span
    if pattern_type == "prefix_number":
        return span
    if pattern_type == "letter_number_letter":
        return 26 * 26 * span
    if pattern_type in {"repeated_digits", "sequential_numbers"}:
        return 10
    if pattern_type == "mirrored_numbers":
        safe_length = max(2, min(length, max_length))
        return 10 ** ((safe_length + 1) // 2)
    if pattern_type == "two_letters":
        return 676
    if pattern_type == "custom_template":
        total = 1
        for match in PLACEHOLDER.finditer(template.upper()):
            total *= {"L": 26, "N": 10, "NN": 100, "WORD": 1}[match.group(1)]
        return total
    return None


def _spread_examples(values: list[str], limit: int = 8) -> list[str]:
    if len(values) <= limit:
        return list(values)
    head = values[:3]
    rest = limit - len(head)
    step = (len(values) - 3) / rest
    return head + [values[3 + int(step * index) + int(step) - 1] for index in range(rest)]


def estimate_generation(pattern_type: str, **kwargs: object) -> dict[str, object]:
    """Count combinations before generating, with examples.

    Returns an exact count (after validation and duplicate removal) whenever the
    pattern can be enumerated within ``MAX_PREVIEW_COMBINATIONS``; otherwise a
    clearly-flagged upper bound.
    """

    max_length = int(kwargs.get("max_length", 7))  # type: ignore[arg-type]
    raw: int | None = None
    summary = ""
    if pattern_type == "pattern_builder":
        parsed = parse_slots(kwargs.get("slots"))
        raw = pattern_raw_count(parsed)
        summary = describe_slots(parsed)
        lengths = [0]
        for slot in parsed:
            choice_lengths = {len(choice) for choice in (parsed[slot.link] if slot.link is not None else slot).choices()}
            lengths = [a + b for a in lengths for b in choice_lengths]
        if min(lengths) > max_length:
            return {
                "exact": True, "count": 0, "raw": raw, "too_large": False, "examples": [],
                "rejected": raw, "duplicates": 0, "summary": summary,
                "error": f"Every combination is longer than {max_length} characters.",
            }
    elif pattern_type != "plate_ideas":
        raw = raw_pattern_count(
            pattern_type,
            start=int(kwargs.get("start", 0)),  # type: ignore[arg-type]
            end=int(kwargs.get("end", 9)),  # type: ignore[arg-type]
            length=int(kwargs.get("length", 4)),  # type: ignore[arg-type]
            template=str(kwargs.get("template", "")),
            max_length=max_length,
        )
    if raw is not None and raw > MAX_PREVIEW_COMBINATIONS:
        return {
            "exact": False, "count": raw, "raw": raw, "too_large": True, "examples": [],
            "rejected": 0, "duplicates": 0, "summary": summary,
            "error": f"Up to {raw:,} combinations — the limit is {MAX_PREVIEW_COMBINATIONS:,}. Narrow the pattern to preview it.",
        }
    result = generate_candidates(pattern_type, **kwargs)  # type: ignore[arg-type]
    return {
        "exact": True,
        "count": len(result.candidates),
        "raw": result.total_before_validation,
        "too_large": False,
        "examples": _spread_examples(result.candidates),
        "rejected": len(result.rejected),
        "duplicates": result.duplicate_count,
        "summary": summary,
        "error": None,
    }
