"""Per-panel deck-view policies with anchor-preserving Main transitions.

``DeckPanelViewMixin`` stores the ``DeckViewPolicies`` for a deck panel and
applies Main policies through one view-change transition that keeps the
reader's card, block, offset, pin, and following in every direction. Files
policies are stored here; the Files probe honors them in files-engine.

The mixin is composed from three parts: stored policies
(:mod:`sase.ace.tui.widgets.decks.panel_view_policies`), read-only view
queries (:mod:`sase.ace.tui.widgets.decks.panel_view_queries`), and the
Main view-change transition
(:mod:`sase.ace.tui.widgets.decks.panel_view_transition`).
"""

from __future__ import annotations

from .panel_view_policies import DeckPanelViewPoliciesMixin
from .panel_view_queries import DeckPanelViewQueriesMixin
from .panel_view_transition import DeckPanelViewTransitionMixin

__all__ = ["DeckPanelViewMixin"]


class DeckPanelViewMixin(
    DeckPanelViewPoliciesMixin,
    DeckPanelViewQueriesMixin,
    DeckPanelViewTransitionMixin,
):
    """View policies, predicates, and the Main view-change transition."""
