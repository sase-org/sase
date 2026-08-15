"""Strict positive-integer parsing shared by Launch Control scalar editors."""

from __future__ import annotations

import re

_POSITIVE_INTEGER_RE = re.compile(r"[0-9]+")


def parse_positive_base10(raw: str, *, empty: str, minimum: str) -> int:
    """Parse one unsigned, whitespace-free base-10 integer of at least one."""
    if not raw:
        raise ValueError(empty)
    if raw != raw.strip() or _POSITIVE_INTEGER_RE.fullmatch(raw) is None:
        raise ValueError("Use a whole base-10 number with no sign or spaces.")
    value = int(raw, 10)
    if value < 1:
        raise ValueError(minimum)
    return value


__all__ = ["parse_positive_base10"]
