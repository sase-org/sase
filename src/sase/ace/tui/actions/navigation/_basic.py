"""Basic navigation mixin for scrolling and tab switching."""

from __future__ import annotations

from textual.containers import VerticalScroll

from ._types import NavigationMixinBase


class BasicNavigationMixin(NavigationMixinBase):
    """Mixin providing basic navigation, scrolling, and tab switching."""

    # --- Navigation Actions ---

    def action_next_changespec(self) -> None:
        """Navigate to the next item, cycling to start if at end."""
        if self.current_tab == "changespecs":
            if len(self.changespecs) == 0:
                return
            if self.current_idx < len(self.changespecs) - 1:
                self.current_idx += 1
            else:
                self.current_idx = 0
        elif self.current_tab == "agents":
            if len(self._agents) == 0:
                return
            if self.current_idx < len(self._agents) - 1:
                self.current_idx += 1
            else:
                self.current_idx = 0
        else:  # axe tab
            if len(self._axe_items) == 0:  # type: ignore[attr-defined]
                return
            if self.current_idx < len(self._axe_items) - 1:  # type: ignore[attr-defined]
                self.current_idx += 1
            else:
                self.current_idx = 0

    def action_prev_changespec(self) -> None:
        """Navigate to the previous item, cycling to end if at start."""
        if self.current_tab == "changespecs":
            if len(self.changespecs) == 0:
                return
            if self.current_idx > 0:
                self.current_idx -= 1
            else:
                self.current_idx = len(self.changespecs) - 1
        elif self.current_tab == "agents":
            if len(self._agents) == 0:
                return
            if self.current_idx > 0:
                self.current_idx -= 1
            else:
                self.current_idx = len(self._agents) - 1
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
        """Save the current position before switching tabs."""
        if self.current_tab == "changespecs":
            self._changespecs_last_idx = self.current_idx
        elif self.current_tab == "agents":
            self._agents_last_idx = self.current_idx
        elif self.current_tab == "axe":
            self._axe_last_idx = self.current_idx  # type: ignore[attr-defined]
