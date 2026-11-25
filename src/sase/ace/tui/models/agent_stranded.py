"""Cached, memory-only stranded-work views for Agents-tab rows.

The collector runs only in the Agents tab's deferred bead warmup worker. This
module preserves the original public import path while implementation lives in
private, focused modules.
"""

from __future__ import annotations

from ._agent_stranded_cache import (
    STRANDED_REPORT_CACHE_MISS as STRANDED_REPORT_CACHE_MISS,
    cached_stranded_report,
    cached_stranded_report_for_agent,
    force_stranded_refresh,
    should_resolve_stranded_report,
    stranded_project_key_for_agent,
    stranded_project_keys,
    stranded_report_resolution_reason,
    warm_stranded_work_reports,
)
from ._agent_stranded_surface import (
    cached_stranded_verdict_state,
    stranded_count_for_agents,
    stranded_snapshot_token,
    stranded_verdict_for_bead,
    surfaced_stranded_count,
    surfaced_stranded_leaves,
)
from ._agent_stranded_view import agent_stranded_view, stranded_leaf_verdict

__all__ = [
    "agent_stranded_view",
    "cached_stranded_report",
    "cached_stranded_report_for_agent",
    "cached_stranded_verdict_state",
    "force_stranded_refresh",
    "should_resolve_stranded_report",
    "stranded_count_for_agents",
    "stranded_leaf_verdict",
    "stranded_project_key_for_agent",
    "stranded_project_keys",
    "stranded_snapshot_token",
    "stranded_verdict_for_bead",
    "surfaced_stranded_count",
    "surfaced_stranded_leaves",
    "warm_stranded_work_reports",
]
