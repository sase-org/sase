"""Agent display and refresh methods for the ace TUI app."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from textual.timer import Timer

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_group_fold import AgentGroupFoldState
    from ...widgets import AgentDetail, KeybindingFooter

from ._loading import DISMISSABLE_STATUSES

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]
log = logging.getLogger(__name__)


class AgentDisplayMixin:
    """Mixin providing agent display and refresh methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_idx: int
    current_attempt_number: int | None
    current_tab: TabName
    refresh_interval: int
    _agents: list[Agent]
    _fold_counts: dict[str, tuple[int, int]]
    _agent_search_query: str

    # Debounce timer for j/k navigation detail panel updates
    _detail_update_timer: Timer | None

    _marked_agents: set[tuple[AgentType, str, str | None]]
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]

    # Phase-4 group fold: see ``startup.py`` for documentation.
    _group_fold_state: AgentGroupFoldState
    _current_group_key: tuple[str, ...] | None

    # Countdown for refresh
    _countdown_remaining: int

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        """Refresh the agents tab display.

        Args:
            list_changed: If True, the agent list has changed and needs a full
                rebuild (called from _load_agents). If False, only the selection
                index moved (j/k navigation) — skip the expensive OptionList
                clear-and-rebuild.
        """
        started = time.perf_counter()
        list_started = started
        # Cancel any pending debounce timer — full refresh supersedes
        if self._detail_update_timer is not None:
            self._detail_update_timer.stop()
            self._detail_update_timer = None

        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, AgentList, KeybindingFooter

        try:
            agent_list = self.query_one("#agent-list-panel", AgentList)  # type: ignore[attr-defined]
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            log.debug("agents display refresh skipped: widget tree unavailable")
            return

        if list_changed:
            # Drop any marks pointing at identities that no longer exist.
            self._prune_stale_marked_agents()  # type: ignore[attr-defined]
            jump_hints = (
                dict(self._entry_jump_index_to_hint)
                if self._entry_jump_mode_active
                else None
            )

            group_fold_level = self._group_fold_state.level  # type: ignore[attr-defined]
            agent_list.update_list(
                self._agents,
                self.current_idx,
                fold_counts=self._fold_counts,
                marked_agents=self._marked_agents,
                jump_hints=jump_hints,
                current_attempt_number=self.current_attempt_number,
                group_fold_level=group_fold_level,
                current_group_key=self._current_group_key,  # type: ignore[attr-defined]
            )
            log.debug(
                "agents display refresh list phase: elapsed=%.3fs agents=%d",
                time.perf_counter() - list_started,
                len(self._agents),
            )
        else:
            agent_list.update_highlight(self.current_idx, self.current_attempt_number)

        self._update_agents_info_panel()
        if defer_detail:
            self._detail_update_timer = self.set_timer(  # type: ignore[attr-defined]
                0.15, self._fire_debounced_detail_update
            )
            log.debug(
                "agents display refresh deferred detail: elapsed=%.3fs",
                time.perf_counter() - started,
            )
            return

        detail_started = time.perf_counter()
        self._apply_agent_detail_update(agent_detail, footer_widget)
        log.debug(
            "agents display refresh detail phase: elapsed=%.3fs total=%.3fs",
            time.perf_counter() - detail_started,
            time.perf_counter() - started,
        )

    def _refresh_agents_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the agents tab.

        Updates the list highlight and position counter immediately, but
        debounces the expensive detail panel and footer updates (disk I/O,
        Rich Syntax highlighting, background workers).
        """
        from ...widgets import AgentList

        agent_list = self.query_one("#agent-list-panel", AgentList)  # type: ignore[attr-defined]
        agent_list.update_highlight(
            self.current_idx,
            self.current_attempt_number,
            group_key=self._current_group_key,  # type: ignore[attr-defined]
        )
        self._update_agents_info_panel()

        # Cancel any pending debounce timer before scheduling a new one
        if self._detail_update_timer is not None:
            self._detail_update_timer.stop()

        self._detail_update_timer = self.set_timer(  # type: ignore[attr-defined]
            0.15, self._fire_debounced_detail_update
        )

    def _fire_debounced_detail_update(self) -> None:
        """Timer callback that applies the debounced detail update."""
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

        self._detail_update_timer = None

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            log.debug("debounced detail update skipped: widget tree unavailable")
            return

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
                current_agent,
                stale_threshold_seconds=self.refresh_interval,
                attempt_number=self.current_attempt_number,
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
            can_jump = (
                self._resolve_agent_cl_name(current_agent) is not None  # type: ignore[attr-defined]
                if current_agent
                else False
            )
            footer_widget.update_agent_bindings(
                current_agent,
                completed_count=completed_count,
                can_jump_to_changespec=can_jump,
                marked_count=len(self._marked_agents),
                attempt_pinned=self.current_attempt_number is not None,
                group_focused=self._current_group_key is not None,
            )

    def _update_agents_info_panel(self) -> None:
        """Update the agents info panel with current position and countdown."""
        from ...widgets import AgentDetail, AgentInfoPanel

        agent_info_panel = self.query_one("#agent-info-panel", AgentInfoPanel)  # type: ignore[attr-defined]
        # Position is 1-based for display; exclude workflow children from count.
        non_child_indices = [
            i for i, a in enumerate(self._agents) if not a.is_workflow_child
        ]
        from bisect import bisect_right

        total = len(non_child_indices)
        if self._agents:
            position = bisect_right(non_child_indices, self.current_idx)
        else:
            position = 0
        agent_info_panel.update_position(position, total)
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
