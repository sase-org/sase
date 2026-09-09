"""Scalar coercion and formatting helpers shared by fleet-agent modules."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sase.core.time import local_now


def mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def optional_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def float_or_none(*values: object) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value)
            except ValueError:
                continue
    return None


def int_or_none(*values: object) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip():
            try:
                return int(value)
            except ValueError:
                continue
    return None


def datetime_from_unix(*values: object) -> datetime | None:
    timestamp = float_or_none(*values)
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=local_now().tzinfo)
    except (OSError, OverflowError, ValueError):
        return None


def locator_id(locator: Mapping[str, Any]) -> str:
    try:
        return json.dumps(dict(locator), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(sorted((str(key), repr(value)) for key, value in locator.items()))


def raw_suffix(host_alias: str, key: str | None, summary_index: int) -> str:
    suffix_key = key or f"row-{summary_index + 1}"
    return f"fleet:{host_alias}:{suffix_key}"


def display_token(value: str) -> str:
    token = value.strip().replace("/", ":")
    return token or "fleet"
