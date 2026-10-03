"""Deck pane-key actions for AgentDetail (focus, swap, close, turn, ratio)."""

from __future__ import annotations

from typing import Any

from .decks.layout import (
    close_deck_panel,
    refuse_turn,
    step_ratio,
    swap_deck_panel,
    toggle_focus,
    toggle_focus_reverse,
    turn_deck_layout,
)


class AgentDetailDeckPaneKeysMixin:
    """Mixin providing deck pane-key actions."""

    def toggle_deck_focus(self) -> None:
        """Move logical focus to the next panel in a split."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            self._apply_deck_area_state(toggle_focus(area.state))  # type: ignore[attr-defined]
        except Exception:
            return
        self._notify_deck_state_changed()  # type: ignore[attr-defined]

    def toggle_deck_focus_reverse(self) -> None:
        """Move logical focus to the previous panel in a split."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            self._apply_deck_area_state(toggle_focus_reverse(area.state))  # type: ignore[attr-defined]
        except Exception:
            return
        self._notify_deck_state_changed()  # type: ignore[attr-defined]

    def swap_deck_panel(self, direction: int) -> None:
        """Swap the focused panel's session with its neighbour (split only)."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            self._apply_deck_area_state(swap_deck_panel(area.state, direction))  # type: ignore[attr-defined]
        except Exception:
            return
        self._notify_deck_state_changed()  # type: ignore[attr-defined]

    def close_deck_panel(self) -> None:
        """Close the focused panel, keeping the MRU survivor (split only)."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            self._apply_deck_area_state(close_deck_panel(area.state))  # type: ignore[attr-defined]
        except Exception:
            return
        try:
            area.focused_panel().refresh_chrome()
        except Exception:
            pass
        try:
            from textual.containers import VerticalScroll

            scrolls = area.focused_panel().query(VerticalScroll)
            for scroll in scrolls:
                try:
                    if scroll.has_class("-shown"):
                        scroll.focus()
                        break
                except Exception:
                    continue
            else:
                for scroll in scrolls:
                    try:
                        scroll.focus()
                        break
                    except Exception:
                        continue
        except Exception:
            pass
        self._notify_deck_state_changed()  # type: ignore[attr-defined]

    def turn_deck_layout(self) -> None:
        """Transpose the split layout (stacked/side-by-side).

        A three-pane turn is refused with a toast when the transposed
        grid would starve a panel; the layout is left unchanged.
        """
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            state = area.state
        except Exception:
            return
        try:
            width, height = self._deck_area_extent()  # type: ignore[attr-defined]
            if self._refuse_deck_key(refuse_turn(state, width, height)):  # type: ignore[attr-defined]
                return
        except Exception:
            pass
        try:
            self._apply_deck_area_state(turn_deck_layout(state))  # type: ignore[attr-defined]
        except Exception:
            return
        self._notify_deck_state_changed()  # type: ignore[attr-defined]

    def step_deck_ratio(self, grow: bool) -> None:
        """Grow or shrink the focused panel one ratio step."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            state = area.state
        except Exception:
            return
        try:
            candidate = step_ratio(state, grow)
            if len(candidate.grid.panes) == 3:
                width, height = self._deck_area_extent()  # type: ignore[attr-defined]
                if width > 0 and height > 0:
                    from .decks.layout import (
                        MIN_DECK_PANEL_HEIGHT,
                        MIN_DECK_PANEL_WIDTH,
                    )
                    from sase.ace.tui.util.pane_grid import fits

                    if not fits(
                        candidate.grid,
                        width,
                        height,
                        min_width=MIN_DECK_PANEL_WIDTH,
                        min_height=MIN_DECK_PANEL_HEIGHT,
                    ):
                        return
            self._apply_deck_area_state(candidate)  # type: ignore[attr-defined]
        except Exception:
            return
        self._notify_deck_state_changed()  # type: ignore[attr-defined]

    def _move_focus_off_hidden_list(self) -> None:
        """Move Textual focus off the hidden node list when it holds it."""
        try:
            app = self.app  # type: ignore[attr-defined]
            focused = app.focused
            container = app.query_one("#agent-list-container")
        except Exception:
            return
        if focused is None:
            return
        node: Any = focused
        inside = False
        while node is not None:
            if node is container:
                inside = True
                break
            node = getattr(node, "parent", None)
        if not inside:
            return
        try:
            from textual.containers import VerticalScroll

            area = self.deck_area  # type: ignore[attr-defined]
            scrolls = area.focused_panel().query(VerticalScroll)
            for scroll in scrolls:
                try:
                    if scroll.has_class("-shown"):
                        scroll.focus()
                        return
                except Exception:
                    continue
        except Exception:
            pass
