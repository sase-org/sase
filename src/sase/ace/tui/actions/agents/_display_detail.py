"""Agent detail panel + info panel update helpers.

Holds the right-hand detail-pane / info-panel plumbing extracted from
:mod:`._display`: the immediate detail-header refresh used during j/k
bursts, the debounced full update spawned once the burst quiesces, and
the bottom-bar info panel update.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...widgets import AgentDetail, KeybindingFooter

from ...models.agent_groups import GroupingMode
from ._display_helpers import TabName

log = logging.getLogger(__name__)


class DetailMixin:
    """Detail pane + info panel update helpers.

    Type hints below declare attributes that are defined at runtime by
    AceApp (and by :class:`AgentDisplayMixin` in particular).
    """

    current_idx: int
    current_attempt_number: int | None
    current_tab: TabName
    refresh_interval: int
    _agents: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _agent_search_query: str
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None
    _countdown_remaining: int

    def _apply_agent_detail_immediate(self) -> None:
        """Update the agent detail prompt header without spawning workers."""
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        except NoMatches:
            return

        current_agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if current_agent is None:
            agent_detail.show_empty()
            return
        agent_detail.update_display_immediate(
            current_agent, attempt_number=self.current_attempt_number
        )

    def _fire_debounced_detail_update(self) -> None:
        """Apply the debounced detail update once the j/k burst quiesces."""
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

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
            completed_count = self._agent_panel_index().completed_count  # type: ignore[attr-defined]
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
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        total = panel_index.non_child_total
        position = (
            panel_index.non_child_position(self.current_idx) if self._agents else 0
        )
        agent_info_panel.update_position(position, total)
        agent_info_panel.update_countdown(
            self._countdown_remaining, self.refresh_interval
        )
        agent_info_panel.update_search_query(self._agent_search_query)
        from ._grouping import _MODE_LABELS

        agent_info_panel.update_grouping_mode(
            _MODE_LABELS.get(self._grouping_mode.name, self._grouping_mode.name)
        )
        # Show current panel view mode when an agent is selected
        if self._get_selected_agent() is not None:  # type: ignore[attr-defined]
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            agent_info_panel.update_view_mode(agent_detail.panel_mode_label)
        else:
            agent_info_panel.update_view_mode("")
