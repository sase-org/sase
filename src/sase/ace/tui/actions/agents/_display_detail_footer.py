"""Agent detail-panel footer binding helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._display_helpers import TabName

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...widgets import AgentDetail, KeybindingFooter

log = logging.getLogger(__name__)


class AgentFooterDisplayMixin:
    """Refresh footer bindings for the current agent detail state."""

    current_attempt_number: int | None
    current_tab: TabName
    _current_group_key: tuple[str, ...] | None
    _marked_agents: set[tuple[AgentType, str, str | None]]

    if TYPE_CHECKING:

        def _selected_agent_neighbor_count(
            self, current_agent: Agent | None
        ) -> int: ...

        def _selected_agent_tmux_choice_count(
            self, current_agent: Agent | None
        ) -> int: ...

    def _apply_agent_footer_update(
        self,
        agent_detail: AgentDetail,
        footer_widget: KeybindingFooter,
        current_agent: Agent | None,
    ) -> None:
        """Refresh Agents-tab footer bindings for the current selection."""
        if pending_digit := getattr(self, "_member_jump_pending_digit", None):
            footer_widget.update_member_jump_bindings(pending_digit)
        elif getattr(self, "_fold_mode_active", False):
            footer_widget.update_fold_bindings()
        elif getattr(self, "_leader_mode_active", False):
            footer_widget.update_leader_bindings(
                current_tab="agents",
                has_notification=(
                    current_agent.status in ("PLAN", "QUESTION")
                    if current_agent is not None
                    else False
                ),
                has_unread_completed_agent=self._has_unread_completed_agent(),  # type: ignore[attr-defined]
                has_stopped_agent=self._has_stopped_agent(),  # type: ignore[attr-defined]
            )
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
                not current_agent.is_clan_container
                and self._resolve_agent_cl_name(current_agent) is not None  # type: ignore[attr-defined]
                if current_agent
                else False
            )
            cached_artifacts = getattr(self, "_cached_artifact_files", None)
            if (
                current_agent is not None
                and not current_agent.is_clan_container
                and callable(cached_artifacts)
            ):
                probe = cached_artifacts(current_agent)
                if probe is None:
                    schedule = getattr(self, "_schedule_artifact_file_discovery", None)
                    if callable(schedule):
                        schedule(current_agent)
                    has_artifact_files = False
                else:
                    has_artifact_files = bool(probe)
            else:
                has_artifact_files = False
            artifact_visible = getattr(self, "_artifact_file_tmux_pane_visible", None)
            artifact_file_viewer_active = (
                bool(artifact_visible()) if callable(artifact_visible) else False
            )
            resolve_collapsed_panel = getattr(
                self, "_resolve_focused_collapsed_panel", None
            )
            collapsed_panel_focused = (
                resolve_collapsed_panel() is not None
                if callable(resolve_collapsed_panel)
                else False
            )
            footer_widget.update_agent_bindings(
                current_agent,
                completed_count=completed_count,
                can_jump_to_changespec=can_jump,
                marked_count=len(self._marked_agents),
                attempt_pinned=self.current_attempt_number is not None,
                collapsed_panel_focused=collapsed_panel_focused,
                group_focused=self._current_group_key is not None,
                has_artifact_files=has_artifact_files,
                artifact_file_viewer_active=artifact_file_viewer_active,
                neighbor_count=(
                    0
                    if current_agent is not None and current_agent.is_clan_container
                    else self._selected_agent_neighbor_count(current_agent)
                ),
                tmux_choice_count=(
                    0
                    if current_agent is not None and current_agent.is_clan_container
                    else self._selected_agent_tmux_choice_count(current_agent)
                ),
                tools_visible=agent_detail.is_tools_visible(),
                tools_detail_level=int(agent_detail.tools_detail_level),
            )

    def _refresh_agent_footer_bindings_only(self) -> None:
        """Refresh footer bindings without rebuilding the agent detail panel."""
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, KeybindingFooter

        try:
            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            footer_widget = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
        except NoMatches:
            log.debug("footer-only update skipped: widget tree unavailable")
            return
        self._apply_agent_footer_update(
            agent_detail,
            footer_widget,
            self._get_selected_agent(),  # type: ignore[attr-defined]
        )
