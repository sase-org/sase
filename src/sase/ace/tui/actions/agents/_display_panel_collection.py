"""Panel-group synchronization and border-title refresh helpers.

Compatibility facade: the implementation lives in smaller,
responsibility-focused modules. This module keeps the historical import path
so existing callers keep working.
"""

from __future__ import annotations

from ._display_panel_collection_reconcile import STICKY_PANEL_BRIDGE_S
from ._display_panel_collection_reconcile import (
    SessionStickyReconcileMixin,
)
from ._display_panel_collection_sticky import SessionStickyStoreMixin
from ._display_panel_collection_sync import PanelSyncMixin
from ._display_panel_collection_titles import PanelTitlesMixin


class PanelCollectionMixin(
    SessionStickyStoreMixin,
    SessionStickyReconcileMixin,
    PanelSyncMixin,
    PanelTitlesMixin,
):
    """Panel collection synchronization and title rendering helpers."""


__all__ = [
    "PanelCollectionMixin",
    "PanelSyncMixin",
    "PanelTitlesMixin",
    "SessionStickyReconcileMixin",
    "SessionStickyStoreMixin",
    "STICKY_PANEL_BRIDGE_S",
]
