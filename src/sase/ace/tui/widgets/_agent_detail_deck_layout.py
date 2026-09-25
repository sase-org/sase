"""Deck split layout API for AgentDetail."""

from __future__ import annotations

from typing import Any

from .decks.layout import (
    choose_new_panel,
    exit_zoom_keeping_panels,
    is_zoomed,
    new_panel_for_deck,
    step_ratio,
    toggle_focus,
    toggle_nodes_collapsed,
    toggle_split,
    toggle_zoom,
)
from .decks.model import DeckId, DeckLayout
from .decks.picker import other_panel_target


class AgentDetailDeckLayoutMixin:
    """Mixin providing deck split, focus and ratio actions."""

    _main_deck_document: Any
    _current_agent: Any | None
    _current_attempt_number: int | None

    def _notify_deck_state_changed(self) -> None:
        """Schedule a coalesced deck-layout save when the app owns one."""
        try:
            notify = getattr(self.app, "_agents_deck_state_changed", None)  # type: ignore[attr-defined]
            if callable(notify):
                notify()
        except Exception:
            pass

    @property
    def deck_layout(self) -> DeckLayout:
        """Return the current deck split layout."""
        try:
            return self.deck_area.state.layout  # type: ignore[attr-defined]
        except Exception:
            return DeckLayout.SINGLE

    def toggle_deck_split(self, target: DeckLayout) -> None:
        """Toggle a deck split layout for ``target``."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            state = area.state
        except Exception:
            return
        if state.layout is DeckLayout.SINGLE:
            self._open_deck_split(target)
            return
        try:
            area.apply_state(toggle_split(state, target, state.panels[-1]))
        except Exception:
            return
        self._notify_deck_state_changed()

    def _open_deck_split(
        self,
        target: DeckLayout,
        deck: DeckId | None = None,
        *,
        focus_new: bool = True,
    ) -> bool:
        """Open a split from a single deck panel; False when nothing opened.

        ``deck=None`` lets ``choose_new_panel`` pick the new panel's deck, as
        the split keys do. An explicit ``deck`` is shown in the new panel
        instead. The new panel takes focus unless ``focus_new`` is false.
        """
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            state = area.state
        except Exception:
            return False
        try:
            was_zoomed_from = state.focused if is_zoomed(state) else None
        except Exception:
            was_zoomed_from = None
        try:
            current_panel = area.focused_panel()
            current_deck = current_panel.deck
        except Exception:
            return False
        try:
            if current_deck is DeckId.MAIN:
                try:
                    active = current_panel.main_view.active_card_id
                except Exception:
                    active = getattr(current_panel, "_main_active_card", None)
                try:
                    card_ids = tuple(self._main_deck_document.card_ids)
                except Exception:
                    card_ids = ()
            else:
                active = None
                card_ids = ()
        except Exception:
            active = None
            card_ids = ()
        try:
            if deck is None:
                try:
                    shown = {p.deck for p in area.visible_panels()}
                except Exception:
                    shown = {current_deck}
                try:
                    raw_avail = dict(getattr(current_panel, "_availability", {}))
                    has_content = {
                        d: (raw_avail[d].has_content if d in raw_avail else None)
                        for d in (DeckId.MAIN, DeckId.FILES, DeckId.TOOLS)
                    }
                except Exception:
                    has_content = {}
                new_panel = choose_new_panel(
                    current_deck, active, shown, has_content, card_ids
                )
            else:
                new_panel = new_panel_for_deck(deck, current_deck, active, card_ids)
        except Exception:
            return False
        is_duplicate_files = (
            current_deck is DeckId.FILES and new_panel.deck is DeckId.FILES
        )
        try:
            area.apply_state(
                toggle_split(state, target, new_panel, focus_new=focus_new)
            )
        except Exception:
            return False
        if was_zoomed_from == 1:
            # Ending the zoom through a split: the zoomed panel's deck
            # now lives at logical index 0, so widget 0 must show it.
            try:
                self.show_deck(0, area.state.panels[0].deck)  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            self.show_deck(1, new_panel.deck)  # type: ignore[attr-defined]
        except Exception:
            pass
        if is_duplicate_files:
            try:
                panel1 = area.panel(1)
                file_list = list(getattr(panel1.file_view, "_file_list", []))
                if len(file_list) > 1:
                    panel1.file_view.next_file()
            except Exception:
                pass
        try:
            self._deck_refresh_availability()  # type: ignore[attr-defined]
        except Exception:
            pass
        self._notify_deck_state_changed()
        return True

    def show_deck_in_other_panel(self, panel_index: int | None, deck: DeckId) -> bool:
        """Show ``deck`` in the panel opposite ``panel_index``; True on change.

        A single deck area opens a new bottom panel. A split keeps its layout
        and fills the other panel. A zoom ends first, the way ``Z`` ends it.
        Focus stays on the source panel throughout. Returns False only when
        nothing changed: the other panel already shows ``deck`` and no zoom
        ended.
        """
        try:
            area = self.deck_area  # type: ignore[attr-defined]
        except Exception:
            return False
        try:
            visible_indices = {p.panel_index for p in area.visible_panels()}
            focused_index = area.focused_panel().panel_index
        except Exception:
            return False
        if panel_index is not None and panel_index in visible_indices:
            source = panel_index
        else:
            source = focused_index
        try:
            target = other_panel_target(area.state, source)
        except Exception:
            return False
        ended_zoom = False
        if target.ends_zoom:
            try:
                area.apply_state(exit_zoom_keeping_panels(area.state))
            except Exception:
                return False
            ended_zoom = True
            self._sync_nodes_collapsed_chrome()
            try:
                area.focused_panel().refresh_chrome()
            except Exception:
                pass
        if target.opens_split:
            opened = self._open_deck_split(DeckLayout.TOP_BOTTOM, deck, focus_new=False)
            return opened or ended_zoom
        if not ended_zoom:
            try:
                if area.panel(target.panel_index).deck is deck:
                    return False
            except Exception:
                return False
        try:
            self.show_deck(target.panel_index, deck)  # type: ignore[attr-defined]
        except Exception:
            return ended_zoom
        return True

    def toggle_deck_focus(self) -> None:
        """Move logical focus to the other panel in a split."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            area.apply_state(toggle_focus(area.state))
        except Exception:
            return
        self._notify_deck_state_changed()

    def step_deck_ratio(self, grow: bool) -> None:
        """Grow or shrink the focused panel one ratio step."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            area.apply_state(step_ratio(area.state, grow))
        except Exception:
            return
        self._notify_deck_state_changed()

    @property
    def is_nodes_collapsed(self) -> bool:
        """Return whether the node panel is collapsed in deck mode."""
        try:
            return bool(self.deck_area.state.nodes_collapsed)  # type: ignore[attr-defined]
        except Exception:
            return False

    @property
    def is_deck_zoomed(self) -> bool:
        """Return whether a deck panel is zoomed in place."""
        try:
            return is_zoomed(self.deck_area.state)  # type: ignore[attr-defined]
        except Exception:
            return False

    def toggle_node_panel(self) -> None:
        """Collapse or expand the node panel without unmounting it."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            area.apply_state(toggle_nodes_collapsed(area.state))
        except Exception:
            return
        self._sync_nodes_collapsed_chrome()
        self._notify_deck_state_changed()

    def toggle_deck_zoom(self) -> None:
        """Zoom the focused deck panel in place, or restore the snapshot."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            area.apply_state(toggle_zoom(area.state))
        except Exception:
            return
        self._sync_nodes_collapsed_chrome()
        try:
            area.focused_panel().refresh_chrome()
        except Exception:
            pass
        self._notify_deck_state_changed()

    def _sync_nodes_collapsed_chrome(self) -> None:
        """Sync the agents-content collapse class, spine and focus safety."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            collapsed = bool(area.state.nodes_collapsed)
        except Exception:
            return
        try:
            app = self.app  # type: ignore[attr-defined]
        except Exception:
            return
        try:
            content = app.query_one("#agents-content")
        except Exception:
            content = None
        if content is not None:
            try:
                if collapsed:
                    content.add_class("-nodes-collapsed")
                else:
                    content.remove_class("-nodes-collapsed")
            except Exception:
                pass
        try:
            from .decks.node_spine import NodeSpine

            spine = app.query_one("#agent-node-spine", NodeSpine)
        except Exception:
            spine = None
        if spine is not None:
            try:
                if collapsed:
                    spine.remove_class("hidden")
                else:
                    spine.add_class("hidden")
            except Exception:
                pass
        if collapsed:
            self._move_focus_off_hidden_list()
        try:
            info = getattr(app, "_update_agents_info_panel", None)
            if callable(info):
                info()
            else:
                footer = getattr(app, "_refresh_agent_footer_bindings_only", None)
                if callable(footer):
                    footer()
        except Exception:
            pass

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

    def _reload_duplicate_deck_from_cache(
        self, deck: DeckId, exclude_panel_index: int | None = None
    ) -> None:
        """Re-feed duplicate ``deck`` panels from shared caches only."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            agent = self._current_agent
        except Exception:
            return
        if agent is None:
            return
        try:
            panels = area.visible_panels()
        except Exception:
            return
        for panel in panels:
            try:
                if panel.deck is not deck:
                    continue
                if (
                    exclude_panel_index is not None
                    and panel.panel_index == exclude_panel_index
                ):
                    continue
            except Exception:
                continue
            try:
                if deck is DeckId.FILES:
                    self._load_files_panel_from_cache(panel, agent)  # type: ignore[attr-defined]
                elif deck is DeckId.TOOLS:
                    self._load_tools_panel_from_cache(panel, agent)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _load_files_panel_from_cache(self, panel: Any, agent: Any) -> bool:
        """Load a Files view from cache without starting a diff worker."""
        try:
            from .file_panel._messages import (
                _LIVE_DIFF_SENTINEL,
                file_cache,
                get_cache_key,
            )
        except Exception:
            return False
        try:
            panel.file_view._reconcile_file_list(agent, allow_initial_display=True)
        except Exception:
            pass
        try:
            cache_key = get_cache_key(agent)
            entry = file_cache.get(cache_key)
        except Exception:
            entry = None
        if entry is None or entry.diff_output is None:
            try:
                panel.refresh_chrome()
            except Exception:
                pass
            return False
        try:
            file_list = list(getattr(panel.file_view, "_file_list", []))
            index = int(getattr(panel.file_view, "_current_file_index", 0))
            if file_list and file_list[index] != _LIVE_DIFF_SENTINEL:
                try:
                    panel.refresh_chrome()
                except Exception:
                    pass
                return True
        except Exception:
            pass
        try:
            panel.file_view._display_file_with_timestamp(
                entry.diff_output,
                entry.fetch_time,
                post_visibility_message=False,
            )
        except Exception:
            return False
        try:
            panel.refresh_chrome()
        except Exception:
            pass
        return True

    def _load_tools_panel_from_cache(self, panel: Any, agent: Any) -> bool:
        """Load a Tools view from cache without starting a fetch worker."""
        try:
            result = panel.tools_view._cached_fetch_result(agent)
        except Exception:
            return False
        if result is None:
            return False
        try:
            panel.tools_view._display_llm_calls_result(
                result, post_visibility_message=False
            )
        except Exception:
            return False
        try:
            panel.refresh_chrome()
        except Exception:
            pass
        return True
