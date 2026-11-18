"""Shared metadata and numeric conversions for typed chop admission."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

AXE_CHOP_SOURCE_SURFACE = "axe_chop"
UNIT_DISPATCH_METADATA_KEY = "unit_dispatch_metadata"


def unit_metadata(data: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = data.get(UNIT_DISPATCH_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and key and isinstance(value, Mapping):
            result[key] = value
    return result


def int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
