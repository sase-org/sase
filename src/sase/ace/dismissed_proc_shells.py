"""Deprecated alias for :mod:`sase.ace.dismissed_procs`.

Kept for importers not yet moved to the turn spelling; new code should
import from ``sase.ace.dismissed_procs``.
"""

from __future__ import annotations

from sase.ace.dismissed_procs import (
    SCHEMA_VERSION,
    _DISMISSED_PROC_SHELLS_FILE,
    load_dismissed_proc_shells,
    load_dismissed_procs,
    prune_dismissed_proc_shells,
    prune_dismissed_procs,
    record_dismissed_proc_shells,
    record_dismissed_procs,
)

__all__ = [
    "SCHEMA_VERSION",
    "load_dismissed_proc_shells",
    "load_dismissed_procs",
    "prune_dismissed_proc_shells",
    "prune_dismissed_procs",
    "record_dismissed_proc_shells",
    "record_dismissed_procs",
]
