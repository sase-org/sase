"""Shared helpers for bead argument parser definitions."""

from __future__ import annotations

import argparse

from sase.markdown_wrap import (
    WRAP_AUTO,
    resolve_wrap_width,
    wrap_width,
)
from sase.vcs_log.dates import VcsLogDateError, parse_time_bound

__all__ = [
    "WRAP_AUTO",
    "bead_date_arg",
    "nonnegative_int",
    "resolve_wrap_width",
    "wrap_width",
]


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
