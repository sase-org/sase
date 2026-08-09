"""Basic navigation mixin for scrolling and tab switching."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.geometry import Region

from ...tab_order import TabName, adjacent_tab
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
        groups are folded. When the focused panel has at most one
        selectable stop, the same keys select the adjacent whole panel
        instead.

        Args:
            direction: +1 for next, -1 for previous.
        """
        whole_panel_nav = getattr(self, "_change_whole_panel_focus", None)
        if callable(whole_panel_nav) and whole_panel_nav(forward=direction > 0):
            return
        stops = self._panel_navigation_stops()  # type: ignore[attr-defined]
        guard = getattr(self, "_guard_agent_navigation_for_artifact_file_viewer", None)
        if callable(guard) and guard():
            return
        if len(stops) <= 1:
            escape = getattr(self, "_escape_dead_end_panel_focus", None)
            if callable(escape) and escape(forward=direction > 0):
                return
        if not stops:
            return
        old_key = self._current_group_key
        old_idx = self.current_idx
        pos: int | None = None
        stop_maps = getattr(self, "_panel_navigation_stop_maps", None)
        agent_positions: dict[int, int] = {}
        banner_positions: dict[tuple[str, ...], int] = {}
        if callable(stop_maps):
            agent_positions, banner_positions = stop_maps()
        # Prefer a banner match when the user is explicitly focused on
        # one; otherwise fall through to an agent match by current_idx.
        if old_key is not None:
            pos = banner_positions.get(old_key)
        if pos is None:
            pos = agent_positions.get(old_idx)
        if pos is None:
            pos = _nearest_stop_anchor(stops, old_idx, old_key)
        new_pos = (pos + direction) % len(stops)
        kind, payload = stops[new_pos]
        old_agent = None
        if (
            old_key is None
            and hasattr(self, "_agents")
            and 0 <= old_idx < len(self._agents)  # type: ignore[attr-defined]
        ):
            old_agent = self._agents[old_idx]  # type: ignore[attr-defined]
        leaving_old_agent = old_agent is not None and not (
            kind == "agent" and payload == old_idx
        )
        if leaving_old_agent:
            arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
            if callable(arm_manual):
                arm_manual(old_agent)
        if kind == "banner":
            self._current_group_key = payload
        else:
            self._current_group_key = None
            self.current_idx = payload
            if 0 <= payload < len(self._agents):  # type: ignore[attr-defined]
                agent = self._agents[payload]  # type: ignore[attr-defined]
                ack_unread = getattr(self, "_acknowledge_agent_unread", None)
                if callable(ack_unread):
                    ack_unread(agent)
        # The ``current_idx`` setter only fires ``watch_current_idx``
        # (the refresh trigger) when the index actually changes.
        # Banner-targeted stops leave ``current_idx`` untouched, and
        # banner→agent transitions can land on the same index — in
        # both cases nothing fires a refresh, so the highlight stays
        # stale on the previously selected row.  Drive it explicitly
        # whenever only ``_current_group_key`` changed.
        if self.current_idx == old_idx and self._current_group_key != old_key:
            self._refresh_agents_display_debounced()  # type: ignore[attr-defined]
        remember = getattr(self, "_remember_focused_panel_selection", None)
        if callable(remember):
            remember((kind, payload))

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

    def action_next_patch(self) -> None:
        """Navigate to the next item, cycling to start if at end."""
        self._jk_perf_begin("next")  # type: ignore[attr-defined]
        self._record_jk_navigation()  # type: ignore[attr-defined]
        if self.current_tab == "artifacts":
            if len(self.patches) == 0:
                return
            self._navigate_patch_panel(1)  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            self._navigate_agents_panel(1)
        else:  # axe tab
            if len(self._axe_items) == 0:  # type: ignore[attr-defined]
                return
            if self.current_idx < len(self._axe_items) - 1:  # type: ignore[attr-defined]
                self.current_idx += 1
            else:
                self.current_idx = 0

    def action_next_changespec(self) -> None:  # legacy compatibility alias
        """Legacy alias for :meth:`action_next_patch`."""
        self.action_next_patch()

    def action_prev_patch(self) -> None:
        """Navigate to the previous item, cycling to end if at start."""
        self._jk_perf_begin("prev")  # type: ignore[attr-defined]
        self._record_jk_navigation()  # type: ignore[attr-defined]
        if self.current_tab == "artifacts":
            if len(self.patches) == 0:
                return
            self._navigate_patch_panel(-1)  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            self._navigate_agents_panel(-1)
        else:  # axe tab
            if len(self._axe_items) == 0:  # type: ignore[attr-defined]
                return
            if self.current_idx > 0:
                self.current_idx -= 1
            else:
                self.current_idx = len(self._axe_items) - 1  # type: ignore[attr-defined]

    def action_prev_changespec(self) -> None:  # legacy compatibility alias
        """Legacy alias for :meth:`action_prev_patch`."""
        self.action_prev_patch()

    def _get_agent_detail_scroll_id(self) -> str:
        """Get the scroll container ID for the active agent detail panel.

        Returns:
            CSS selector for the currently visible scroll container.
        """
        from ...widgets import AgentDetail

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        if agent_detail.is_info_mode():
            return "#agent-prompt-scroll"
        if agent_detail.is_tools_visible():
            return "#agent-tools-scroll"
        if agent_detail._has_file_content:
            return "#agent-file-scroll"
        return "#agent-prompt-scroll"

    def action_scroll_detail_down(self) -> None:
        """Scroll the detail panel down by half a page (vim Ctrl+D style)."""
        route_artifacts = getattr(self, "_scroll_non_pr_artifacts_detail", None)
        if callable(route_artifacts) and route_artifacts(1):
            return
        if self.current_tab == "artifacts":
            scroll_container = self.query_one("#detail-scroll", VerticalScroll)  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            scroll_id = self._get_agent_detail_scroll_id()
            scroll_container = self.query_one(scroll_id, VerticalScroll)  # type: ignore[attr-defined]

        else:  # axe
            self._axe_pinned_to_bottom = False
            scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
        height = scroll_container.scrollable_content_region.height
        scroll_container.scroll_relative(y=height // 2, animate=False)

    def action_scroll_detail_up(self) -> None:
        """Scroll the detail panel up by half a page (vim Ctrl+U style)."""
        route_artifacts = getattr(self, "_scroll_non_pr_artifacts_detail", None)
        if callable(route_artifacts) and route_artifacts(-1):
            return
        if self.current_tab == "artifacts":
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
        route_artifacts = getattr(self, "_navigate_non_pr_artifacts", None)
        if callable(route_artifacts) and route_artifacts(action="down10", offset=10):
            return
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
        route_artifacts = getattr(self, "_navigate_non_pr_artifacts", None)
        if callable(route_artifacts) and route_artifacts(action="up10", offset=-10):
            return
        if self.current_tab == "agents":
            scroll_container = self.query_one("#agent-prompt-scroll", VerticalScroll)  # type: ignore[attr-defined]
            height = scroll_container.scrollable_content_region.height
            scroll_container.scroll_relative(y=-(height // 2), animate=False)
        elif self.current_tab == "axe":
            self._axe_pinned_to_bottom = False
            scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
            height = scroll_container.scrollable_content_region.height
            scroll_container.scroll_relative(y=-height, animate=False)  # Full page

    def action_next_agent_metadata_section(self) -> None:
        """Jump to the next rendered title in the Agents metadata pane."""
        self._cycle_agent_metadata_section(1)

    def action_prev_agent_metadata_section(self) -> None:
        """Jump to the previous rendered title in the Agents metadata pane."""
        self._cycle_agent_metadata_section(-1)

    def _cycle_agent_metadata_section(
        self,
        direction: int,
        *,
        retry: bool = False,
    ) -> None:
        """Resolve a cached section anchor and align it with the viewport top."""
        if self.current_tab != "agents":
            return

        from ...widgets import AgentDetail
        from ...widgets.prompt_panel import AgentPromptPanel
        from ...widgets.prompt_panel._section_navigation import (
            PromptPanelSectionTargetKind,
        )

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            panel = agent_detail.query_one("#agent-prompt-panel", AgentPromptPanel)
            scroll = agent_detail.query_one("#agent-prompt-scroll", VerticalScroll)
        except Exception:
            return

        if panel.enable_section_layout_reserve():
            panel.queue_section_retry(direction)
            if not getattr(self, "_agent_metadata_section_retry_scheduled", False):
                self._agent_metadata_section_retry_scheduled = True
                self.call_after_refresh(  # type: ignore[attr-defined]
                    self._retry_agent_metadata_section
                )
            return

        target = panel.resolve_section_target(
            direction,
            width=panel.size.width,
        )
        if not target.ready:
            if retry:
                return
            panel.queue_section_retry(direction)
            if not getattr(self, "_agent_metadata_section_retry_scheduled", False):
                self._agent_metadata_section_retry_scheduled = True
                self.call_after_refresh(  # type: ignore[attr-defined]
                    self._retry_agent_metadata_section
                )
            return
        if target.kind is PromptPanelSectionTargetKind.EMPTY:
            return
        if target.kind is PromptPanelSectionTargetKind.TOP:
            scroll.scroll_to(y=0, animate=False, immediate=True)
            return

        anchor = target.anchor
        if anchor is None:
            return

        panel_region = panel.virtual_region
        target_region = Region(
            panel_region.x,
            panel_region.y + anchor.row,
            max(1, panel_region.width),
            1,
        )
        scroll.scroll_to_region(
            target_region,
            top=True,
            animate=False,
            x_axis=False,
            y_axis=True,
            immediate=True,
        )

    def _retry_agent_metadata_section(self) -> None:
        """Consume one thin after-refresh retry from the newly published cache."""
        self._agent_metadata_section_retry_scheduled = False
        if self.current_tab != "agents":
            return

        from ...widgets import AgentDetail
        from ...widgets.prompt_panel import AgentPromptPanel

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            panel = agent_detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        except Exception:
            return
        direction = panel.consume_section_retry()
        if direction is not None:
            self._cycle_agent_metadata_section(direction, retry=True)

    def action_scroll_to_top(self) -> None:
        """Scroll to the top of the current scrollable area."""
        route_artifacts = getattr(self, "_navigate_non_pr_artifacts", None)
        if callable(route_artifacts) and route_artifacts(
            action="first", boundary="first"
        ):
            return
        if self.current_tab == "axe":
            self._axe_pinned_to_bottom = False
            scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll_container.scroll_home(animate=False)
        elif self.current_tab == "agents":
            scroll_id = self._get_agent_detail_scroll_id()
            scroll_container = self.query_one(scroll_id, VerticalScroll)  # type: ignore[attr-defined]
            scroll_container.scroll_home(animate=False)
        elif self.current_tab == "artifacts":
            scroll_container = self.query_one("#detail-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll_container.scroll_home(animate=False)

    def action_scroll_to_bottom(self) -> None:
        """Scroll to the bottom of the current scrollable area.

        On Axe tab, also pins the scroll to bottom so auto-refresh keeps
        showing latest output.
        """
        route_artifacts = getattr(self, "_navigate_non_pr_artifacts", None)
        if callable(route_artifacts) and route_artifacts(
            action="last", boundary="last"
        ):
            return
        if self.current_tab == "axe":
            self._axe_pinned_to_bottom = True
            scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll_container.scroll_end(animate=False)
        elif self.current_tab == "agents":
            scroll_id = self._get_agent_detail_scroll_id()
            scroll_container = self.query_one(scroll_id, VerticalScroll)  # type: ignore[attr-defined]
            if scroll_id == "#agent-prompt-scroll":
                from ...widgets.prompt_panel import AgentPromptPanel

                panel = scroll_container.query_one(
                    "#agent-prompt-panel", AgentPromptPanel
                )
                target = max(
                    0,
                    int(scroll_container.max_scroll_y) - panel.section_layout_reserve,
                )
                scroll_container.scroll_to(y=target, animate=False, immediate=True)
            else:
                scroll_container.scroll_end(animate=False)
        elif self.current_tab == "artifacts":
            scroll_container = self.query_one("#detail-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll_container.scroll_end(animate=False)

    # --- Tab Switching Actions ---

    def _get_clamped_patches_idx(self) -> int:
        """Get patches index clamped to valid range."""
        patches = getattr(
            self,
            "patches",
            getattr(self, "changespecs", []),  # legacy compatibility alias
        )
        if not patches:
            return 0
        last_idx = getattr(self, "_patches_last_idx", None)
        if last_idx is None:
            last_idx = getattr(self, "_patches_last_idx", 0)
        if not isinstance(last_idx, int):
            last_idx = 0
        return min(last_idx, len(patches) - 1)

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

    def _clamped_idx_for_tab(self, tab: TabName) -> int:
        """Return the restored selection index for ``tab``."""
        if tab == "artifacts":
            return self._get_clamped_patches_idx()
        if tab == "agents":
            return self._get_clamped_agents_idx()
        return self._get_clamped_axe_idx()

    def _switch_to_tab(self, tab: TabName) -> None:
        """Activate ``tab`` and restore its last selection index."""
        if (
            tab == "artifacts"
            and not hasattr(self, "patches")
            and hasattr(
                self,
                "changespecs",  # legacy compatibility alias
            )
        ):
            self.__dict__["current_tab"] = "changespecs"  # legacy compatibility alias
        else:
            self.current_tab = tab
        self.current_idx = self._clamped_idx_for_tab(tab)

    def action_next_tab(self) -> None:
        """Switch to the next tab (cycling: Agents -> Patches -> Axe -> Agents)."""
        self._last_input_action = "next_tab"  # type: ignore[attr-defined]
        self._record_input_event()  # type: ignore[attr-defined]
        if self.current_tab == "agents":
            focus_artifact = getattr(
                self, "_focus_tracked_artifact_file_tmux_pane", None
            )
            if callable(focus_artifact) and focus_artifact():
                return
        self._save_current_tab_position()
        self._switch_to_tab(adjacent_tab(self.current_tab, 1))

    def action_prev_tab(self) -> None:
        """Switch to the previous tab (cycling: Agents <- Patches <- Axe <- Agents)."""
        self._last_input_action = "prev_tab"  # type: ignore[attr-defined]
        self._record_input_event()  # type: ignore[attr-defined]
        self._save_current_tab_position()
        self._switch_to_tab(adjacent_tab(self.current_tab, -1))

    def _save_current_tab_position(self) -> None:
        """Save the current position before switching tabs.

        Persists both the visible row index and the per-tab identity key
        so that an off-tab rebuild can restore the user's selection by
        identity rather than index — without an identity snapshot a
        background refresh on an inactive tab would silently shift the
        saved row to a different logical entry.
        """
        if self.current_tab in {
            "artifacts",
            "patches",
            "changespecs",  # legacy compatibility alias
        }:
            self._patches_last_idx = self.current_idx
            patches = getattr(
                self,
                "patches",
                getattr(self, "changespecs", []),  # legacy compatibility alias
            )
            if patches and 0 <= self.current_idx < len(patches):
                self._patches_last_name = patches[self.current_idx].name
            else:
                self._patches_last_name = None
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
