"""AgentList mounting and selective panel-widget refresh helpers.

Compatibility facade: the implementation lives in smaller,
responsibility-focused modules. This module keeps the historical import path
so existing callers and tests keep working.
"""

from __future__ import annotations

from ._display_panel_widgets_keys import (
    panel_agents_match,
    panel_fold_inputs,
    panel_paint_key,
    panel_row_signature,
)
from ._display_panel_widgets_mount import PanelWidgetMountMixin
from ._display_panel_widgets_paint import PanelWidgetPaintMixin
from ._display_panel_widgets_refresh import PanelWidgetRefreshOrchestrationMixin


class PanelWidgetRefreshMixin(
    PanelWidgetMountMixin,
    PanelWidgetPaintMixin,
    PanelWidgetRefreshOrchestrationMixin,
):
    """Mount, remove, and repaint AgentList panel widgets."""


# Private alias kept for tests importing the historical helper location.
_panel_fold_inputs = panel_fold_inputs


__all__ = [
    "PanelWidgetMountMixin",
    "PanelWidgetPaintMixin",
    "PanelWidgetRefreshMixin",
    "PanelWidgetRefreshOrchestrationMixin",
    "_panel_fold_inputs",
    "panel_agents_match",
    "panel_fold_inputs",
    "panel_paint_key",
    "panel_row_signature",
]
