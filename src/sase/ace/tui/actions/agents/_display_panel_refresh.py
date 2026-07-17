"""Compatibility facade for panel collection and widget refresh helpers."""

from __future__ import annotations

from ._display_panel_collection import PanelCollectionMixin
from ._display_panel_layout import PanelLayoutMixin
from ._display_panel_widgets import PanelWidgetRefreshMixin


class PanelRefreshMixin(
    PanelCollectionMixin,
    PanelWidgetRefreshMixin,
    PanelLayoutMixin,
):
    """Aggregate panel collection, widget refresh, sizing, and focus helpers."""
