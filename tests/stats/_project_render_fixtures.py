"""Pinned ProjectStatsView fixtures for renderer goldens.

Public facade: the fixture builders live in the sibling private modules
(`_project_render_base`, `_project_render_projects`, `_project_render_views`).
This module re-exports the public names so existing imports keep working.
"""

from __future__ import annotations

from tests.stats._project_render_base import (
    MACHINE,
    NOW,
    NOW_TS,
    RANGE,
    TZ,
    render_context,
)
from tests.stats._project_render_views import (
    all_projects_view,
    build_view,
    code_pending_view,
    empty_range_view,
    local_plans_view,
    one_project_view,
    repo_edge_view,
)

__all__ = [
    "MACHINE",
    "NOW",
    "NOW_TS",
    "RANGE",
    "TZ",
    "all_projects_view",
    "build_view",
    "code_pending_view",
    "empty_range_view",
    "local_plans_view",
    "one_project_view",
    "render_context",
    "repo_edge_view",
]
