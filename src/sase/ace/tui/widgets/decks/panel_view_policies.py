"""Stored view policies for deck panels.

Policy-storage third of
:mod:`sase.ace.tui.widgets.decks.panel_view`: keeps the
``DeckViewPolicies`` for a panel and applies user-initiated changes through
the Main or Files view-change paths owned by the sibling mixins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .model import DeckId, DeckView, DeckViewPolicies

__all__ = ["DeckPanelViewPoliciesMixin"]


class DeckPanelViewPoliciesMixin:
    """Stored view policies and chrome sync for a deck panel."""

    _deck: DeckId
    _view_policies: DeckViewPolicies
    _view_generation: int
    _pending_view_anchor: tuple[object, Any, int] | None
    _view_cycle_available: bool
    _files_spread_pending: bool
    _files_spread_blocked: bool

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def _init_view_state(self) -> None:
        self._view_policies = DeckViewPolicies()
        self._view_generation = 0
        self._pending_view_anchor = None
        self._view_cycle_available = False
        # Owned here so resolved_view() works before files-engine populates
        # them per subject; files-engine is the only writer afterwards.
        self._files_spread_pending = False
        self._files_spread_blocked = False

    # -- Policy storage -------------------------------------------------

    def view_policy(self, deck: DeckId) -> DeckView:
        """Return the stored policy for ``deck`` (other decks are AUTO)."""
        try:
            policies = self._view_policies
        except Exception:
            return DeckView.AUTO
        try:
            if deck is DeckId.MAIN:
                return policies.main
            if deck is DeckId.FILES:
                return policies.files
        except Exception:
            pass
        return DeckView.AUTO

    def sync_view_policies(self, policies: DeckViewPolicies) -> bool:
        """Store ``policies``; True when the shown deck's policy changed."""
        try:
            old = self._view_policies.for_deck(self._deck)
        except Exception:
            old = DeckView.AUTO
        try:
            self._view_policies = policies
        except Exception:
            return False
        try:
            return bool(policies.for_deck(self._deck) != old)
        except Exception:
            return False

    def set_view_policy(
        self, deck: DeckId, view: DeckView, *, user_initiated: bool = False
    ) -> None:
        """Store ``view`` for ``deck``, applying it when that deck is shown.

        ``user_initiated`` marks a P/palette change so the Files path can
        post the one-shot media toast; subject changes never set it.
        """
        try:
            policies = self._view_policies
        except Exception:
            self._init_view_state()
            policies = self._view_policies
        # Raises ValueError for Tools and Files PAGE_BLOCKS, like the model.
        self._view_policies = policies.with_deck(deck, view)
        if deck is not self._deck:
            self._refresh_view_chrome()
            return
        if deck is DeckId.MAIN:
            try:
                document = self._main_document
            except Exception:
                document = None
            if (
                document is None
                or getattr(document, "partial", False)
                or not getattr(document, "cards", ())
            ):
                # Partial or empty: store only; the next full document
                # applies the policy through the normal deciders.
                self._refresh_view_chrome()
                return
            self._apply_main_view_change()
            return
        # FILES applies through the files-engine view-change path, which
        # keeps the page and offset via the existing Files transition.
        try:
            self._apply_files_view_change(user_initiated=user_initiated)  # type: ignore[attr-defined]
        except Exception:
            self._refresh_view_chrome()

    def _refresh_view_chrome(self) -> None:
        """Refresh chrome and cached predicates without raising."""
        try:
            self.refresh_chrome()
        except Exception:
            pass
        try:
            self._sync_block_navigable()
        except Exception:
            pass
        try:
            self._sync_block_rail()
        except Exception:
            pass

    def _sync_block_navigable(self) -> None:
        """Refresh the block predicate, then the view-cycle predicate.

        Every panel path funnels through the block predicate sync, so
        overriding it here keeps the cached cycle predicate fresh without
        touching each call site.
        """
        try:
            parent = super()
            refresh = getattr(parent, "_sync_block_navigable", None)
            if callable(refresh):
                refresh()
        except Exception:
            pass
        try:
            self._sync_view_cycle_available()
        except Exception:
            pass
