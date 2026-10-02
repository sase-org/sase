"""Pane-ID-keyed deck panels rendered through one flat Textual grid."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical

from sase.ace.tui.util.pane_grid import grid_spec
from sase.ace.tui.util.pane_grid import focus_pane as _grid_focus_pane

from .layout import is_zoomed
from .model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckView,
    panel_state,
    with_panel_deck,
    with_panel_view,
    with_preferred_card,
)
from .panel import DeckPanel, DeckPanelFocusRequested
from .titles import ZoomChrome


class DeckArea(Vertical):
    """Area holding pane-ID-keyed deck panels in a flat grid."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the deck area."""
        super().__init__(**kwargs)
        self._state: DeckAreaState = DeckAreaState()

    @property
    def state(self) -> DeckAreaState:
        """Return the deck area state."""
        return self._state

    def compose(self) -> ComposeResult:
        """Compose all three panels; panels 1 and 2 start hidden.

        The third panel is composed eagerly (hidden) so a nest behind the
        ``three_pane_splits`` flag never mounts during a key handler: every
        structural key keeps widget identity with no mount or unmount.
        """
        yield DeckPanel(0, id="agent-deck-panel-0", classes="deck-panel")
        yield DeckPanel(1, id="agent-deck-panel-1", classes="deck-panel hidden")
        yield DeckPanel(2, id="agent-deck-panel-2", classes="deck-panel hidden")

    def panel(self, pane_id: int) -> DeckPanel:
        """Return the panel for ``pane_id`` through the explicit ID map."""
        try:
            found = self.query_one(f"#agent-deck-panel-{pane_id}", DeckPanel)
        except Exception:
            raise IndexError(pane_id) from None
        return found

    def _panels_by_id(self) -> dict[int, DeckPanel]:
        """Return the mounted panels keyed by pane ID (never raises)."""
        found: dict[int, DeckPanel] = {}
        for pane_id in (0, 1, 2):
            try:
                found[pane_id] = self.query_one(
                    f"#agent-deck-panel-{pane_id}", DeckPanel
                )
            except Exception:
                continue
        return found

    def _apply_grid_spec(self, new_state: DeckAreaState) -> None:
        """Apply the grid tracks, spans and DOM order (never raises)."""
        try:
            spec = grid_spec(new_state.grid)
        except Exception:
            return
        try:
            styles = self.styles
            styles.grid_size_columns = len(spec.columns)
            styles.grid_size_rows = len(spec.rows)
            styles.grid_columns = " ".join(f"{weight}fr" for weight in spec.columns)
            styles.grid_rows = " ".join(f"{weight}fr" for weight in spec.rows)
        except Exception:
            pass
        try:
            by_id = self._panels_by_id()
            for pane_id, cell in spec.cells.items():
                child = by_id.get(pane_id)
                if child is None:
                    continue
                try:
                    _, _, column_span, row_span = cell
                    child.styles.column_span = max(1, column_span)
                    child.styles.row_span = max(1, row_span)
                except Exception:
                    continue
            current = [
                child._panel_index
                for child in self.query(DeckPanel)
                if child._panel_index in by_id
            ]
            if current != list(spec.dom_order):
                previous: DeckPanel | None = None
                for pane_id in spec.dom_order:
                    child = by_id.get(pane_id)
                    if child is None:
                        continue
                    try:
                        if previous is None:
                            self.move_child(child, before=0)
                        else:
                            self.move_child(child, after=previous)
                    except Exception:
                        continue
                    previous = child
        except Exception:
            pass

    def apply_state(self, new_state: DeckAreaState) -> None:
        """Store ``new_state`` and sync grid tracks, spans and classes."""
        self._state = new_state
        self._sync_panel_views(new_state)
        self._apply_grid_spec(new_state)
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
        by_id = self._panels_by_id()
        if not by_id:
            return
        if is_zoomed(new_state):
            # The zoomed pane keeps its widget, card and scroll; every
            # other widget hides while the snapshot is held. The zoomed
            # pane gets its -zoomed class and ZoomChrome before
            # set_focused() repaints the chrome, so every zoom entry and
            # exit is correct by construction.
            snapshot = new_state.zoom_snapshot
            if snapshot is None:
                return
            order = snapshot.grid.panes
            try:
                position = list(order).index(new_state.focused)
            except ValueError:
                position = 0
            from sase.ace.tui.util.pane_grid import position_glyph as _glyph

            chrome = ZoomChrome(
                from_layout=snapshot.layout,
                panel_index=position,
                panel_count=len(order),
            )
            try:
                chrome = dataclasses.replace(
                    chrome, glyph=_glyph(snapshot.grid, new_state.focused)
                )
            except Exception:
                pass
            for pane_id, widget in by_id.items():
                try:
                    if pane_id == new_state.focused:
                        widget.set_zoom_chrome(chrome)
                        widget.remove_class("hidden")
                    else:
                        widget.set_zoom_chrome(None)
                        widget.add_class("hidden")
                    widget.set_focused(pane_id == new_state.focused)
                except Exception:
                    pass
            return
        visible = set(new_state.grid.panes)
        if layout is DeckLayout.SINGLE:
            sole = new_state.grid.panes[0] if new_state.grid.panes else 0
            for pane_id, widget in by_id.items():
                try:
                    widget.set_zoom_chrome(None)
                except Exception:
                    pass
                try:
                    if pane_id == sole:
                        widget.remove_class("hidden")
                    else:
                        widget.add_class("hidden")
                    widget.set_focused(pane_id == sole)
                except Exception:
                    pass
            return
        # A split shows every grid pane. A widget hidden by a zoom on the
        # other pane is reshown here, and a widget whose pane just closed
        # (for example 3 panels to 2) hides without unmounting.
        for pane_id, widget in by_id.items():
            if pane_id not in visible:
                try:
                    widget.set_zoom_chrome(None)
                    widget.add_class("hidden")
                    widget.set_focused(False)
                except Exception:
                    pass
                continue
            try:
                widget.set_zoom_chrome(None)
                widget.remove_class("hidden")
                widget.set_focused(pane_id == new_state.focused)
            except Exception:
                pass

    def visible_panels(self) -> tuple[DeckPanel, ...]:
        """Return the visible panels in grid reading order."""
        if is_zoomed(self._state):
            try:
                return (self.panel(self._state.focused),)
            except Exception:
                return ()
        shown: list[DeckPanel] = []
        for pane_id in self._state.grid.panes:
            try:
                shown.append(self.panel(pane_id))
            except Exception:
                continue
        return tuple(shown)

    def focused_panel(self) -> DeckPanel:
        """Return the focused panel."""
        return self.panel(self._state.focused)

    def set_panel_deck(self, pane_id: int, deck: DeckId) -> None:
        """Update state and the panel's deck."""
        self._state = with_panel_deck(self._state, pane_id, deck)
        self.panel(pane_id).set_deck(deck)

    def set_panel_view(
        self,
        pane_id: int,
        deck: DeckId,
        view: DeckView,
        *,
        user_initiated: bool = False,
    ) -> None:
        """Update state via ``with_panel_view``, then apply it on the panel.

        ``user_initiated`` marks a P/palette change (for the Files media
        toast); state syncs and restores never set it.
        """
        self._state = with_panel_view(self._state, pane_id, deck, view)
        self.panel(pane_id).set_view_policy(deck, view, user_initiated=user_initiated)

    def _sync_panel_views(self, new_state: DeckAreaState) -> None:
        """Sync stored view policies; apply only when changed (never raises)."""
        for pane_id, panel_state_entry in new_state.panels.items():
            try:
                widget = self.panel(pane_id)
            except Exception:
                continue
            try:
                changed = bool(widget.sync_view_policies(panel_state_entry.views))
            except Exception:
                continue
            if not changed:
                continue
            try:
                if widget.deck is DeckId.MAIN:
                    document = widget._main_document
                    if not document.partial and document.cards:
                        widget._apply_main_view_change()
                        continue
                elif widget.deck is DeckId.FILES:
                    # State syncs and restores apply without the
                    # user-initiated flag, so they never toast.
                    widget._apply_files_view_change()
                    continue
                # Other decks need chrome only.
                widget.refresh_chrome()
            except Exception:
                pass

    def set_preferred_card(
        self, pane_id: int, card_id: str | None, deck: DeckId | None = None
    ) -> None:
        """Update preferred card and re-show the stored Main document.

        The preference is stored under ``deck`` (default: the panel's own
        deck); the re-show always uses Main's entry.
        """
        self._state = with_preferred_card(self._state, pane_id, card_id, deck)
        widget = self.panel(pane_id)
        try:
            document = widget._main_document
        except Exception:
            return
        try:
            preferred = panel_state(self._state, pane_id).preferred_card
        except Exception:
            preferred = card_id
        try:
            widget.show_main_document(document, preferred_card=preferred)
        except Exception:
            pass

    def set_preferred_card_state(
        self, pane_id: int, card_id: str | None, deck: DeckId | None = None
    ) -> None:
        """Record the preferred card without re-showing the Main document.

        Block-only swaps (``cycle_block``/``select_block``) already show the
        owning card, sync chrome/rail, and step the cursor; pushing the whole
        document again re-measures, re-renders, and re-applies deck CSS for
        an identical frame. New subjects and deck switches still go through
        :meth:`set_preferred_card`.
        """
        self._state = with_preferred_card(self._state, pane_id, card_id, deck)

    def set_preferred_cards(self, pane_id: int, cards: Mapping[DeckId, str]) -> None:
        """Restore a whole per-deck mapping and re-show the Main document.

        Used when applying persisted state so every deck's sticky card is
        restored at once instead of one deck at a time.
        """
        current = panel_state(self._state, pane_id)
        panels = dict(self._state.panels)
        panels[pane_id] = dataclasses.replace(current, preferred_cards=dict(cards))
        self._state = dataclasses.replace(self._state, panels=panels)
        widget = self.panel(pane_id)
        try:
            document = widget._main_document
        except Exception:
            return
        try:
            widget.show_main_document(
                document, preferred_card=panels[pane_id].preferred_card
            )
        except Exception:
            pass

    def panels_showing(self, deck: DeckId) -> tuple[DeckPanel, ...]:
        """Return visible panels showing ``deck``."""
        return tuple(p for p in self.visible_panels() if p.deck is deck)

    def on_deck_panel_focus_requested(self, message: DeckPanelFocusRequested) -> None:
        """Focus the clicked pane by ID when it differs from the focused one."""
        pane_id = message.panel_index
        if pane_id == self._state.focused:
            return
        if pane_id not in self._state.grid.panes:
            return
        try:
            self.apply_state(
                dataclasses.replace(
                    self._state, grid=_grid_focus_pane(self._state.grid, pane_id)
                )
            )
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
