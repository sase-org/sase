"""Agent display and refresh methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from textual.timer import Timer

    from ...models import Agent
    from ...models.agent import AgentType
    from ...widgets import AgentDetail, KeybindingFooter

from ._loading import DISMISSABLE_STATUSES

# Panel focus type
PanelFocus = Literal["main", "pinned"]

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentDisplayMixin:
    """Mixin providing agent display and refresh methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_idx: int
    current_tab: TabName
    refresh_interval: int
    _agents: list[Agent]
    _fold_counts: dict[str, tuple[int, int]]
    _agent_search_query: str

    # Debounce timer for j/k navigation detail panel updates
    _detail_update_timer: Timer | None

    # Panel focus and index maps for pinned panel split
    _pinned_panel_focused: PanelFocus
    _main_panel_indices: list[int]
    _pinned_panel_indices: list[int]
    _main_panel_idx_map: dict[int, int]
    _pinned_panel_idx_map: dict[int, int]
    _pinned_agents: set[tuple[AgentType, str, str | None]]

    # Countdown for refresh
    _countdown_remaining: int

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        """Refresh the agents tab display.

        Args:
            list_changed: If True, the agent list has changed and needs a full
                rebuild (called from _load_agents). If False, only the selection
                index moved (j/k navigation) — skip the expensive OptionList
                clear-and-rebuild.
        """
        # Cancel any pending debounce timer — full refresh supersedes
        if self._detail_update_timer is not None:
            self._detail_update_timer.stop()
            self._detail_update_timer = None

        from ...widgets import AgentDetail, AgentList, KeybindingFooter

        agent_list = self.query_one("#agent-list-panel", AgentList)  # type: ignore[attr-defined]
        pinned_list = self.query_one("#pinned-list-panel", AgentList)  # type: ignore[attr-defined]
        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]

        if list_changed:
            # Build panel-specific agent lists
            main_agents = [self._agents[i] for i in self._main_panel_indices]
            pinned_agents = [self._agents[i] for i in self._pinned_panel_indices]

            # Compute local selection index for each panel (O(1) via precomputed maps)
            main_local_idx = self._main_panel_idx_map.get(self.current_idx, 0)
            pinned_local_idx = self._pinned_panel_idx_map.get(self.current_idx, 0)

            agent_list.update_list(
                main_agents,
                main_local_idx,
                fold_counts=self._fold_counts,
                pinned_agents=self._pinned_agents,
                has_focus=(self._pinned_panel_focused == "main"),
            )
            pinned_list.update_list(
                pinned_agents,
                pinned_local_idx,
                fold_counts=self._fold_counts,
                pinned_agents=self._pinned_agents,
                has_focus=(self._pinned_panel_focused == "pinned"),
            )
        else:
            # Update highlight on the focused panel only; clear unfocused
            if self._pinned_panel_focused == "pinned":
                local_idx = self._pinned_panel_idx_map.get(self.current_idx)
                if local_idx is not None:
                    pinned_list.update_highlight(local_idx)
                agent_list.highlighted = None
            else:
                local_idx = self._main_panel_idx_map.get(self.current_idx)
                if local_idx is not None:
                    agent_list.update_highlight(local_idx)
                pinned_list.highlighted = None

        # Update focus styling
        self._update_panel_focus_styling()

        self._apply_agent_detail_update(agent_detail, footer_widget)

        self._update_agents_info_panel()

    def _refresh_agents_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the agents tab.

        Updates the list highlight and position counter immediately, but
        debounces the expensive detail panel and footer updates (disk I/O,
        Rich Syntax highlighting, background workers).
        """
        from ...widgets import AgentList

        # Update highlight on the focused panel only; clear unfocused
        if self._pinned_panel_focused == "pinned":
            pinned_list = self.query_one("#pinned-list-panel", AgentList)  # type: ignore[attr-defined]
            local_idx = self._pinned_panel_idx_map.get(self.current_idx)
            if local_idx is not None:
                pinned_list.update_highlight(local_idx)
            agent_list = self.query_one("#agent-list-panel", AgentList)  # type: ignore[attr-defined]
            agent_list.highlighted = None
        else:
            agent_list = self.query_one("#agent-list-panel", AgentList)  # type: ignore[attr-defined]
            local_idx = self._main_panel_idx_map.get(self.current_idx)
            if local_idx is not None:
                agent_list.update_highlight(local_idx)
            pinned_list = self.query_one("#pinned-list-panel", AgentList)  # type: ignore[attr-defined]
            pinned_list.highlighted = None
        self._update_agents_info_panel()

        # Cancel any pending debounce timer before scheduling a new one
        if self._detail_update_timer is not None:
            self._detail_update_timer.stop()

        self._detail_update_timer = self.set_timer(  # type: ignore[attr-defined]
            0.15, self._fire_debounced_detail_update
        )

    def _fire_debounced_detail_update(self) -> None:
        """Timer callback that applies the debounced detail update."""
        from ...widgets import AgentDetail, KeybindingFooter

        self._detail_update_timer = None

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        self._apply_agent_detail_update(agent_detail, footer_widget)

    def _apply_agent_detail_update(
        self,
        agent_detail: AgentDetail,
        footer_widget: KeybindingFooter,
    ) -> None:
        """Apply the expensive agent detail panel and footer updates.

        Args:
            agent_detail: The agent detail panel widget.
            footer_widget: The keybinding footer widget.
        """
        current_agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if current_agent is not None:
            agent_detail.update_display(
                current_agent, stale_threshold_seconds=self.refresh_interval
            )
        else:
            agent_detail.show_empty()

        if getattr(self, "_fold_mode_active", False):
            footer_widget.update_fold_bindings()
        elif getattr(self, "_leader_mode_active", False):
            footer_widget.update_leader_bindings(current_tab="agents")
        elif getattr(self, "_bang_mode_active", False):
            footer_widget.update_bang_bindings()
        elif getattr(self, "_copy_mode_active", False):
            file_visible = agent_detail.is_file_visible()
            footer_widget.update_copy_bindings(
                self.current_tab, file_visible=file_visible
            )
        elif (cm := getattr(self, "_custom_mode_active", None)) is not None:
            footer_widget.update_custom_mode_bindings(cm)
        else:
            completed_count = sum(
                1 for a in self._agents if a.status in DISMISSABLE_STATUSES
            )
            agent_is_pinned = (
                current_agent is not None
                and current_agent.identity in self._pinned_agents
            )
            footer_widget.update_agent_bindings(
                current_agent,
                completed_count=completed_count,
                is_pinned=agent_is_pinned,
                pinned_count=len(self._pinned_panel_indices),
                panel_focus=self._pinned_panel_focused,
            )

    def _update_panel_focus_styling(self) -> None:
        """Update CSS classes on both panels to reflect focus state."""
        from ...widgets import AgentList

        try:
            main_panel = self.query_one("#agent-list-panel")  # type: ignore[attr-defined]
            pinned_container = self.query_one("#pinned-panel-container")  # type: ignore[attr-defined]
            main_list = self.query_one("#agent-list-panel", AgentList)  # type: ignore[attr-defined]
            pinned_list = self.query_one("#pinned-list-panel", AgentList)  # type: ignore[attr-defined]
        except Exception:
            return

        # Auto-hide pinned panel when empty
        pinned_count = len(self._pinned_panel_indices)
        pinned_container.display = pinned_count > 0

        if self._pinned_panel_focused == "pinned":
            main_panel.add_class("panel-inactive")
            pinned_container.add_class("panel-active")
            main_list.add_class("panel-content-dim")
            pinned_list.remove_class("panel-content-dim")
        else:
            main_panel.remove_class("panel-inactive")
            pinned_container.remove_class("panel-active")
            main_list.remove_class("panel-content-dim")
            pinned_list.add_class("panel-content-dim")

        # Border titles with focus arrows
        if pinned_count > 0:
            if self._pinned_panel_focused == "pinned":
                main_panel.border_title = "  Agents"
                pinned_container.border_title = (
                    f"\u25b8 \U0001f4cc Pinned ({pinned_count})"
                )
                pinned_container.border_subtitle = "J switch"
            else:
                main_panel.border_title = "\u25b8 Agents"
                pinned_container.border_title = f"  \U0001f4cc Pinned ({pinned_count})"
                pinned_container.border_subtitle = ""
        else:
            main_panel.border_title = ""
            pinned_container.border_subtitle = ""

    def action_focus_pinned_panel(self) -> None:
        """Toggle focus between main agent list and pinned panel."""
        if self.current_tab != "agents":
            return

        if self._pinned_panel_focused == "main":
            if not self._pinned_panel_indices:
                self.notify("No pinned agents", severity="warning")  # type: ignore[attr-defined]
                return
            self._switch_panel_focus("pinned")  # type: ignore[attr-defined]
        else:
            if not self._main_panel_indices:
                self.notify("No agents in main list", severity="warning")  # type: ignore[attr-defined]
                return
            self._switch_panel_focus("main")  # type: ignore[attr-defined]

        self._refresh_agents_display(list_changed=True)

    def _update_agents_info_panel(self) -> None:
        """Update the agents info panel with current position and countdown."""
        from ...widgets import AgentDetail, AgentInfoPanel

        agent_info_panel = self.query_one("#agent-info-panel", AgentInfoPanel)  # type: ignore[attr-defined]
        # Position is 1-based for display (current_idx is 0-based)
        position = self.current_idx + 1 if self._agents else 0
        agent_info_panel.update_position(position, len(self._agents))
        agent_info_panel.update_countdown(
            self._countdown_remaining, self.refresh_interval
        )
        agent_info_panel.update_search_query(self._agent_search_query)
        # Show current panel view mode when an agent is selected
        if self._get_selected_agent() is not None:  # type: ignore[attr-defined]
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            agent_info_panel.update_view_mode(agent_detail.panel_mode_label)
        else:
            agent_info_panel.update_view_mode("")
