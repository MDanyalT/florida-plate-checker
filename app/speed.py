"""User-selectable checking speed, stored locally next to the database.

The choice only changes pacing between batches and how long the checker waits
for a result. It never adds parallel browsers, more than five plates per form,
CAPTCHA solving, or any way around FLHSMV blocks.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from app.settings import SPEED_PROFILES, Settings

PREFERENCES_FILENAME = "preferences.json"

# Even an edited .env can't go below these: they keep a human-paced, serial run.
MIN_DELAY_FLOOR_SECONDS = 2.0
MIN_RESULT_TIMEOUT_SECONDS = 15.0
MIN_RETRY_DELAY_SECONDS = 1.0

SPEED_CHOICES: dict[str, dict[str, str]] = {
    "conservative": {
        "label": "Careful",
        "summary": "5–10 seconds between batches. The gentlest pace, best for long runs.",
    },
    "balanced": {
        "label": "Balanced",
        "summary": "3–6 seconds between batches. A good everyday choice.",
    },
    "faster": {
        "label": "Faster",
        "summary": "2–4 seconds between batches. Best for short lists.",
    },
}


def _preferences_path(config: Settings) -> Path:
    return config.data_directory / PREFERENCES_FILENAME


def saved_speed_profile(config: Settings) -> str | None:
    """Return the speed picked in the app, or None if none was saved."""

    try:
        data = json.loads(_preferences_path(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("check_speed") if isinstance(data, dict) else None
    return value if value in SPEED_PROFILES else None


def current_speed_profile(config: Settings) -> str:
    return saved_speed_profile(config) or config.check_speed_profile


def save_speed_profile(config: Settings, profile: str) -> None:
    if profile not in SPEED_PROFILES:
        raise ValueError(f"Unknown checking speed: {profile}")
    path = _preferences_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data["check_speed"] = profile
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)


def apply_safety_floors(config: Settings) -> Settings:
    delay_min = max(MIN_DELAY_FLOOR_SECONDS, config.check_delay_min_seconds)
    return replace(
        config,
        check_delay_min_seconds=delay_min,
        check_delay_max_seconds=max(delay_min, config.check_delay_max_seconds),
        result_timeout_seconds=max(MIN_RESULT_TIMEOUT_SECONDS, config.result_timeout_seconds),
        retry_delay_seconds=max(MIN_RETRY_DELAY_SECONDS, config.retry_delay_seconds),
        max_retries=max(1, config.max_retries),
        max_batch_size=max(1, min(5, config.max_batch_size)),
    )


def settings_for_profile(config: Settings, profile: str) -> Settings:
    """Settings with a profile's timing applied (and safety floors enforced)."""

    values = SPEED_PROFILES[profile]
    return apply_safety_floors(
        replace(
            config,
            check_speed_profile=profile,
            check_delay_min_seconds=float(values["delay_min"]),
            check_delay_max_seconds=float(values["delay_max"]),
            result_timeout_seconds=float(values["result_timeout"]),
            retry_delay_seconds=float(values["retry_delay"]),
            max_retries=int(values["max_retries"]),
        )
    )


def settings_for_run(config: Settings) -> Settings:
    """The settings a new checking run uses.

    A speed picked in the app wins over .env timing values; without one, the
    .env configuration applies exactly as before (still subject to the floors).
    """

    saved = saved_speed_profile(config)
    if saved is None:
        return apply_safety_floors(config)
    return settings_for_profile(config, saved)
