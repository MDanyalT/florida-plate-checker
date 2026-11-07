from app.settings import SPEED_PROFILES


def estimated_inter_batch_delay(plate_count: int, profile: str) -> tuple[float, float]:
    batches = (plate_count + 4) // 5
    waits = max(0, batches - 1)
    values = SPEED_PROFILES[profile]
    return waits * float(values["delay_min"]), waits * float(values["delay_max"])


def test_balanced_profile_reduces_mocked_wait_without_parallelism() -> None:
    conservative = estimated_inter_batch_delay(10, "conservative")
    balanced = estimated_inter_batch_delay(10, "balanced")
    assert conservative == (5.0, 10.0)
    assert balanced == (3.0, 6.0)
    assert balanced[0] < conservative[0]
    assert balanced[1] < conservative[1]
    assert SPEED_PROFILES["conservative"]["max_retries"] == 3
    assert SPEED_PROFILES["balanced"]["max_retries"] == 3


def test_faster_profile_remains_bounded_and_serial() -> None:
    faster = SPEED_PROFILES["faster"]
    assert float(faster["delay_min"]) > 0
    assert float(faster["delay_max"]) >= float(faster["delay_min"])
    assert int(faster["max_retries"]) >= 1
