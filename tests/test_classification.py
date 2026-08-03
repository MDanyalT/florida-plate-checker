from app.checker_service import classify_status


def test_negative_availability_is_checked_first() -> None:
    assert classify_status("NOT AVAILABLE") == "Not available"
    assert classify_status("This configuration is unavailable") == "Not available"


def test_all_classification_groups() -> None:
    assert classify_status("AVAILABLE") == "Available"
    assert classify_status("INVALID CONFIGURATION") == "Invalid"
    assert classify_status("ERROR TRY AGAIN") == "Error"
    assert classify_status("Unexpected wording") == "Unknown"

