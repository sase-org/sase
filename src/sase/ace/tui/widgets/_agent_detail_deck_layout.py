"""Deck split layout API for AgentDetail."""

from __future__ import annotations

from typing import Any

from ._agent_detail_deck_pane_keys import AgentDetailDeckPaneKeysMixin
from .decks.layout import (
    SidebarMode,
    choose_new_panel,
    exit_zoom_keeping_panels,
    is_zoomed,
    new_panel_for_deck,
    refuse_three_pane_key,
    sidebar_mode,
    toggle_nodes_collapsed,
    toggle_split,
    toggle_zoom,
)
from .decks.model import DeckAreaState, DeckId, DeckLayout
from .decks.picker import other_panel_target


class AgentDetailDeckLayoutMixin(AgentDetailDeckPaneKeysMixin):
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

    def _apply_deck_area_state(self, new_state: DeckAreaState) -> None:
        """Apply ``new_state`` and re-sync sidebar chrome on mode changes."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
        except Exception:
            return
        try:
            old_mode = sidebar_mode(area.state)
        except Exception:
            old_mode = None
        try:
            area.apply_state(new_state)
        except Exception:
            return
        try:
            if old_mode is not None and sidebar_mode(new_state) is not old_mode:
                self._sync_sidebar_chrome()
        except Exception:
            pass

    @property
    def deck_layout(self) -> DeckLayout:
        """Return the current deck split layout."""
        try:
            return self.deck_area.state.layout  # type: ignore[attr-defined]
        except Exception:
            return DeckLayout.SINGLE

    def _deck_area_extent(self) -> tuple[int, int]:
        """Return the deck area (width, height), or (0, 0) when unknown."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            size = getattr(area, "size", None)
            if size is None:
                return (0, 0)
            return (int(size.width or 0), int(size.height or 0))
        except Exception:
            return (0, 0)

    def _node_collapse_gain(self) -> int:
        """Return the width collapsing the node list would reclaim."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            if area.state.nodes_collapsed:
                return 0
        except Exception:
            return 0
        try:
            from ._agent_list_render_rail import NODE_RAIL_WIDTH

            container = self.app.query_one("#agent-list-container")  # type: ignore[attr-defined]
            gain = int(container.size.width or 0) - int(NODE_RAIL_WIDTH)
            return max(0, gain)
        except Exception:
            return 0

    def _refuse_deck_key(self, message: str | None) -> bool:
        """Toast ``message`` and return True when a key is refused."""
        if message is None:
            return False
        try:
            self.notify(message, severity="warning")  # type: ignore[attr-defined]
        except Exception:
            try:
                self.app.notify(message, severity="warning")  # type: ignore[attr-defined]
            except Exception:
                pass
        return True

    def _choose_nest_panel(self) -> Any | None:
        """Choose the deck for a nested third panel, or None on failure.

        Mirrors the split-key choice in :meth:`_open_deck_split`: with Main
        and Files shown the third panel opens on Tools, or on FINAL when
        FINAL has positive content.
        """
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            current_panel = area.focused_panel()
            current_deck = current_panel.deck
        except Exception:
            return None
        try:
            if current_deck is DeckId.MAIN:
                try:
                    active = current_panel.main_view.active_card_id
                except Exception:
                    active = getattr(current_panel, "_main_active_card", None)
                try:
                    card_ids = tuple(self._main_deck_document.card_ids)  # type: ignore[attr-defined]
                except Exception:
                    card_ids = ()
            else:
                active = None
                card_ids = ()
        except Exception:
            active = None
            card_ids = ()
        try:
            try:
                shown = {p.deck for p in area.visible_panels()}
            except Exception:
                shown = {current_deck}
            try:
                from .decks.spec import active_deck_cycle

                raw_avail = dict(getattr(current_panel, "_availability", {}))
                has_content = {
                    d: (raw_avail[d].has_content if d in raw_avail else None)
                    for d in active_deck_cycle()
                }
            except Exception:
                has_content = {}
            return choose_new_panel(current_deck, active, shown, has_content, card_ids)
        except Exception:
            return None

    def _finish_nested_panels(self, before: set[int]) -> None:
        """Show freshly nested panels and refresh availability."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            opened = [pid for pid in area.state.grid.panes if pid not in before]
        except Exception:
            return
        if not opened:
            return
        try:
            panels = area.state.panels
        except Exception:
            return
        for new_id in opened:
            try:
                self.show_deck(new_id, panels[new_id].deck)  # type: ignore[attr-defined]
            except Exception:
                continue
        try:
            self._deck_refresh_availability()  # type: ignore[attr-defined]
        except Exception:
            pass

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
            width, height = self._deck_area_extent()
            refusal = refuse_three_pane_key(
                state,
                target,
                width,
                height,
                collapsed_gain=self._node_collapse_gain(),
            )
        except Exception:
            refusal = None
        if self._refuse_deck_key(refusal):
            return
        before = set()
        try:
            before = set(state.grid.panes)
        except Exception:
            before = set()
        new_panel = None
        if len(state.grid.panes) == 2:
            new_panel = self._choose_nest_panel()
        if new_panel is None:
            try:
                new_panel = state.panels[state.focused]
            except Exception:
                return
        try:
            self._apply_deck_area_state(toggle_split(state, target, new_panel))
        except Exception:
            return
        try:
            if len(area.state.grid.panes) == 3:
                self._finish_nested_panels(before)
        except Exception:
            pass
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
        A split while zoomed only restores the snapshot: from a
        zoomed-from-split state nothing opens, and from a zoomed-from-single
        state the restore runs first and the split then opens from it.
        """
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            state = area.state
        except Exception:
            return False
        if is_zoomed(state):
            try:
                self._apply_deck_area_state(exit_zoom_keeping_panels(state))
            except Exception:
                return False
            try:
                area.focused_panel().refresh_chrome()
            except Exception:
                pass
            try:
                state = area.state
            except Exception:
                return False
            if state.layout is not DeckLayout.SINGLE:
                self._notify_deck_state_changed()
                return False
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
                    from .decks.spec import active_deck_cycle

                    raw_avail = dict(getattr(current_panel, "_availability", {}))
                    has_content = {
                        d: (raw_avail[d].has_content if d in raw_avail else None)
                        for d in active_deck_cycle()
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
            before = set(area.state.grid.panes)
        except Exception:
            before = set()
        try:
            self._apply_deck_area_state(
                toggle_split(state, target, new_panel, focus_new=focus_new)
            )
        except Exception:
            return False
        try:
            opened = [pid for pid in area.state.grid.panes if pid not in before]
        except Exception:
            opened = []
        if not opened:
            return False
        new_id = area.state.grid.focused if focus_new else opened[0]
        try:
            self.show_deck(new_id, new_panel.deck)  # type: ignore[attr-defined]
        except Exception:
            pass
        if is_duplicate_files:
            try:
                created = area.panel(new_id)
                file_list = list(getattr(created.file_view, "_file_list", []))
                if len(file_list) > 1:
                    created.file_view.next_file()
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
                self._apply_deck_area_state(exit_zoom_keeping_panels(area.state))
            except Exception:
                return False
            ended_zoom = True
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

    @property
    def is_nodes_collapsed(self) -> bool:
        """Return whether the node-rail preference is set in deck mode."""
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

    @property
    def sidebar_mode(self) -> SidebarMode:
        """Return the derived left-column presentation mode."""
        try:
            return sidebar_mode(self.deck_area.state)  # type: ignore[attr-defined]
        except Exception:
            return SidebarMode.EXPANDED

    @property
    def is_node_rail(self) -> bool:
        """Return whether the node panel is in rail mode."""
        return self.sidebar_mode is SidebarMode.RAIL

    def toggle_node_panel(self) -> None:
        """Toggle the node panel between expanded and rail without unmounting it.

        While zoomed, restore the snapshot exactly like Z.
        """
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            if is_zoomed(area.state):
                self.toggle_deck_zoom()
                return
            self._apply_deck_area_state(toggle_nodes_collapsed(area.state))
        except Exception:
            return
        self._notify_deck_state_changed()

    def toggle_deck_zoom(self) -> None:
        """Zoom the focused deck panel in place, or restore the snapshot."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            self._apply_deck_area_state(toggle_zoom(area.state))
        except Exception:
            return
        try:
            area.focused_panel().refresh_chrome()
        except Exception:
            pass
        self._notify_deck_state_changed()

    def _sync_sidebar_chrome(self) -> None:
        """Sync sidebar mode classes, rail projection and focus safety."""
        from ..util.trace import tui_trace

        try:
            area = self.deck_area  # type: ignore[attr-defined]
            mode = sidebar_mode(area.state)
        except Exception:
            return
        with tui_trace("agents.sidebar.sync", mode=mode.value):
            try:
                app = self.app  # type: ignore[attr-defined]
            except Exception:
                return
            try:
                old_mode = getattr(app, "_agents_sidebar_mode", None)
            except Exception:
                old_mode = None
            try:
                app._agents_sidebar_mode = mode
            except Exception:
                pass
            try:
                content = app.query_one("#agents-content")
            except Exception:
                content = None
            if content is not None:
                try:
                    content.remove_class("-nodes-collapsed")
                    if mode is SidebarMode.RAIL:
                        content.add_class("-nodes-rail")
                    else:
                        content.remove_class("-nodes-rail")
                    if mode is SidebarMode.HIDDEN:
                        content.add_class("-nodes-hidden")
                    else:
                        content.remove_class("-nodes-hidden")
                except Exception:
                    pass
            self._sync_rail_projection(app, mode)
            if mode is SidebarMode.HIDDEN:
                self._move_focus_off_hidden_list()
            if old_mode is SidebarMode.RAIL and mode is SidebarMode.EXPANDED:
                self._settle_expanded_list_width(app)
                try:
                    catch_up = getattr(app, "_patch_agent_runtime_rows", None)
                    if callable(catch_up):
                        catch_up()
                except Exception:
                    pass
            try:
                info = getattr(app, "_update_agents_info_panel", None)
                if callable(info):
                    info()
            except Exception:
                pass
            try:
                # The footer carries mode-conditional entries (Z restore in
                # zoom, Ctrl+S expand in rail), so it refreshes on every
                # mode change alongside the info row.
                footer = getattr(app, "_refresh_agent_footer_bindings_only", None)
                if callable(footer):
                    footer()
            except Exception:
                pass

    def _sync_rail_projection(self, app: Any, mode: SidebarMode) -> None:
        """Project every live panel list into rail form while in RAIL mode.

        The container is clamped to ``NODE_RAIL_WIDTH`` through its inline
        min/max width; the negotiated expanded width underneath (``styles.width``,
        still tracked by the width writers) snaps back the moment the clamp
        clears. Panel titles are repainted for the new density.
        """
        from ..actions.agents._display_helpers import agent_list_widgets_in
        from ._agent_list_render_rail import NODE_RAIL_WIDTH

        in_rail = mode is SidebarMode.RAIL
        try:
            container = app.query_one("#agent-list-container")
        except Exception:
            container = None
        widgets: list[Any] = []
        if container is not None:
            try:
                widgets = agent_list_widgets_in(container)
            except Exception:
                widgets = []
        for widget in widgets:
            try:
                set_rail = getattr(widget, "set_rail", None)
                if callable(set_rail):
                    set_rail(in_rail)
            except Exception:
                continue
        if container is not None:
            try:
                styles = container.styles
                if in_rail:
                    styles.min_width = NODE_RAIL_WIDTH
                    styles.max_width = NODE_RAIL_WIDTH
                else:
                    styles.min_width = None
                    styles.max_width = None
            except Exception:
                pass
        try:
            refresh_titles = getattr(app, "_refresh_agent_panel_titles", None)
            if callable(refresh_titles):
                refresh_titles()
        except Exception:
            pass

    def _settle_expanded_list_width(self, app: Any) -> None:
        """Re-settle the list column after the expanded titles are back."""
        try:
            container = app.query_one("#agent-list-container")
        except Exception:
            return
        try:
            from ..actions.agents._display_helpers import agent_list_widgets_in

            widgets = agent_list_widgets_in(container)
        except Exception:
            return
        try:
            settle = getattr(app, "_settle_agent_list_container_width", None)
            if callable(settle):
                settle(container, widgets)
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
