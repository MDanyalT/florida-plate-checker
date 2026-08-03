import csv

import plate_checker


def test_cli_still_saves_local_validation_results_without_opening_browser(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plates.txt").write_text("BAD!\n", encoding="utf-8")

    exit_code = plate_checker.main()

    with (tmp_path / "plate_results.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert exit_code == 0
    assert rows[0]["plate"] == "BAD!"
    assert rows[0]["status"] == "Invalid"
    assert (tmp_path / "checked_plates.txt").read_text().strip() == "BAD!"
