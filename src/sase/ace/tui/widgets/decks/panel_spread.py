"""Spread versus paged mode state for ``DeckPanel``.

This module preserves the public import path while keeping implementation
concerns in focused private modules.
"""

from __future__ import annotations

from ._panel_spread_files_scroll import PanelSpreadFilesScrollMixin


class DeckPanelSpreadMixin(PanelSpreadFilesScrollMixin):
    """Per-panel, per-deck spread/paged decision and scroll tracking."""


__all__ = ["DeckPanelSpreadMixin"]
