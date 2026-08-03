#!/usr/bin/env python3
"""Build clean macOS and Windows ZIP releases without private local data."""

from __future__ import annotations

import argparse
import stat
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHARED_ROOT_FILES = (
    "app.py",
    "plate_checker.py",
    "requirements.txt",
    "README.md",
    "plates.example.txt",
    ".env.example",
)
MAC_LAUNCHERS = (
    "Setup Plate Research.command",
    "Open Plate Research.command",
    "Stop Plate Research.command",
    "Update Plate Research.command",
)
WINDOWS_LAUNCHERS = (
    "Setup Plate Research.bat",
    "Open Plate Research.bat",
    "Stop Plate Research.bat",
    "Update Plate Research.bat",
)


def shared_files() -> list[Path]:
    files = [PROJECT_ROOT / name for name in SHARED_ROOT_FILES]
    license_file = PROJECT_ROOT / "LICENSE"
    if license_file.exists():
        files.append(license_file)
    for directory in ("app", "templates", "static"):
        files.extend(
            path
            for path in sorted((PROJECT_ROOT / directory).rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        )
    return files


def add_file(archive: zipfile.ZipFile, path: Path, *, executable: bool = False) -> None:
    relative = path.relative_to(PROJECT_ROOT).as_posix()
    info = zipfile.ZipInfo(relative)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    mode = stat.S_IFREG | (0o755 if executable else 0o644)
    info.external_attr = mode << 16
    archive.writestr(info, path.read_bytes())


def build_archive(destination: Path, launchers: tuple[str, ...], *, macos: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    with zipfile.ZipFile(destination, "w") as archive:
        for path in shared_files():
            if not path.exists():
                raise FileNotFoundError(f"Required release file is missing: {path}")
            add_file(archive, path)
        for name in launchers:
            add_file(archive, PROJECT_ROOT / name, executable=macos)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=PROJECT_ROOT / "dist",
        help="Directory for the two release ZIP files (default: dist).",
    )
    args = parser.parse_args()
    output = args.output_directory.resolve()
    mac_zip = output / "Florida-Plate-Research-macOS.zip"
    windows_zip = output / "Florida-Plate-Research-Windows.zip"
    build_archive(mac_zip, MAC_LAUNCHERS, macos=True)
    build_archive(windows_zip, WINDOWS_LAUNCHERS, macos=False)
    print(f"Created {mac_zip}")
    print(f"Created {windows_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
