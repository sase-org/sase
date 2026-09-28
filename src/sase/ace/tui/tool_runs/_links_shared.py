"""Shared run-state helpers for the run-links split.

Public names in this private module are the only cross-module helpers:
both the suffix renderers and the matchers need the same verdict-bucket
and liveness reads. Everything else lives privately in its own module.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "is_live_run",
    "run_bucket",
]


def run_bucket(run: Any) -> str:
    """Return the verdict bucket for *run*, defaulting to live/undetermined."""

    verdict = getattr(run, "verdict", None)
    bucket = str(getattr(verdict, "bucket", "") or "")
    if bucket:
        return bucket
    state = str(getattr(run, "state", "") or "")
    if state in ("created", "running"):
        return "running"
    return "undetermined"


def is_live_run(run: Any) -> bool:
    """Return True when *run* is still created/running."""

    return str(getattr(run, "state", "") or "") in ("created", "running")
