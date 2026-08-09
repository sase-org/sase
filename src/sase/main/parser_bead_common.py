"""Shared helpers for bead argument parser definitions."""

from __future__ import annotations

import argparse
import shutil

from sase.markdown_wrap import MIN_PROSE_WRAP_WIDTH
from sase.vcs_log.dates import VcsLogDateError, parse_time_bound

WRAP_AUTO = -1


def bead_date_arg(value: str) -> str:
    """Validate a ``--since``/``--until`` DATE token for bead listings."""
    try:
        parse_time_bound(value)
    except VcsLogDateError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    return value


def nonnegative_int(value: str) -> int:
    """Parse a non-negative integer for an argparse option."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def wrap_width(value: str) -> int | None:
    """Parse ``--wrap``: integer width, ``auto``, ``none``, or ``0``."""
    normalized = value.lower()
    if normalized == "auto":
        return WRAP_AUTO
    if normalized in {"none", "0"}:
        return None
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"must be an integer >= {MIN_PROSE_WRAP_WIDTH}, 'auto', 'none', or 0"
        ) from None
    if parsed < MIN_PROSE_WRAP_WIDTH:
        raise argparse.ArgumentTypeError(
            f"must be an integer >= {MIN_PROSE_WRAP_WIDTH}, 'auto', 'none', or 0"
        )
    return parsed


def resolve_wrap_width(value: int | None) -> int | None:
    """Resolve a parsed ``--wrap`` token into a concrete width or ``None``."""
    if value is None:
        return None
    if value == WRAP_AUTO:
        return max(
            shutil.get_terminal_size(fallback=(80, 24)).columns,
            MIN_PROSE_WRAP_WIDTH,
        )
    return value
