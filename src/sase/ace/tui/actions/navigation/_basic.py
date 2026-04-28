"""Basic navigation mixin for scrolling and tab switching."""

from __future__ import annotations

from textual.containers import VerticalScroll

from ._types import NavigationMixinBase


def _nearest_stop_anchor(
    stops: list[tuple[str, int | tuple[str, ...]]],
    old_idx: int,
    old_key: tuple[str, ...] | None,
) -> int:
    """Pick a sensible anchor in ``stops`` when no exact match was found.

    Returns the position of the stop closest to the user's last anchor.
    Caller adds ``direction`` so the keystroke still moves by exactly one
    stop — but from a sensible neighbor instead of jumping to ``stops[0]``
    or ``stops[-1]``.

    Banner ancestor preferred when ``old_key`` shares any prefix with a
    banner stop's key.  Otherwise the agent stop with the closest global
    index to ``old_idx`` wins (lower-index tiebreak).  When neither
    applies the first banner stop is the last-resort fallback.
    """
    best_banner_pos: int | None = None
    best_banner_depth = 0
    if old_key is not None:
        for i, (kind, payload) in enumerate(stops):
            if kind != "banner":
                continue
            assert isinstance(payload, tuple)
            depth = 0
            while (
                depth < len(payload)
                and depth < len(old_key)
                and payload[depth] == old_key[depth]
            ):
                depth += 1
            if depth > best_banner_depth:
                best_banner_depth = depth
                best_banner_pos = i
        if best_banner_pos is not None:
            return best_banner_pos

    best_agent_pos: int | None = None
    best_dist: int | None = None
    for i, (kind, payload) in enumerate(stops):
        if kind != "agent":
            continue
        assert isinstance(payload, int)
        dist = abs(payload - old_idx)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_agent_pos = i
    if best_agent_pos is not None:
        return best_agent_pos

    for i, (kind, _) in enumerate(stops):
        if kind == "banner":
            return i
    return 0


class BasicNavigationMixin(NavigationMixinBase):
    """Mixin providing basic navigation, scrolling, and tab switching."""

    # --- Navigation Actions ---

    def _navigate_agents_panel(self, direction: int) -> None:
        """Navigate within the agents panel.

        Walks the same row sequence the renderer is showing: cycles
        through every selectable stop (collapsed banners + visible
        agents) in tree order so the user can step in and out of
        collapsed groups with ``j`` / ``k`` regardless of how many
        groups are folded.

        Args:
            direction: +1 for next, -1 for previous.
        """
        stops = self._panel_navigation_stops()  # type: ignore[attr-defined]
        if not stops:
            return
        old_key = self._current_group_key
        old_idx = self.current_idx
        pos: int | None = None
        # Prefer a banner match when the user is explicitly focused on
        # one; otherwise fall through to an agent match by current_idx.
        if old_key is not None:
            for i, (kind, payload) in enumerate(stops):
                if kind == "banner" and payload == old_key:
                    pos = i
                    break
        if pos is None:
            for i, (kind, payload) in enumerate(stops):
                if kind == "agent" and payload == old_idx:
                    pos = i
                    break
        if pos is None:
            pos = _nearest_stop_anchor(stops, old_idx, old_key)
        new_pos = (pos + direction) % len(stops)
        kind, payload = stops[new_pos]
        if kind == "banner":
            self._current_group_key = payload
        else:
            self._current_group_key = None
            self.current_idx = payload
        # The ``current_idx`` setter only fires ``watch_current_idx``
        # (the refresh trigger) when the index actually changes.
        # Banner-targeted stops leave ``current_idx`` untouched, and
        # banner→agent transitions can land on the same index — in
        # both cases nothing fires a refresh, so the highlight stays
        # stale on the previously selected row.  Drive it explicitly
        # whenever only ``_current_group_key`` changed.
        if self.current_idx == old_idx and self._current_group_key != old_key:
            self._refresh_agents_display_debounced()  # type: ignore[attr-defined]

    def _navigate_visible(self, direction: int) -> None:
        """Cycle ``current_idx`` through agents in rendered order.

        At fold level 2 the renderer walks the agent tree's grouping order
        rather than the raw ``_agents`` input order, so j/k must step
        through the same sequence to track the visible row.
        """
        visible = self._agents_visible_order()  # type: ignore[attr-defined]
        if not visible:
            return
        try:
            pos = visible.index(self.current_idx)
        except ValueError:
            self.current_idx = visible[0]
            return
        new_pos = (pos + direction) % len(visible)
        self.current_idx = visible[new_pos]

    def action_next_changespec(self) -> None:
        """Navigate to the next item, cycling to start if at end."""
        self._jk_perf_begin("next")  # type: ignore[attr-defined]
        self._record_jk_navigation()  # type: ignore[attr-defined]
        if self.current_tab == "changespecs":
            if len(self.changespecs) == 0:
                return
            self._navigate_changespec_panel(1)  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            self._navigate_agents_panel(1)
        else:  # axe tab
            if len(self._axe_items) == 0:  # type: ignore[attr-defined]
                return
            if self.current_idx < len(self._axe_items) - 1:  # type: ignore[attr-defined]
                self.current_idx += 1
            else:
                self.current_idx = 0

    def action_prev_changespec(self) -> None:
        """Navigate to the previous item, cycling to end if at start."""
        self._jk_perf_begin("prev")  # type: ignore[attr-defined]
        self._record_jk_navigation()  # type: ignore[attr-defined]
        if self.current_tab == "changespecs":
            if len(self.changespecs) == 0:
                return
            self._navigate_changespec_panel(-1)  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            self._navigate_agents_panel(-1)
        else:  # axe tab
            if len(self._axe_items) == 0:  # type: ignore[attr-defined]
                return
            if self.current_idx > 0:
                self.current_idx -= 1
            else:
                self.current_idx = len(self._axe_items) - 1  # type: ignore[attr-defined]

    def _get_agent_detail_scroll_id(self) -> str:
        """Get the scroll container ID for the active agent detail panel.

        Returns:
            CSS selector for the currently visible scroll container.
        """
        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        if agent_detail.is_info_mode():
            return "#agent-prompt-scroll"
        if agent_detail.is_thinking_visible():
            if agent_detail._has_thinking_content:
                return "#agent-thinking-scroll"
            return "#agent-prompt-scroll"
        if agent_detail._has_file_content:
            return "#agent-file-scroll"
        return "#agent-prompt-scroll"

    def action_scroll_detail_down(self) -> None:
        """Scroll the detail panel down by half a page (vim Ctrl+D style).

        On the agents tab, if scrolled to the bottom and content is trimmed,
        auto-expands by one page instead of scrolling.
        """
        if self.current_tab == "changespecs":
            scroll_container = self.query_one("#detail-scroll", VerticalScroll)  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            scroll_id = self._get_agent_detail_scroll_id()
            scroll_container = self.query_one(scroll_id, VerticalScroll)  # type: ignore[attr-defined]

            # Auto-expand when at bottom and content is trimmed
            if scroll_id == "#agent-file-scroll":
                from ...widgets import AgentDetail

                agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
                at_bottom = (
                    scroll_container.scroll_y >= scroll_container.max_scroll_y - 1
                )
                if at_bottom and agent_detail.is_file_trimmed():
                    agent_detail.expand_file_trim()
                    height = scroll_container.scrollable_content_region.height
                    self.call_after_refresh(  # type: ignore[attr-defined]
                        lambda: scroll_container.scroll_relative(
                            y=height // 2, animate=False
                        )
                    )
                    return
        else:  # axe
            self._axe_pinned_to_bottom = False
            scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
        height = scroll_container.scrollable_content_region.height
        scroll_container.scroll_relative(y=height // 2, animate=False)

    def action_scroll_detail_up(self) -> None:
        """Scroll the detail panel up by half a page (vim Ctrl+U style)."""
        if self.current_tab == "changespecs":
            scroll_container = self.query_one("#detail-scroll", VerticalScroll)  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            scroll_id = self._get_agent_detail_scroll_id()
            scroll_container = self.query_one(scroll_id, VerticalScroll)  # type: ignore[attr-defined]
        else:  # axe
            self._axe_pinned_to_bottom = False
            scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
        height = scroll_container.scrollable_content_region.height
        scroll_container.scroll_relative(y=-(height // 2), animate=False)

    def action_scroll_prompt_down(self) -> None:
        """Scroll prompt panel (Agents) or full page (Axe)."""
        if self.current_tab == "agents":
            scroll_container = self.query_one("#agent-prompt-scroll", VerticalScroll)  # type: ignore[attr-defined]
            height = scroll_container.scrollable_content_region.height
            scroll_container.scroll_relative(y=height // 2, animate=False)
        elif self.current_tab == "axe":
            self._axe_pinned_to_bottom = False
            scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
            height = scroll_container.scrollable_content_region.height
            scroll_container.scroll_relative(y=height, animate=False)  # Full page

    def action_scroll_prompt_up(self) -> None:
        """Scroll prompt panel (Agents) or full page (Axe)."""
        if self.current_tab == "agents":
            scroll_container = self.query_one("#agent-prompt-scroll", VerticalScroll)  # type: ignore[attr-defined]
            height = scroll_container.scrollable_content_region.height
            scroll_container.scroll_relative(y=-(height // 2), animate=False)
        elif self.current_tab == "axe":
            self._axe_pinned_to_bottom = False
            scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
            height = scroll_container.scrollable_content_region.height
            scroll_container.scroll_relative(y=-height, animate=False)  # Full page

    def action_scroll_to_top(self) -> None:
        """Scroll to the top of the current scrollable area."""
        if self.current_tab == "axe":
            self._axe_pinned_to_bottom = False
            scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll_container.scroll_home(animate=False)
        elif self.current_tab == "agents":
            scroll_id = self._get_agent_detail_scroll_id()
            scroll_container = self.query_one(scroll_id, VerticalScroll)  # type: ignore[attr-defined]
            scroll_container.scroll_home(animate=False)
        elif self.current_tab == "changespecs":
            scroll_container = self.query_one("#detail-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll_container.scroll_home(animate=False)

    def action_scroll_to_bottom(self) -> None:
        """Scroll to the bottom of the current scrollable area.

        On Axe tab, also pins the scroll to bottom so auto-refresh keeps
        showing latest output.
        """
        if self.current_tab == "axe":
            self._axe_pinned_to_bottom = True
            scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll_container.scroll_end(animate=False)
        elif self.current_tab == "agents":
            scroll_id = self._get_agent_detail_scroll_id()
            scroll_container = self.query_one(scroll_id, VerticalScroll)  # type: ignore[attr-defined]
            if scroll_id == "#agent-file-scroll":
                from ...widgets import AgentDetail

                agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
                if agent_detail.is_file_trimmed():
                    agent_detail.show_all_file_lines()
                    self.call_after_refresh(  # type: ignore[attr-defined]
                        lambda: scroll_container.scroll_end(animate=False)
                    )
                    return
            scroll_container.scroll_end(animate=False)
        elif self.current_tab == "changespecs":
            scroll_container = self.query_one("#detail-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll_container.scroll_end(animate=False)

    # --- Tab Switching Actions ---

    def _get_clamped_changespecs_idx(self) -> int:
        """Get changespecs index clamped to valid range."""
        if not self.changespecs:
            return 0
        return min(self._changespecs_last_idx, len(self.changespecs) - 1)

    def _get_clamped_agents_idx(self) -> int:
        """Get agents index clamped to valid range."""
        if not self._agents:
            return 0
        return min(self._agents_last_idx, len(self._agents) - 1)

    def _get_clamped_axe_idx(self) -> int:
        """Get axe index clamped to valid range."""
        if not self._axe_items:  # type: ignore[attr-defined]
            return 0
        from ..axe_display._loaders import find_axe_item_idx

        key_idx = find_axe_item_idx(  # type: ignore[attr-defined]
            self._axe_items, self._axe_last_item_key
        )
        if key_idx is not None:
            return key_idx
        return min(self._axe_last_idx, len(self._axe_items) - 1)  # type: ignore[attr-defined]

    def action_next_tab(self) -> None:
        """Switch to the next tab (cycling: CLs -> Agents -> Axe -> CLs)."""
        self._record_user_activity()  # type: ignore[attr-defined]
        self._save_current_tab_position()
        if self.current_tab == "changespecs":
            self.current_tab = "agents"  # type: ignore[assignment]
            self.current_idx = self._get_clamped_agents_idx()
        elif self.current_tab == "agents":
            self.current_tab = "axe"  # type: ignore[assignment]
            self.current_idx = self._get_clamped_axe_idx()
        else:  # axe
            self.current_tab = "changespecs"  # type: ignore[assignment]
            self.current_idx = self._get_clamped_changespecs_idx()

    def action_prev_tab(self) -> None:
        """Switch to the previous tab (cycling: CLs <- Agents <- Axe <- CLs)."""
        self._record_user_activity()  # type: ignore[attr-defined]
        self._save_current_tab_position()
        if self.current_tab == "changespecs":
            self.current_tab = "axe"  # type: ignore[assignment]
            self.current_idx = self._get_clamped_axe_idx()
        elif self.current_tab == "agents":
            self.current_tab = "changespecs"  # type: ignore[assignment]
            self.current_idx = self._get_clamped_changespecs_idx()
        else:  # axe
            self.current_tab = "agents"  # type: ignore[assignment]
            self.current_idx = self._get_clamped_agents_idx()

    def _save_current_tab_position(self) -> None:
        """Save the current position before switching tabs.

        Persists both the visible row index and the per-tab identity key
        so that an off-tab rebuild can restore the user's selection by
        identity rather than index — without an identity snapshot a
        background refresh on an inactive tab would silently shift the
        saved row to a different logical entry.
        """
        if self.current_tab == "changespecs":
            self._changespecs_last_idx = self.current_idx
            if self.changespecs and 0 <= self.current_idx < len(self.changespecs):
                self._changespecs_last_name = self.changespecs[self.current_idx].name
            else:
                self._changespecs_last_name = None
        elif self.current_tab == "agents":
            self._agents_last_idx = self.current_idx
            if self._agents and 0 <= self.current_idx < len(self._agents):
                self._agents_last_identity = self._agents[self.current_idx].identity
            else:
                self._agents_last_identity = None
        elif self.current_tab == "axe":
            self._axe_last_idx = self.current_idx  # type: ignore[attr-defined]
            from ..axe_display._loaders import selected_axe_item_key

            self._axe_last_item_key = selected_axe_item_key(  # type: ignore[attr-defined]
                self._axe_items, self.current_idx
            )
