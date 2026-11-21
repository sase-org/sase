"""Shared helpers for the ACE-run retention split.

The names here are public so the sibling ``agent_artifact_run_retention_*``
modules can import them without touching a ``_``-prefixed symbol across
files. Each helper keeps the behavior the former monolithic
:mod:`sase.core.agent_artifact_run_retention` module used.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def normalized_path(path: Path | str) -> str:
    """Canonicalize *path* the way retention keys run directories."""

    if not path:
        return ""
    return str(Path(path).expanduser().resolve(strict=False))


def recent_month_names(now: datetime, keep_recent_months: int) -> tuple[str, ...]:
    """Sorted trailing ``YYYYMM`` month names kept whole by retention.

    Shared by the preview plan and the trash quarantine so both sides
    protect the same recent window.
    """

    count = max(1, keep_recent_months)
    year = now.year
    month = now.month
    names: list[str] = []
    for _ in range(count):
        names.append(f"{year:04d}{month:02d}")
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return tuple(sorted(names))


__all__ = [
    "normalized_path",
    "recent_month_names",
]
