"""Surfaced-row candidate snapshots for bead warmup.

This module owns the viewport-bounded candidate scan plus the waiter and
stranded-project indexes it reads. The scan lifecycle
(:mod:`._loading_bead_warmup_scan`) and result application
(:mod:`._loading_bead_warmup_apply`) reach these helpers through ``self``.
"""

from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING

from ...models.agent_bead import (
    bead_display_resolution_reason,
    should_resolve_bead_display,
)
from ...models.agent_epic_follow_progress import (
    epic_follow_progress_resolution_reason,
    should_resolve_epic_follow_progress,
)
from ...models.agent_stranded import (
    should_resolve_stranded_report,
    stranded_project_keys,
    stranded_report_resolution_reason,
)
from ...models.agent_wait_beads import (
    should_resolve_wait_bead_statuses,
    wait_bead_status_resolution_reason,
)
from ...util.trace import is_enabled as tui_trace_enabled
from ._loading_bead_warmup_types import AgentBeadWarmupCandidates
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

__all__ = [
    "AgentBeadWarmupCandidatesMixin",
]

_MAX_WAITER_CANDIDATES = 32
_MAX_BACKGROUND_STRANDED_PROJECTS = 4
_MAX_VISIBLE_STRANDED_PROJECTS = 4
_STRANDED_PROJECTS_PER_SCAN = 16
_STRANDED_REPORT_TTL_SECONDS = 60.0


class AgentBeadWarmupCandidatesMixin(AgentLoadingStateMixin):
    """Snapshot surfaced rows and maintain waiter/project indexes."""

    def _bead_warmup_candidates(
        self,
        *,
        force_stranded: bool = False,
        force_stranded_immediate: bool = False,
    ) -> AgentBeadWarmupCandidates:
        """Snapshot surfaced rows plus the indexed WAITING set.

        The viewport query is bounded by Textual's visible line map. Historical
        rows are considered only when they are in the separately refreshed
        WAITING index or the bounded stranded-project sweep.
        """
        from ._roster_generation import get_roster_generation

        generation = get_roster_generation(self)
        previous_generation = getattr(self, "_bead_warmup_index_generation", None)
        roster_changed = previous_generation != generation
        trace_candidates = tui_trace_enabled()
        candidates_examined = 0
        cause_counts = (
            {
                "cold": 0,
                "ttl": 0,
                "forced": 0,
                "roster": 0,
                "pending_retry": 0,
            }
            if trace_candidates
            else None
        )
        if roster_changed:
            if cause_counts is not None:
                cause_counts["roster"] = 1
            self._refresh_bead_warmup_indexes(generation)

        surfaced_agents = self._surfaced_bead_warmup_agents()
        waiter_agents = tuple(getattr(self, "_bead_warmup_waiting_agents", {}).values())
        waiter_cursor = int(getattr(self, "_bead_warmup_waiter_cursor", 0))
        if waiter_agents:
            waiter_cursor %= len(waiter_agents)
            waiter_batch = tuple(
                waiter_agents[(waiter_cursor + offset) % len(waiter_agents)]
                for offset in range(min(_MAX_WAITER_CANDIDATES, len(waiter_agents)))
            )
            self._bead_warmup_waiter_cursor = (waiter_cursor + len(waiter_batch)) % len(
                waiter_agents
            )
        else:
            waiter_batch = ()
            self._bead_warmup_waiter_cursor = 0
        waiter_by_identity = {
            agent.identity: agent
            for agent in (*surfaced_agents, *waiter_batch)
            if agent.status == "WAITING"
        }

        bead_display_agents: list[Agent] = []
        wait_bead_status_agents: list[Agent] = []
        follow_progress_agents: list[Agent] = []
        for agent in surfaced_agents:
            if trace_candidates:
                candidates_examined += 1
                reason = bead_display_resolution_reason(agent)
            else:
                reason = "needed" if should_resolve_bead_display(agent) else None
            if reason is not None:
                bead_display_agents.append(agent)
                if cause_counts is not None:
                    cause_counts[reason] += 1
        for agent in waiter_by_identity.values():
            if trace_candidates:
                candidates_examined += 1
                reason = wait_bead_status_resolution_reason(agent)
            else:
                reason = "needed" if should_resolve_wait_bead_statuses(agent) else None
            if reason is not None:
                wait_bead_status_agents.append(agent)
                if cause_counts is not None:
                    cause_counts[reason] += 1
            if trace_candidates:
                reason = epic_follow_progress_resolution_reason(agent)
            else:
                reason = (
                    "needed" if should_resolve_epic_follow_progress(agent) else None
                )
            if reason is not None:
                follow_progress_agents.append(agent)
                if cause_counts is not None:
                    cause_counts[reason] += 1

        forced_projects: set[str] = getattr(self, "_bead_warmup_forced_projects", set())
        if not isinstance(forced_projects, set):
            forced_projects = set()
        if force_stranded and not forced_projects:
            # Compatibility for explicit callers that predate the project
            # argument: force the projects currently represented on screen.
            forced_projects = set(stranded_project_keys(surfaced_agents))
        forced_project_keys = tuple(dict.fromkeys(forced_projects))
        immediate_projects: set[str] = getattr(
            self, "_bead_warmup_forced_immediate_projects", set()
        )

        visible_project_keys = stranded_project_keys(surfaced_agents)
        stranded_projects: list[str] = []
        seen_projects: set[str] = set()
        for project_key in visible_project_keys:
            if project_key in seen_projects or project_key in forced_project_keys:
                continue
            if trace_candidates:
                candidates_examined += 1
            seen_projects.add(project_key)
            if trace_candidates:
                reason = stranded_report_resolution_reason(project_key)
            else:
                reason = (
                    "needed" if should_resolve_stranded_report(project_key) else None
                )
            if reason is not None:
                stranded_projects.append(project_key)
                if cause_counts is not None:
                    cause_counts[reason] += 1
            if len(stranded_projects) >= _MAX_VISIBLE_STRANDED_PROJECTS:
                break

        all_projects = tuple(getattr(self, "_bead_warmup_stranded_projects", ()))
        stranded_cursor = int(getattr(self, "_bead_warmup_stranded_cursor", 0))
        scan_remaining = int(getattr(self, "_bead_warmup_stranded_scan_remaining", 0))
        scan_next_at = float(getattr(self, "_bead_warmup_stranded_scan_next_at", 0.0))
        if all_projects and scan_remaining <= 0 and monotonic() >= scan_next_at:
            stranded_cursor = 0
            scan_remaining = len(all_projects)
        examined = 0
        background_due = 0
        while (
            scan_remaining > 0
            and examined < min(_STRANDED_PROJECTS_PER_SCAN, len(all_projects))
            and background_due < _MAX_BACKGROUND_STRANDED_PROJECTS
        ):
            project_key = all_projects[stranded_cursor]
            stranded_cursor = (stranded_cursor + 1) % len(all_projects)
            scan_remaining -= 1
            examined += 1
            if trace_candidates:
                candidates_examined += 1
            if project_key in seen_projects or project_key in forced_project_keys:
                continue
            seen_projects.add(project_key)
            if trace_candidates:
                reason = stranded_report_resolution_reason(project_key)
            else:
                reason = (
                    "needed" if should_resolve_stranded_report(project_key) else None
                )
            if reason is not None:
                stranded_projects.append(project_key)
                background_due += 1
                if cause_counts is not None:
                    cause_counts[reason] += 1
        forced_batch = forced_project_keys[:_MAX_BACKGROUND_STRANDED_PROJECTS]
        if cause_counts is not None:
            cause_counts["forced"] = len(forced_batch)
        stranded_scan_more = scan_remaining > 0 or len(forced_project_keys) > len(
            forced_batch
        )
        pending_retry = (
            stranded_scan_more
            or getattr(self, "_bead_warmup_scan_pending", False)
            or getattr(self, "_bead_warmup_scan_source", "") == "bead_warmup_followup"
        )
        if cause_counts is not None:
            cause_counts["pending_retry"] = int(bool(pending_retry))
        if scan_remaining == 0 and examined:
            scan_next_at = monotonic() + _STRANDED_REPORT_TTL_SECONDS
        self._bead_warmup_stranded_cursor = stranded_cursor
        self._bead_warmup_stranded_scan_remaining = scan_remaining
        self._bead_warmup_stranded_scan_next_at = scan_next_at

        return AgentBeadWarmupCandidates(
            bead_display_agents=tuple(bead_display_agents),
            wait_bead_status_agents=tuple(wait_bead_status_agents),
            follow_progress_agents=tuple(follow_progress_agents),
            stranded_projects=tuple(stranded_projects),
            force_stranded_projects=forced_batch,
            force_stranded_immediate=(
                force_stranded_immediate
                or bool(set(forced_batch) & set(immediate_projects))
            ),
            stranded_scan_more=stranded_scan_more,
            roster_generation=generation,
            candidates_examined=candidates_examined,
            cause_counts=(
                tuple((cause, count) for cause, count in cause_counts.items() if count)
                if cause_counts is not None
                else ()
            ),
        )

    def _refresh_bead_warmup_indexes(self, generation: int) -> None:
        """Build current-generation identity, waiter, and project indexes."""
        complete = getattr(self, "_agents_with_children", None)
        rows = tuple(complete or getattr(self, "_agents", ()) or ())
        agents_by_identity: dict[tuple[AgentType, str, str | None], Agent] = {}
        waiting_agents: dict[tuple[AgentType, str, str | None], Agent] = {}
        for agent in rows:
            agents_by_identity.setdefault(agent.identity, agent)
            if agent.status == "WAITING":
                waiting_agents[agent.identity] = agent
        for agent in getattr(self, "_agents", ()) or ():
            agents_by_identity[agent.identity] = agent
            if agent.status == "WAITING":
                waiting_agents[agent.identity] = agent

        self._bead_warmup_agent_by_identity = agents_by_identity
        self._bead_warmup_waiting_agents = waiting_agents
        self._bead_warmup_stranded_projects = stranded_project_keys(rows)
        self._bead_warmup_index_generation = generation
        self._bead_warmup_waiter_cursor = 0
        self._bead_warmup_stranded_cursor = 0
        self._bead_warmup_stranded_scan_remaining = len(
            self._bead_warmup_stranded_projects
        )
        self._bead_warmup_stranded_scan_next_at = 0.0

    def _surfaced_bead_warmup_agents(self) -> list[Agent]:
        """Collect surfaced rows from active panels plus the selected detail."""
        if getattr(self, "current_tab", "agents") != "agents":
            return []
        surfaced: list[Agent] = []
        query_one = getattr(self, "query_one", None)
        if callable(query_one):
            from ...widgets import AgentList
            from ._display_helpers import agent_list_widgets_in

            try:
                container = query_one("#agent-list-container")
            except Exception:  # noqa: BLE001 - unmounted test hosts have no surface.
                container = None
            if container is not None:
                for widget in agent_list_widgets_in(container):
                    if isinstance(widget, AgentList) and widget.display:
                        surfaced.extend(widget.surfaced_agents())
        else:
            # Small headless test hosts provide no widget tree; their _agents
            # list is the explicit surfaced fixture.
            surfaced.extend(getattr(self, "_agents", ()) or ())

        current_idx = getattr(self, "current_idx", None)
        agents = getattr(self, "_agents", ()) or ()
        if isinstance(current_idx, int) and 0 <= current_idx < len(agents):
            surfaced.append(agents[current_idx])
        by_identity: dict[tuple[AgentType, str, str | None], Agent] = {}
        for agent in surfaced:
            by_identity.setdefault(agent.identity, agent)
        return list(by_identity.values())
