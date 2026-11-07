import pytest

from app.generator import (
    MAX_PREVIEW_COMBINATIONS,
    estimate_generation,
    generate_candidates,
    idea_variations,
)


def slots(*items):
    return list(items)


def test_fixed_prefix_with_two_digits() -> None:
    pattern = slots({"kind": "fixed", "value": "SUN"}, {"kind": "digit"}, {"kind": "digit"})
    result = generate_candidates("pattern_builder", slots=pattern)
    assert result.candidates[:3] == ["SUN00", "SUN01", "SUN02"]
    assert len(result.candidates) == 100
    estimate = estimate_generation("pattern_builder", slots=pattern)
    assert estimate["exact"] is True and estimate["count"] == 100


def test_independent_letter_and_digits() -> None:
    pattern = slots({"kind": "letter"}, {"kind": "digit"}, {"kind": "digit"})
    assert estimate_generation("pattern_builder", slots=pattern)["count"] == 26 * 100


def test_linked_positions_repeat_values() -> None:
    mirror = slots({"kind": "digit"}, {"kind": "digit"}, {"kind": "digit", "link": 1}, {"kind": "digit", "link": 0})
    result = generate_candidates("pattern_builder", slots=mirror)
    assert len(result.candidates) == 100
    assert "1221" in result.candidates and "1231" not in result.candidates


def test_custom_sets_and_optional_positions_dedupe() -> None:
    pattern = slots({"kind": "custom", "value": "aab"}, {"kind": "custom", "value": "AB", "optional": True})
    result = generate_candidates("pattern_builder", slots=pattern)
    # A, B, AA, AB, BA, BB (custom set duplicates removed; optional blank adds A and B)
    assert sorted(result.candidates) == ["A", "AA", "AB", "B", "BA", "BB"]


def test_optional_duplicates_are_counted_exactly() -> None:
    pattern = slots({"kind": "letter"}, {"kind": "letter", "optional": True}, {"kind": "letter", "optional": True})
    estimate = estimate_generation("pattern_builder", slots=pattern)
    assert estimate["exact"] is True
    assert estimate["count"] == 26 + 26**2 + 26**3
    assert estimate["duplicates"] == 676


def test_overlength_combinations_are_excluded_from_count() -> None:
    pattern = slots({"kind": "fixed", "value": "SUNNY"}, {"kind": "digit"}, {"kind": "digit", "optional": True}, {"kind": "digit", "optional": True})
    estimate = estimate_generation("pattern_builder", slots=pattern, max_length=7)
    assert estimate["count"] == 10 + 100
    assert estimate["rejected"] == 1000


def test_huge_patterns_return_bounded_estimate() -> None:
    pattern = [{"kind": "alnum"}] * 5
    estimate = estimate_generation("pattern_builder", slots=pattern)
    assert estimate["exact"] is False and estimate["too_large"] is True
    assert estimate["count"] == 36**5 > MAX_PREVIEW_COMBINATIONS
    with pytest.raises(ValueError):
        generate_candidates("pattern_builder", slots=pattern)


def test_invalid_patterns_are_rejected() -> None:
    with pytest.raises(ValueError):
        generate_candidates("pattern_builder", slots=[])
    with pytest.raises(ValueError):
        generate_candidates("pattern_builder", slots=[{"kind": "digit", "link": 0}])
    with pytest.raises(ValueError):
        generate_candidates("pattern_builder", slots=[{"kind": "custom", "value": "!!"}])


def test_preset_counts_match_generation() -> None:
    for pattern, kwargs in [
        ("prefix_number", {"prefix": "SUN", "start": 0, "end": 99}),
        ("single_letter_numbers", {"start": 0, "end": 9}),
        ("letter_number_letter", {"start": 1, "end": 3}),
        ("mirrored_numbers", {"length": 5}),
        ("two_letters", {}),
        ("custom_template", {"template": "{L}{NN}"}),
    ]:
        estimate = estimate_generation(pattern, **kwargs)
        assert estimate["count"] == len(generate_candidates(pattern, **kwargs).candidates)


def test_preset_too_large_is_refused() -> None:
    assert estimate_generation("letter_number_letter", start=0, end=9999)["too_large"] is True
    with pytest.raises(ValueError):
        generate_candidates("letter_number_letter", start=0, end=9999)


def test_plate_ideas_are_deterministic_and_fit() -> None:
    first = generate_candidates("plate_ideas", word="Sunny Days", idea_options=["similar", "shorter", "numbers", "substitutions"])
    second = generate_candidates("plate_ideas", word="Sunny Days", idea_options=["similar", "shorter", "numbers", "substitutions"])
    assert first.candidates == second.candidates
    assert all(len(plate) <= 7 for plate in first.candidates)
    assert "SUNNY" in first.candidates and "DAYS" in first.candidates


def test_plate_idea_options() -> None:
    assert "4EVER" in idea_variations("forever", ["substitutions"])
    assert "SNNY" in idea_variations("sunny", ["shorter"])
    assert "SUNNY7" in idea_variations("sunny", ["numbers"])
    surprise_a = idea_variations("beach", ["surprise"], seed=1)
    assert surprise_a == idea_variations("beach", ["surprise"], seed=1)
    assert surprise_a != idea_variations("beach", ["surprise"], seed=2)
    with pytest.raises(ValueError):
        idea_variations("   ", ["similar"])
