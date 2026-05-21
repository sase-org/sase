"""Agent detail panel + info panel update helpers.

Holds the right-hand detail-pane / info-panel plumbing extracted from
:mod:`._display`: the immediate detail-header refresh used during j/k
bursts, the debounced full update spawned once the burst quiesces, and
the bottom-bar info panel update.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sase.agent.status_buckets import agent_is_asking

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...widgets import AgentDetail, KeybindingFooter

from ...models.agent_groups import GroupingMode, status_bucket_for
from ...util.trace import tui_trace
from ._display_helpers import TabName
from ._loading_helpers import DISMISSABLE_STATUSES

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
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _agent_search_query: str
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None
    _countdown_remaining: int
    _agent_info_metrics_cache: tuple[Any, ...] | None

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
            from ._loading_helpers import hydrate_agent_attempt_history

            changed = hydrate_agent_attempt_history(current_agent)
            if changed:
                self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
            agent_detail.update_display(
                current_agent,
                stale_threshold_seconds=self.refresh_interval,
                attempt_number=self.current_attempt_number,
            )
        else:
            agent_detail.show_empty()

        self._apply_agent_footer_update(agent_detail, footer_widget, current_agent)

    def _apply_agent_footer_update(
        self,
        agent_detail: AgentDetail,
        footer_widget: KeybindingFooter,
        current_agent: Agent | None,
    ) -> None:
        """Refresh Agents-tab footer bindings for the current selection."""
        if getattr(self, "_fold_mode_active", False):
            footer_widget.update_fold_bindings()
        elif getattr(self, "_leader_mode_active", False):
            footer_widget.update_leader_bindings(
                current_tab="agents",
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
                self._resolve_agent_cl_name(current_agent) is not None  # type: ignore[attr-defined]
                if current_agent
                else False
            )
            cached_artifacts = getattr(self, "_cached_agent_artifacts", None)
            if current_agent is not None and callable(cached_artifacts):
                probe = cached_artifacts(current_agent)
                if probe is None:
                    schedule = getattr(
                        self, "_schedule_agent_artifacts_discovery", None
                    )
                    if callable(schedule):
                        schedule(current_agent)
                    has_agent_artifacts = False
                else:
                    has_agent_artifacts = bool(probe)
            else:
                has_agent_artifacts = False
            artifact_visible = getattr(self, "_artifact_tmux_pane_visible", None)
            artifact_viewer_active = (
                bool(artifact_visible()) if callable(artifact_visible) else False
            )
            footer_widget.update_agent_bindings(
                current_agent,
                completed_count=completed_count,
                can_jump_to_changespec=can_jump,
                marked_count=len(self._marked_agents),
                attempt_pinned=self.current_attempt_number is not None,
                group_focused=self._current_group_key is not None,
                has_agent_artifacts=has_agent_artifacts,
                artifact_viewer_active=artifact_viewer_active,
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

    def _update_agents_info_panel(self) -> None:
        """Update the agents info panel with current position and countdown."""
        with tui_trace("agents.update_info_panel", agents=len(self._agents)):
            self._update_agents_info_panel_impl()

    def _agent_info_metrics(self) -> tuple[int, int, int, int, int, int, int, int]:
        """Return cached visible top-level status counts for the info panel."""
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        cache_key = (id(self._agents), frozenset(unread_ids))
        cached = getattr(self, "_agent_info_metrics_cache", None)
        if cached is not None and cached[0] == cache_key:
            return cached[1]  # type: ignore[return-value]

        visible_top_level_agents = [
            self._agents[i] for i in panel_index.non_child_indices
        ]
        hidden_starting_agents = [
            self._agents[i] for i in panel_index.hidden_starting_indices
        ]
        unread_count = sum(
            1 for agent in visible_top_level_agents if agent.identity in unread_ids
        )
        visible_agent_buckets = [
            (agent, status_bucket_for(agent)) for agent in visible_top_level_agents
        ]
        waiting_count = sum(
            1 for _agent, bucket in visible_agent_buckets if bucket == "Waiting"
        )
        starting_count = len(hidden_starting_agents)
        failed_count = sum(
            1 for _agent, bucket in visible_agent_buckets if bucket == "Failed"
        )
        asking_count = sum(
            1
            for agent, _bucket in visible_agent_buckets
            if agent_is_asking(agent.status)
        )
        running_count = sum(
            1
            for agent, bucket in visible_agent_buckets
            if agent.status not in DISMISSABLE_STATUSES
            and bucket != "Starting"
            and bucket != "Waiting"
            and bucket != "Failed"
            and not agent_is_asking(agent.status)
        )
        read_count = sum(
            1
            for agent, bucket in visible_agent_buckets
            if bucket == "Done" and agent.identity not in unread_ids
        )
        metrics = (
            unread_count,
            asking_count,
            running_count,
            waiting_count,
            failed_count,
            read_count,
            panel_index.non_child_total,
            starting_count,
        )
        self._agent_info_metrics_cache = (cache_key, metrics)
        return metrics

    def _update_agents_info_panel_impl(self) -> None:
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, AgentInfoPanel

        try:
            agent_info_panel = self.query_one("#agent-info-panel", AgentInfoPanel)  # type: ignore[attr-defined]
        except NoMatches:
            log.debug("agents info panel update skipped: widget tree unavailable")
            return
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        total = panel_index.non_child_total
        position = (
            panel_index.non_child_position(self.current_idx) if self._agents else 0
        )
        (
            unread_count,
            asking_count,
            running_count,
            waiting_count,
            failed_count,
            read_count,
            visible_agent_count,
            starting_count,
        ) = self._agent_info_metrics()
        view_mode = ""
        if self._get_selected_agent() is not None:  # type: ignore[attr-defined]
            try:
                agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            except NoMatches:
                log.debug(
                    "agents info panel view mode skipped: widget tree unavailable"
                )
            else:
                view_mode = agent_detail.panel_mode_label
        from ._grouping import _MODE_LABELS

        grouping_mode = _MODE_LABELS.get(
            self._grouping_mode.name, self._grouping_mode.name
        )
        update_state = getattr(agent_info_panel, "update_state", None)
        if callable(update_state):
            update_state(
                position=position,
                total=total,
                unread=unread_count,
                asking=asking_count,
                running=running_count,
                waiting=waiting_count,
                failed=failed_count,
                read=read_count,
                visible_agent_count=visible_agent_count,
                starting=starting_count,
                countdown=self._countdown_remaining,
                interval=self.refresh_interval,
                search_query=self._agent_search_query,
                grouping_mode=grouping_mode,
                view_mode=view_mode,
            )
            return

        agent_info_panel.update_position(position, total)
        agent_info_panel.update_agent_counts(
            unread_count,
            asking_count,
            running_count,
            waiting_count,
            failed_count,
            read_count,
            total,
            starting=starting_count,
        )
        agent_info_panel.update_countdown(
            self._countdown_remaining, self.refresh_interval
        )
        agent_info_panel.update_search_query(self._agent_search_query)
        agent_info_panel.update_grouping_mode(grouping_mode)
        agent_info_panel.update_view_mode(view_mode)
