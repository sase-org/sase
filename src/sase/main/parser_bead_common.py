"""Shared helpers for bead argument parser definitions."""

from __future__ import annotations

import argparse


def nonnegative_int(value: str) -> int:
    """Parse a non-negative integer for an argparse option."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed
