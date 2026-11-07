from app.generator import generate_candidates


def test_required_generators_produce_expected_examples() -> None:
    assert "A1000" in generate_candidates(
        "single_letter_numbers", start=1000, end=1000
    ).candidates
    assert "786A" in generate_candidates("number_letter", start=786, end=786).candidates
    assert generate_candidates(
        "prefix_number", prefix="FL", start=123, end=123
    ).candidates == ["FL123"]
    assert "T7A" in generate_candidates(
        "letter_number_letter", start=7, end=7
    ).candidates
    assert "777" in generate_candidates("repeated_digits", length=3).candidates
    assert "7887" in generate_candidates("mirrored_numbers", length=4).candidates
    assert "12345" in generate_candidates("sequential_numbers", length=5).candidates
    assert len(generate_candidates("two_letters").candidates) == 676


def test_custom_template_and_keyword_variations() -> None:
    custom = generate_candidates("custom_template", template="{WORD}{NN}", word="SUN")
    assert "SUN00" in custom.candidates
    assert "SUN99" in custom.candidates
    keywords = generate_candidates(
        "keyword_variations",
        keywords="COAST",
        start=7,
        end=7,
        substitutions=True,
    )
    assert "C0AST7" in keywords.candidates


def test_generator_rejects_overlength_without_truncating() -> None:
    result = generate_candidates(
        "prefix_number", prefix="TOOLONG", start=99, end=99, max_length=7
    )
    assert result.candidates == []
    assert any("TOOLONG99" in rejection for rejection in result.rejected)
