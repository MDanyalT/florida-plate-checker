from app.plate_utils import analyze_candidates, normalize_plate, validate_plate


def test_normalization_preserves_internal_space_and_hyphen() -> None:
    assert normalize_plate("  go- fla  ") == "GO- FLA"


def test_validation_rejects_bad_characters_and_overlength() -> None:
    assert "Only letters" in (validate_plate("ABC!", 7) or "")
    assert "maximum" in (validate_plate("ABCDEFGH", 7) or "")
    assert validate_plate("ABC-123", 7) is None


def test_duplicate_removal_and_failures() -> None:
    report = analyze_candidates(["abc", " ABC ", "BAD!", "", "FLA-1"], 7)
    assert report.valid == ["ABC", "FLA-1"]
    assert report.duplicates == ["ABC"]
    assert [failure.normalized for failure in report.failures] == ["BAD!"]

