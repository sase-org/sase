"""Agents-tab info-panel metrics and display helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ...models._agent_clan import agent_summary_status_counts
from ...models.agent_groups import GroupingMode
from ...models.agent_runner_slots import RunnerCapacitySnapshot
from ...util.trace import tui_trace

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

log = logging.getLogger(__name__)
_NEUTRAL_RUNNER_CAPACITY = RunnerCapacitySnapshot()


class AgentInfoDisplayMixin:
    """Compute and render Agents-tab position and status information."""

    current_idx: int
    refresh_interval: int
    _agents: list[Agent]
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _agent_search_query: str
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None
    _countdown_remaining: int
    _agent_info_metrics_cache: tuple[Any, ...] | None
    _agent_runner_capacity: RunnerCapacitySnapshot

    def _update_agents_info_panel(self) -> None:
        """Update the agents info panel with current position and countdown."""
        with tui_trace("agents.update_info_panel", agents=len(self._agents)):
            self._update_agents_info_panel_impl()

    def _agent_info_metrics(self) -> tuple[int, int, int, int, int, int, int, int]:
        """Return cached effective-agent status counts for the info panel."""
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
        projected = agent_summary_status_counts(
            visible_top_level_agents,
            unread_ids,
        )
        starting_count = len(hidden_starting_agents)
        metrics = (
            projected.unread,
            projected.stopped,
            projected.running,
            projected.waiting,
            projected.failed,
            projected.done,
            projected.total + starting_count,
            starting_count,
        )
        self._agent_info_metrics_cache = (cache_key, metrics)
        return metrics

    def _selected_agent_neighbor_count(self, current_agent: Agent | None) -> int:
        """Return the reachable neighbor/descendant count for the focused row."""
        if current_agent is None:
            return 0
        if getattr(self, "_current_group_key", None) is not None:
            return 0
        if not (0 <= self.current_idx < len(self._agents)):
            return 0
        index_getter = getattr(self, "_agent_neighbor_index", None)
        if not callable(index_getter):
            return 0
        index = index_getter()
        return int(
            index.neighbor_count(self.current_idx)
            + index.ancestor_count(self.current_idx)
            + index.descendant_count(self.current_idx)
        )

    def _selected_agent_tmux_choice_count(self, current_agent: Agent | None) -> int:
        """Return the cached tmux chooser target count for the focused agent.

        Reads only the in-memory opened-workspace cache (no marker I/O); a
        return value of ``0`` keeps the footer's plain ``tmux`` label.
        """
        getter = getattr(self, "cached_agent_tmux_choice_count", None)
        if not callable(getter):
            return 0
        return int(getter(current_agent))

    def _update_agents_info_panel_impl(self) -> None:
        from textual.css.query import NoMatches

        from ...widgets import AgentDetail, AgentInfoPanel

        try:
            agent_info_panel = self.query_one("#agent-info-panel", AgentInfoPanel)  # type: ignore[attr-defined]
        except NoMatches:
            log.debug("agents info panel update skipped: widget tree unavailable")
            return
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        # ``selectable_total`` drives position semantics (rendered/selectable
        # top-level rows), while ``visible_agent_count`` is the effective-agent
        # headline total that also includes hidden top-level STARTING rows.
        selectable_total = panel_index.non_child_total
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
        current_agent = self._get_selected_agent()  # type: ignore[attr-defined]
        neighbor_count = self._selected_agent_neighbor_count(current_agent)
        view_mode = ""
        if self._focused_tribe_panel_context() is not None:  # type: ignore[attr-defined]
            view_mode = "tribe"
        elif current_agent is not None:
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
        runner_capacity = getattr(
            self, "_agent_runner_capacity", _NEUTRAL_RUNNER_CAPACITY
        )
        update_state = getattr(agent_info_panel, "update_state", None)
        if callable(update_state):
            update_state(
                position=position,
                total=selectable_total,
                unread=unread_count,
                asking=asking_count,
                running=running_count,
                waiting=waiting_count,
                failed=failed_count,
                read=read_count,
                visible_agent_count=visible_agent_count,
                starting=starting_count,
                neighbor_count=neighbor_count,
                countdown=self._countdown_remaining,
                interval=self.refresh_interval,
                search_query=self._agent_search_query,
                grouping_mode=grouping_mode,
                view_mode=view_mode,
                runner_limit=runner_capacity.configured_limit,
                runner_slots_in_use=runner_capacity.slots_in_use,
                runner_queue_count=runner_capacity.global_cap_queue_count,
            )
            return

        agent_info_panel.update_position(position, selectable_total)
        update_runner_capacity = getattr(
            agent_info_panel, "update_runner_capacity", None
        )
        if callable(update_runner_capacity):
            update_runner_capacity(
                runner_capacity.slots_in_use,
                runner_capacity.configured_limit,
                runner_capacity.global_cap_queue_count,
            )
        agent_info_panel.update_agent_counts(
            unread_count,
            asking_count,
            running_count,
            waiting_count,
            failed_count,
            read_count,
            visible_agent_count,
            starting=starting_count,
        )
        agent_info_panel.update_countdown(
            self._countdown_remaining, self.refresh_interval
        )
        agent_info_panel.update_search_query(self._agent_search_query)
        agent_info_panel.update_grouping_mode(grouping_mode)
        agent_info_panel.update_view_mode(view_mode)
