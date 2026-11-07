"""Formatting helpers for hijack recovery panel content."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RESULT_PREFIX = "hijack:"


def diff_totals(record: Mapping[str, Any]) -> tuple[int, int, int]:
    files = insertions = deletions = 0
    diffs = record.get("repo_diffs")
    if isinstance(diffs, list):
        for entry in diffs:
            if not isinstance(entry, Mapping):
                continue
            files += int_value(entry.get("files_changed"))
            insertions += int_value(entry.get("insertions"))
            deletions += int_value(entry.get("deletions"))
    return files, insertions, deletions


def duration(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return ""
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


def age(value: object) -> str:
    from datetime import UTC, datetime

    if not isinstance(value, str):
        return ""
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        seconds = max(
            0, int((datetime.now(UTC) - stamp.astimezone(UTC)).total_seconds())
        )
    except (TypeError, ValueError, OverflowError):
        return ""
    return f"{max(1, seconds // 60)}m ago" if seconds >= 60 else "just now"


def text_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def int_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


__all__ = ["RESULT_PREFIX", "age", "diff_totals", "duration", "int_value", "text_value"]
