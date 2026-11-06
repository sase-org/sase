"""Small value conversions shared by private hijack preview adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def integer(value: object) -> int:
    return value if type(value) is int else 0


def string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def string_list(value: object) -> list[str]:
    return (
        [item for item in value if isinstance(item, str) and item]
        if isinstance(value, list)
        else []
    )


def duration(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return ""
    seconds = int(value)
    if seconds < 60:
        return "<1m"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, remaining = divmod(minutes, 60)
    return f"{hours}h {remaining}m" if remaining else f"{hours}h"


def diff_totals(record: Mapping[str, Any]) -> tuple[int, int, int]:
    diffs = record.get("repo_diffs")
    files = insertions = deletions = 0
    if isinstance(diffs, list):
        for entry in diffs:
            if not isinstance(entry, Mapping):
                continue
            files += integer(entry.get("files_changed"))
            insertions += integer(entry.get("insertions"))
            deletions += integer(entry.get("deletions"))
    return files, insertions, deletions


def concrete_model_target(record: Mapping[str, Any]) -> str | None:
    provider = string(record.get("provider"))
    model = string(record.get("model"))
    if not model:
        return None
    concrete = model if "/" in model or not provider else f"{provider}/{model}"
    effort = string(record.get("effort"))
    if effort and not concrete.endswith(f"@{effort}"):
        concrete += f"@{effort}"
    return concrete
