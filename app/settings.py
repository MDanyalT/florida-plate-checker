"""Environment-backed configuration with conservative local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


SPEED_PROFILES: dict[str, dict[str, float | int]] = {
    "conservative": {
        "delay_min": 5.0,
        "delay_max": 10.0,
        "result_timeout": 45.0,
        "retry_delay": 3.0,
        "max_retries": 3,
    },
    "balanced": {
        "delay_min": 3.0,
        "delay_max": 6.0,
        "result_timeout": 30.0,
        "retry_delay": 2.0,
        "max_retries": 3,
    },
    "faster": {
        "delay_min": 2.0,
        "delay_max": 4.0,
        "result_timeout": 25.0,
        "retry_delay": 1.5,
        "max_retries": 2,
    },
}
CHECK_SPEED_PROFILE = os.getenv("CHECK_SPEED_PROFILE", "conservative").strip().lower()
if CHECK_SPEED_PROFILE not in SPEED_PROFILES:
    CHECK_SPEED_PROFILE = "conservative"
PROFILE_DEFAULTS = SPEED_PROFILES[CHECK_SPEED_PROFILE]


def _float_env_with_legacy(name: str, legacy_name: str, default: float) -> float:
    if os.getenv(name):
        return _float_env(name, default)
    return _float_env(legacy_name, default)


def _path_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    path = Path(value).expanduser() if value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


DATA_DIRECTORY = _path_env("DATA_DIRECTORY", PROJECT_ROOT / "user_data")


def _database_path() -> Path:
    """Use the new data folder while recognizing the former default setting."""

    configured = os.getenv("DATABASE_PATH", "").strip()
    if not configured or Path(configured) == Path("data/plates.db"):
        return DATA_DIRECTORY / "plates.db"
    return _path_env("DATABASE_PATH", DATA_DIRECTORY / "plates.db")


def _debug_path() -> Path:
    configured = os.getenv("DEBUG_DIRECTORY", "").strip()
    if not configured or Path(configured) == Path("plate_checker_debug"):
        return DATA_DIRECTORY / "debug"
    return _path_env("DEBUG_DIRECTORY", DATA_DIRECTORY / "debug")


@dataclass(frozen=True)
class Settings:
    flhsmv_url: str = os.getenv(
        "FLHSMV_URL",
        "https://services.flhsmv.gov/MVCheckPersonalPlate/PlateInquiryView.aspx",
    )
    data_directory: Path = DATA_DIRECTORY
    database_path: Path = _database_path()
    legacy_database_path: Path = PROJECT_ROOT / "data" / "plates.db"
    exports_directory: Path = DATA_DIRECTORY / "exports"
    backups_directory: Path = DATA_DIRECTORY / "backups"
    runtime_directory: Path = PROJECT_ROOT / ".runtime"
    headless: bool = _bool_env("HEADLESS", False)
    development_mode: bool = _bool_env("DEVELOPMENT_MODE", False)
    check_speed_profile: str = CHECK_SPEED_PROFILE
    check_delay_min_seconds: float = _float_env_with_legacy(
        "CHECK_DELAY_MIN_SECONDS", "MIN_DELAY_SECONDS", float(PROFILE_DEFAULTS["delay_min"])
    )
    check_delay_max_seconds: float = _float_env_with_legacy(
        "CHECK_DELAY_MAX_SECONDS", "MAX_DELAY_SECONDS", float(PROFILE_DEFAULTS["delay_max"])
    )
    result_timeout_seconds: float = _float_env(
        "RESULT_TIMEOUT_SECONDS", float(PROFILE_DEFAULTS["result_timeout"])
    )
    retry_delay_seconds: float = _float_env(
        "RETRY_DELAY_SECONDS", float(PROFILE_DEFAULTS["retry_delay"])
    )
    navigation_timeout_ms: int = _int_env("NAVIGATION_TIMEOUT_MS", 45_000)
    max_retries: int = _int_env("MAX_RETRIES", int(PROFILE_DEFAULTS["max_retries"]))
    max_batch_size: int = min(_int_env("MAX_BATCH_SIZE", 5), 5)
    max_plate_length: int = _int_env("MAX_PLATE_LENGTH", 7)
    max_plates_per_run: int = _int_env(
        "MAX_PLATES_PER_RUN", _int_env("MAX_CANDIDATES_PER_RUN", 1000)
    )
    large_run_confirmation_threshold: int = _int_env("LARGE_RUN_CONFIRMATION_THRESHOLD", 100)
    max_upload_bytes: int = _int_env("MAX_UPLOAD_BYTES", 2 * 1024 * 1024)
    debug_directory: Path = _debug_path()

    @property
    def min_delay_seconds(self) -> float:
        """Compatibility alias for the CLI and older local configuration."""

        return self.check_delay_min_seconds

    @property
    def max_delay_seconds(self) -> float:
        return self.check_delay_max_seconds

    @property
    def max_candidates_per_run(self) -> int:
        return self.max_plates_per_run


settings = Settings()
