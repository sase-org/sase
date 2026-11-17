"""Helpers shared by more than one ``supervise_*`` module.

These stay public inside this already-private module so the supervise split
never imports a ``_``-prefixed name across modules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

TimeoutKind = Literal["total", "idle"]


def format_duration(seconds: float) -> str:
    if 0 < seconds < 1:
        return f"{seconds:g}s"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "TimeoutKind",
    "format_duration",
    "utc_now_iso",
]
