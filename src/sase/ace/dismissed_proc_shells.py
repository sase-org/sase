"""Deprecated alias for :mod:`sase.ace.dismissed_procs`.

Kept for importers not yet moved to the turn spelling; new code should
import from ``sase.ace.dismissed_procs``.
"""

from __future__ import annotations

from sase.ace.dismissed_procs import (
    SCHEMA_VERSION,
    _DISMISSED_NAMED_PROCS_FILE,
    load_dismissed_named_procs,
    load_dismissed_procs,
    prune_dismissed_named_procs,
    prune_dismissed_procs,
    record_dismissed_named_procs,
    record_dismissed_procs,
)

__all__ = [
    "SCHEMA_VERSION",
    "load_dismissed_named_procs",
    "load_dismissed_procs",
    "prune_dismissed_named_procs",
    "prune_dismissed_procs",
    "record_dismissed_named_procs",
    "record_dismissed_procs",
]
