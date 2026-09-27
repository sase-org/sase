"""Two pre-composed deck panels with a focused index."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical

from .layout import is_zoomed, toggle_focus
from .model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckView,
    with_panel_deck,
    with_panel_view,
    with_preferred_card,
)
from .panel import DeckPanel, DeckPanelFocusRequested


class DeckArea(Vertical):
    """Area holding two pre-composed deck panels."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the deck area."""
        super().__init__(**kwargs)
        self._state: DeckAreaState = DeckAreaState()

    @property
    def state(self) -> DeckAreaState:
        """Return the deck area state."""
        return self._state

    def compose(self) -> ComposeResult:
        """Compose both panels; panel 1 starts hidden."""
        yield DeckPanel(0, id="agent-deck-panel-0", classes="deck-panel")
        yield DeckPanel(1, id="agent-deck-panel-1", classes="deck-panel hidden")

    def panel(self, index: int) -> DeckPanel:
        """Return the panel at ``index``."""
        panels = self.query(DeckPanel)
        if index < 0 or index >= len(panels):
            raise IndexError(index)
        return panels[index]

    def apply_state(self, new_state: DeckAreaState) -> None:
        """Store ``new_state`` and sync CSS classes only."""
        self._state = new_state
        self._sync_panel_views(new_state)
        layout = new_state.layout
        for existing in list(self.classes):
            if existing in (
                "-single",
                "-top-bottom",
                "-left-right",
                "-ratio-30",
                "-ratio-50",
                "-ratio-70",
            ):
                self.remove_class(existing)
        if layout is DeckLayout.SINGLE:
            self.add_class("-single")
        elif layout is DeckLayout.TOP_BOTTOM:
            self.add_class("-top-bottom")
        else:
            self.add_class("-left-right")
        self.add_class(f"-ratio-{new_state.ratio}")
        try:
            panel0 = self.panel(0)
        except Exception:
            return
        try:
            panel1 = self.panel(1)
        except Exception:
            panel1 = None
        if is_zoomed(new_state):
            # The zoomed panel keeps its widget, card and scroll; the
            # other widget hides while the snapshot is held.
            for index, panel in ((0, panel0), (1, panel1)):
                if panel is None:
                    continue
                try:
                    if index == new_state.focused:
                        panel.remove_class("hidden")
                    else:
                        panel.add_class("hidden")
                    panel.set_focused(index == new_state.focused)
                except Exception:
                    pass
            return
        if layout is DeckLayout.SINGLE:
            if panel1 is not None:
                panel1.add_class("hidden")
            try:
                panel0.set_focused(True)
            except Exception:
                pass
            return
        # A split shows both panels. Panel 0 can still be hidden here when a
        # zoom on panel 1 just ended.
        for index, panel in ((0, panel0), (1, panel1)):
            if panel is None:
                continue
            try:
                panel.remove_class("hidden")
                panel.set_focused(index == new_state.focused)
            except Exception:
                pass

    def visible_panels(self) -> tuple[DeckPanel, ...]:
        """Return the visible panels for the current layout."""
        if is_zoomed(self._state):
            try:
                return (self.panel(self._state.focused),)
            except Exception:
                return ()
        try:
            panel0 = self.panel(0)
        except Exception:
            return ()
        if self._state.layout is DeckLayout.SINGLE:
            return (panel0,)
        try:
            panel1 = self.panel(1)
        except Exception:
            return (panel0,)
        return (panel0, panel1)

    def focused_panel(self) -> DeckPanel:
        """Return the focused panel."""
        if self._state.layout is DeckLayout.SINGLE and not is_zoomed(self._state):
            return self.panel(0)
        return self.panel(self._state.focused)

    def set_panel_deck(self, index: int, deck: DeckId) -> None:
        """Update state and the panel's deck."""
        self._state = with_panel_deck(self._state, index, deck)
        self.panel(index).set_deck(deck)

    def set_panel_view(
        self, index: int, deck: DeckId, view: DeckView, *, user_initiated: bool = False
    ) -> None:
        """Update state via ``with_panel_view``, then apply it on the panel.

        ``user_initiated`` marks a P/palette change (for the Files media
        toast); state syncs and restores never set it.
        """
        self._state = with_panel_view(self._state, index, deck, view)
        self.panel(index).set_view_policy(deck, view, user_initiated=user_initiated)

    def _sync_panel_views(self, new_state: DeckAreaState) -> None:
        """Sync stored view policies; apply only when changed (never raises)."""
        for index, panel_state in enumerate(new_state.panels):
            try:
                panel = self.panel(index)
            except Exception:
                continue
            try:
                changed = bool(panel.sync_view_policies(panel_state.views))
            except Exception:
                continue
            if not changed:
                continue
            try:
                if panel.deck is DeckId.MAIN:
                    document = panel._main_document
                    if not document.partial and document.cards:
                        panel._apply_main_view_change()
                        continue
                elif panel.deck is DeckId.FILES:
                    # State syncs and restores apply without the
                    # user-initiated flag, so they never toast.
                    panel._apply_files_view_change()
                    continue
                # Other decks need chrome only.
                panel.refresh_chrome()
            except Exception:
                pass

    def set_preferred_card(
        self, index: int, card_id: str | None, deck: DeckId | None = None
    ) -> None:
        """Update preferred card and re-show the stored Main document.

        The preference is stored under ``deck`` (default: the panel's own
        deck); the re-show always uses Main's entry.
        """
        self._state = with_preferred_card(self._state, index, card_id, deck)
        panel = self.panel(index)
        try:
            document = panel._main_document
        except Exception:
            return
        try:
            preferred = self._state.panels[index].preferred_card
        except Exception:
            preferred = card_id
        try:
            panel.show_main_document(document, preferred_card=preferred)
        except Exception:
            pass

    def set_preferred_card_state(
        self, index: int, card_id: str | None, deck: DeckId | None = None
    ) -> None:
        """Record the preferred card without re-showing the Main document.

        Block-only swaps (``cycle_block``/``select_block``) already show the
        owning card, sync chrome/rail, and step the cursor; pushing the whole
        document again re-measures, re-renders, and re-applies deck CSS for
        an identical frame. New subjects and deck switches still go through
        :meth:`set_preferred_card`.
        """
        self._state = with_preferred_card(self._state, index, card_id, deck)

    def set_preferred_cards(self, index: int, cards: Mapping[DeckId, str]) -> None:
        """Restore a whole per-deck mapping and re-show the Main document.

        Used when applying persisted state so every deck's sticky card is
        restored at once instead of one deck at a time.
        """
        panels = list(self._state.panels)
        if index < 0 or index >= len(panels):
            raise IndexError(index)
        panels[index] = dataclasses.replace(panels[index], preferred_cards=dict(cards))
        self._state = dataclasses.replace(self._state, panels=tuple(panels))
        panel = self.panel(index)
        try:
            document = panel._main_document
        except Exception:
            return
        try:
            panel.show_main_document(
                document, preferred_card=panels[index].preferred_card
            )
        except Exception:
            pass

    def panels_showing(self, deck: DeckId) -> tuple[DeckPanel, ...]:
        """Return visible panels showing ``deck``."""
        return tuple(p for p in self.visible_panels() if p.deck is deck)

    def on_deck_panel_focus_requested(self, message: DeckPanelFocusRequested) -> None:
        """Focus the clicked panel when it differs from the focused one."""
        index = message.panel_index
        if self._state.layout is DeckLayout.SINGLE:
            return
        if index == self._state.focused:
            return
        try:
            self.apply_state(toggle_focus(self._state))
        except Exception:
            return
        try:
            app = self.app
            refresh = getattr(app, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh):
                refresh()
            notify = getattr(app, "_agents_deck_state_changed", None)
            if callable(notify):
                notify()
        except Exception:
            pass
