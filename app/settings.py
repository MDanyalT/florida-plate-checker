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


def _path_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    path = Path(value).expanduser() if value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    flhsmv_url: str = os.getenv(
        "FLHSMV_URL",
        "https://services.flhsmv.gov/MVCheckPersonalPlate/PlateInquiryView.aspx",
    )
    database_path: Path = _path_env("DATABASE_PATH", PROJECT_ROOT / "data" / "plates.db")
    headless: bool = _bool_env("HEADLESS", False)
    min_delay_seconds: float = _float_env("MIN_DELAY_SECONDS", 5.0)
    max_delay_seconds: float = _float_env("MAX_DELAY_SECONDS", 10.0)
    navigation_timeout_ms: int = _int_env("NAVIGATION_TIMEOUT_MS", 45_000)
    max_retries: int = _int_env("MAX_RETRIES", 3)
    max_batch_size: int = min(_int_env("MAX_BATCH_SIZE", 5), 5)
    max_plate_length: int = _int_env("MAX_PLATE_LENGTH", 7)
    max_candidates_per_run: int = _int_env("MAX_CANDIDATES_PER_RUN", 500)
    large_run_confirmation_threshold: int = _int_env("LARGE_RUN_CONFIRMATION_THRESHOLD", 100)
    max_upload_bytes: int = _int_env("MAX_UPLOAD_BYTES", 2 * 1024 * 1024)
    debug_directory: Path = _path_env(
        "DEBUG_DIRECTORY", PROJECT_ROOT / "plate_checker_debug"
    )


settings = Settings()
