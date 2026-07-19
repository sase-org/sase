"""Panel-widget helpers for the agent display mixin.

This compatibility module keeps the historical ``PanelsMixin`` import path
while the implementation lives in smaller, responsibility-focused modules.
"""

from __future__ import annotations

from ._display_panel_patches import PanelPatchMixin
from ._display_panel_refresh import PanelRefreshMixin
from ._display_panel_titles import (
    _PANEL_COUNT_STYLE,
    _PANEL_METRIC_LABELS,
    _PANEL_METRIC_STYLES,
    _PANEL_TRIBE_STYLE,
    _PANEL_NO_TRIBE_STYLE,
    AgentPanelCounts,
    agent_panel_border_title,
    agent_panel_counts,
)

_AgentPanelCounts = AgentPanelCounts
_agent_panel_border_title = agent_panel_border_title
_agent_panel_counts = agent_panel_counts


class PanelsMixin(PanelRefreshMixin, PanelPatchMixin):
    """Aggregate panel refresh/layout and incremental patch helpers."""


__all__ = [
    "PanelsMixin",
    "_AgentPanelCounts",
    "_PANEL_COUNT_STYLE",
    "_PANEL_METRIC_LABELS",
    "_PANEL_METRIC_STYLES",
    "_PANEL_TRIBE_STYLE",
    "_PANEL_NO_TRIBE_STYLE",
    "_agent_panel_border_title",
    "_agent_panel_counts",
]
