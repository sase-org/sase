"""Cached, memory-only zombie-plan views for the Beads pane.

The collector runs only in the Beads pane's deferred warmup worker. This
module preserves the original public import path while implementation lives
in focused, private modules.
"""

from __future__ import annotations

from ._zombie_report_cache import (
    cached_zombie_report,
    cached_zombie_verdict,
    force_zombie_refresh,
    should_resolve_zombie_report,
    warm_zombie_reports,
    zombie_report_cache,
)

__all__ = [
    "cached_zombie_report",
    "cached_zombie_verdict",
    "force_zombie_refresh",
    "should_resolve_zombie_report",
    "warm_zombie_reports",
    "zombie_report_cache",
]
