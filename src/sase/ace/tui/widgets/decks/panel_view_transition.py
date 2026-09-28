"""Anchor-preserving Main view-change transition.

Transition third of :mod:`sase.ace.tui.widgets.decks.panel_view`: the
generation-guarded scroll/restore helpers and the stored-policy Main
view-change that keeps the reader's card, block, offset, pin, and
following in every direction.

This module is a facade: the implementation lives in
:mod:`sase.ace.tui.widgets.decks.panel_view_transition_restore` and
:mod:`sase.ace.tui.widgets.decks.panel_view_transition_deferred`.
"""

from __future__ import annotations

from .panel_view_transition_deferred import DeckPanelViewDeferredMixin
from .panel_view_transition_restore import DeckPanelViewRestoreMixin

__all__ = ["DeckPanelViewTransitionMixin"]


class DeckPanelViewTransitionMixin(
    DeckPanelViewRestoreMixin,
    DeckPanelViewDeferredMixin,
):
    """Main view-change transition with anchor-preserving restores."""
