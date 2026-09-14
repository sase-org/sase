"""Shared filesystem and formatting helpers for disk-footprint code."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def iter_children(directory: Path) -> list[Path]:
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def tree_size(path: Path) -> int:
    measured = _du_size(path)
    if measured is not None:
        return measured
    return _tree_size_walk(path)


def _du_size(path: Path) -> int | None:
    if not path.exists():
        return 0
    try:
        result = subprocess.run(
            ["du", "-skx", "--", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    first = result.stdout.split(None, 1)[0] if result.stdout.strip() else ""
    try:
        return int(first) * 1024
    except ValueError:
        return None


def _tree_size_walk(path: Path) -> int:
    try:
        entry_stat = path.stat(follow_symlinks=False)
    except OSError:
        return 0
    if stat.S_ISLNK(entry_stat.st_mode):
        return 0
    if stat.S_ISREG(entry_stat.st_mode):
        return int(entry_stat.st_size)
    if not stat.S_ISDIR(entry_stat.st_mode):
        return 0
    return sum(_tree_size_walk(child) for child in iter_children(path))


def format_horizon_seconds(seconds: float) -> str:
    if seconds % 86_400 == 0:
        return f"{int(seconds // 86_400)}d"
    if seconds % 3_600 == 0:
        return f"{int(seconds // 3_600)}h"
    return f"{int(seconds)}s"


def format_bytes(value: int) -> str:
    """Format bytes for compact CLI rows."""

    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{int(amount)} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def resolve_soft(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        return os.path.commonpath((os.fspath(path), os.fspath(base))) == os.fspath(base)
    except ValueError:
        return False


__all__ = [
    "format_bytes",
    "format_horizon_seconds",
    "is_relative_to",
    "iter_children",
    "resolve_soft",
    "tree_size",
]
