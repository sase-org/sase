"""Small value coercion helpers for daemon lifecycle code."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any


def optional_path(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value.expanduser()
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return None


def command_value(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(shlex.split(value)) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(part) for part in value if str(part).strip())
    return ()


def positive_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result <= 0:
        return default
    return result


def int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
