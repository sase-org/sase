"""Deferred, coalesced bead-confirmation warmup for the Agents tab.

Row rendering and header building must never touch bead storage, so they can
only show the bead glyph / ``Bead:`` field from the cached bead display state
(see :mod:`sase.ace.tui.models.agent_bead`). This mixin warms that cache off
the startup-critical loader path: after an Agents refresh has applied and the
list has painted, a coalesced background worker resolves the small set of
visible rows whose bead candidate has not been checked recently, runs the
bead-store lookups off the event loop, and patches the affected rows in place
by identity when the confirmed state changes.

First paint and j/k navigation are never gated on bead confirmation; the glyph
and field fill in shortly after the TUI is already interactive. Expired values
keep rendering while they revalidate, and missing candidates stay silent until
the cache TTL asks for another check.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

from ...agent_completion import (
    agent_wait_status_maps_for_app,
    wait_dependency_status_counts,
)
from ...models.agent_bead import (
    bead_display_resolution_reason,
    should_resolve_bead_display,
    warm_confirmed_bead_displays,
)
from ...models.agent_wait_beads import (
    cached_wait_bead_status_snapshot,
    should_resolve_wait_bead_statuses,
    wait_bead_status_resolution_reason,
    warm_wait_bead_statuses,
)
from ...models.agent_stranded import (
    should_resolve_stranded_report,
    stranded_project_key_for_agent,
    stranded_project_keys,
    stranded_report_resolution_reason,
    warm_stranded_work_reports,
)
from ...models.agent_epic_follow_progress import (
    epic_follow_progress_resolution_reason,
    should_resolve_epic_follow_progress,
    warm_epic_follow_progress,
)
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import is_enabled as tui_trace_enabled, tui_trace
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

log = logging.getLogger(__name__)

_MAX_WAITER_CANDIDATES = 32
_MAX_BACKGROUND_STRANDED_PROJECTS = 4
_MAX_VISIBLE_STRANDED_PROJECTS = 4
_STRANDED_PROJECTS_PER_SCAN = 16
_STRANDED_REPORT_TTL_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class _AgentBeadWarmupCandidates:
    """Surfaced-row and relevant waiter cache work for one coalesced pass."""

    bead_display_agents: tuple[Agent, ...] = ()
    wait_bead_status_agents: tuple[Agent, ...] = ()
    follow_progress_agents: tuple[Agent, ...] = field(default_factory=tuple)
    stranded_projects: tuple[str, ...] = ()
    force_stranded_projects: tuple[str, ...] = ()
    force_stranded_immediate: bool = False
    stranded_scan_more: bool = False
    roster_generation: int = 0
    candidates_examined: int = 0
    cause_counts: tuple[tuple[str, int], ...] = ()

    def __bool__(self) -> bool:
        return bool(
            self.bead_display_agents
            or self.wait_bead_status_agents
            or self.follow_progress_agents
            or self.stranded_projects
            or self.force_stranded_projects
            or self.stranded_scan_more
        )

    @property
    def total_count(self) -> int:
        """Return total candidate rows across all bead warmup lanes."""
        return (
            len(self.bead_display_agents)
            + len(self.wait_bead_status_agents)
            + len(self.follow_progress_agents)
            + len(self.stranded_projects)
            + len(self.force_stranded_projects)
        )


@dataclass(frozen=True, slots=True)
class _AgentBeadWarmupResults:
    """Cache-visible row changes produced by one bead warmup pass."""

    bead_display_results: dict[tuple[AgentType, str, str | None], bool]
    wait_bead_status_identities: set[tuple[AgentType, str, str | None]]
    follow_progress_identities: set[tuple[AgentType, str, str | None]] = field(
        default_factory=set
    )
    stranded_changed_projects: frozenset[str] = frozenset()
    stranded_warmed_projects: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        return bool(
            self.bead_display_results
            or self.wait_bead_status_identities
            or self.follow_progress_identities
            or self.stranded_changed_projects
            or self.stranded_warmed_projects
        )


def _warm_agent_bead_caches(
    candidates: _AgentBeadWarmupCandidates,
    *,
    telemetry: dict[str, int] | None = None,
) -> _AgentBeadWarmupResults:
    """Warm bead display, wait-status, and follow-progress caches off-loop."""
    if telemetry is None:
        bead_display_results = warm_confirmed_bead_displays(
            candidates.bead_display_agents
        )
        wait_bead_status_identities = warm_wait_bead_statuses(
            candidates.wait_bead_status_agents
        )
        follow_progress_identities = warm_epic_follow_progress(
            candidates.follow_progress_agents
        )
    else:
        bead_display_results = warm_confirmed_bead_displays(
            candidates.bead_display_agents,
            telemetry=telemetry,
        )
        wait_bead_status_identities = warm_wait_bead_statuses(
            candidates.wait_bead_status_agents,
            telemetry=telemetry,
        )
        follow_progress_identities = warm_epic_follow_progress(
            candidates.follow_progress_agents,
            telemetry=telemetry,
        )
    normal_projects = tuple(
        project
        for project in candidates.stranded_projects
        if project not in candidates.force_stranded_projects
    )
    if telemetry is None:
        stranded_changed = warm_stranded_work_reports(normal_projects)
    else:
        stranded_changed = warm_stranded_work_reports(
            normal_projects,
            telemetry=telemetry,
        )
    if candidates.force_stranded_projects:
        if telemetry is None:
            forced_stranded_changed = warm_stranded_work_reports(
                candidates.force_stranded_projects,
                force=True,
                force_immediate=candidates.force_stranded_immediate,
            )
        else:
            forced_stranded_changed = warm_stranded_work_reports(
                candidates.force_stranded_projects,
                force=True,
                force_immediate=candidates.force_stranded_immediate,
                telemetry=telemetry,
            )
        stranded_changed.update(forced_stranded_changed)
    return _AgentBeadWarmupResults(
        bead_display_results=bead_display_results,
        wait_bead_status_identities=wait_bead_status_identities,
        follow_progress_identities=follow_progress_identities,
        stranded_changed_projects=frozenset(stranded_changed),
        stranded_warmed_projects=frozenset(
            {*candidates.stranded_projects, *candidates.force_stranded_projects}
        ),
    )


class AgentBeadWarmupMixin(AgentLoadingStateMixin):
    """Schedule and apply deferred bead-confirmation warmups off startup."""

    # Coalescing state (initialized by ``_init_app_state``):
    #   ``_bead_warmup_scan_scheduled`` — a detached async worker is queued.
    #   ``_bead_warmup_scan_running``  — a worker is mid-flight (off-thread).
    #   ``_bead_warmup_scan_pending``  — a request arrived while one ran, so the
    #                                    in-flight worker re-arms itself on exit.
    #   ``_bead_warmup_scan_source``   — telemetry tag for the queued scan.
    _bead_warmup_scan_scheduled: bool
    _bead_warmup_scan_running: bool
    _bead_warmup_scan_pending: bool
    _bead_warmup_scan_source: str
    _bead_warmup_scheduled_candidates: _AgentBeadWarmupCandidates | None
    _bead_warmup_async_tasks: set[asyncio.Task[None]]

    def _schedule_bead_confirmation_warmup(
        self,
        *,
        source: str = "unknown",
        stranded_project: str | None = None,
    ) -> None:
        """Queue a coalesced bead-confirmation warmup once a load has applied.

        No-op before the first agents load (the loader path owns first paint)
        and while a scan is already queued. If a scan is mid-flight, mark a
        trailing request so a burst of refreshes (auto-refresh, ``sdd/beads``
        watcher, launch fan-out) collapses to a single follow-up scan rather
        than overlapping bead-store reads.
        """
        if stranded_project:
            forced = getattr(self, "_bead_warmup_forced_projects", None)
            if not isinstance(forced, set):
                forced = set()
                self._bead_warmup_forced_projects = forced
            forced.add(stranded_project)
            if source == "stranded_resolve":
                immediate = getattr(
                    self, "_bead_warmup_forced_immediate_projects", None
                )
                if not isinstance(immediate, set):
                    immediate = set()
                    self._bead_warmup_forced_immediate_projects = immediate
                immediate.add(stranded_project)
        if not self._agents_first_load_done:
            return
        if self._bead_warmup_scan_running:
            self._bead_warmup_scan_pending = True
            return
        if self._bead_warmup_scan_scheduled:
            return
        if (
            getattr(self, "current_tab", "agents") != "agents"
            and source != "stranded_resolve"
        ):
            return
        candidates = self._bead_warmup_candidates(
            force_stranded=source == "stranded_resolve",
            force_stranded_immediate=source == "stranded_resolve",
        )
        if not candidates:
            return
        self._bead_warmup_scan_scheduled = True
        self._bead_warmup_scan_source = source
        self._bead_warmup_scheduled_candidates = candidates
        self._spawn_bead_confirmation_warmup_task()

    def _spawn_bead_confirmation_warmup_task(self) -> None:
        """Run a bead warmup outside Textual's serial app message pump."""
        task = spawn_pump_free_task(
            self,
            self._run_bead_confirmation_warmup(),
            name="sase-agents-bead-warmup",
            registry_attr="_bead_warmup_async_tasks",
        )
        if task is None:
            self._bead_warmup_scan_scheduled = False

    async def _run_bead_confirmation_warmup(self) -> None:
        """Confirm bead candidates off-thread, then patch confirmed rows.

        Defers behind the navigation gate so the post-await apply leg never
        lands mid j/k burst. The bead-store reads run in a worker thread;
        results are keyed by agent identity so they re-attach correctly even if
        an interleaved refresh rebuilt the agent list while the worker ran.
        """
        source = self._bead_warmup_scan_source
        blocked_for = self._warmup_activity_blocked_for()
        if blocked_for is not None:
            self.set_timer(  # type: ignore[attr-defined]
                blocked_for,
                self._spawn_bead_confirmation_warmup_task,
            )
            return
        candidates: _AgentBeadWarmupCandidates | None = getattr(
            self, "_bead_warmup_scheduled_candidates", None
        )
        self._bead_warmup_scan_scheduled = False
        self._bead_warmup_scheduled_candidates = None
        if candidates is None:
            candidates = self._bead_warmup_candidates(
                force_stranded=source == "stranded_resolve",
                force_stranded_immediate=source == "stranded_resolve",
            )
        if not candidates:
            self._bead_warmup_scan_pending = False
            return
        self._bead_warmup_scan_running = True
        retry_sweep = candidates.stranded_scan_more
        failed = False
        try:
            warmup_telemetry = (
                {
                    "bead_display_candidates_examined": 0,
                    "bead_display_fingerprint_probes": 0,
                    "bead_display_heavy_resolutions": 0,
                    "bead_display_changed_outcomes": 0,
                    "bead_display_unchanged_outcomes": 0,
                    "wait_bead_status_candidates_examined": 0,
                    "wait_bead_status_fingerprint_probes": 0,
                    "wait_bead_status_heavy_resolutions": 0,
                    "wait_bead_status_heavy_items": 0,
                    "wait_bead_status_changed_outcomes": 0,
                    "wait_bead_status_unchanged_outcomes": 0,
                    "follow_progress_candidates_examined": 0,
                    "follow_progress_fingerprint_probes": 0,
                    "follow_progress_heavy_resolutions": 0,
                    "follow_progress_heavy_items": 0,
                    "follow_progress_changed_outcomes": 0,
                    "follow_progress_unchanged_outcomes": 0,
                    "stranded_candidates_examined": 0,
                    "stranded_fingerprint_probes": 0,
                    "stranded_heavy_resolutions": 0,
                    "stranded_changed_outcomes": 0,
                    "stranded_unchanged_outcomes": 0,
                }
                if tui_trace_enabled()
                else None
            )
            with tui_trace(
                "agents.bead_confirmation_warmup",
                candidates=candidates.total_count,
                candidates_examined=candidates.candidates_examined,
                bead_display_candidates=len(candidates.bead_display_agents),
                wait_bead_status_candidates=len(candidates.wait_bead_status_agents),
                follow_progress_candidates=len(candidates.follow_progress_agents),
                stranded_candidates=(
                    len(candidates.stranded_projects)
                    + len(candidates.force_stranded_projects)
                ),
                candidate_causes=dict(candidates.cause_counts),
                stranded_scan_more=candidates.stranded_scan_more,
                pending_retry=int(
                    source == "bead_warmup_followup"
                    or getattr(self, "_bead_warmup_scan_pending", False)
                ),
                source=self._bead_warmup_scan_source,
            ) as extra:
                if warmup_telemetry is None:
                    results = await asyncio.to_thread(
                        _warm_agent_bead_caches,
                        candidates,
                    )
                else:
                    results = await asyncio.to_thread(
                        _warm_agent_bead_caches,
                        candidates,
                        telemetry=warmup_telemetry,
                    )
                    extra.update(warmup_telemetry)
            forced: set[str] = getattr(self, "_bead_warmup_forced_projects", set())
            if isinstance(forced, set):
                forced.difference_update(candidates.force_stranded_projects)
            immediate: set[str] = getattr(
                self, "_bead_warmup_forced_immediate_projects", set()
            )
            if isinstance(immediate, set):
                immediate.difference_update(candidates.force_stranded_projects)
            blocked_for = self._warmup_activity_blocked_for()
            if blocked_for is None:
                self._apply_bead_warmup_results(results)
            elif results:
                self.set_timer(  # type: ignore[attr-defined]
                    blocked_for,
                    lambda: self._apply_bead_warmup_results(results),
                )
        except Exception:
            failed = True
            log.exception("Bead confirmation warmup failed")
            if candidates.force_stranded_projects:
                self._bead_warmup_scan_pending = True
        finally:
            self._bead_warmup_scan_running = False
            pending_request = self._bead_warmup_scan_pending
            self._bead_warmup_scan_pending = False
            from ._roster_generation import get_roster_generation

            same_roster = get_roster_generation(self) == candidates.roster_generation
            if (pending_request or (retry_sweep and same_roster)) and (
                getattr(self, "current_tab", "agents") == "agents"
                or self._bead_warmup_forced_projects_pending()
            ):
                delay = max(0.05, 1.0 if failed else (0.25 if retry_sweep else 0.0))
                self.set_timer(  # type: ignore[attr-defined]
                    delay,
                    lambda: self._schedule_bead_confirmation_warmup(
                        source="bead_warmup_followup"
                    ),
                )

    def _warmup_activity_blocked_for(self) -> float | None:
        """Return a retry delay while navigation or prompt typing is active."""
        if self._nav_gate.is_navigating():
            return max(0.05, self._nav_gate.time_until_idle() + 0.05)
        prompt_active = getattr(self, "_prompt_input_active", None)
        if callable(prompt_active):
            try:
                if prompt_active():
                    return 0.5
            except Exception:  # noqa: BLE001 - activity gates fail open.
                pass
        return None

    def _bead_warmup_forced_projects_pending(self) -> bool:
        forced = getattr(self, "_bead_warmup_forced_projects", ())
        return bool(forced)

    def _bead_warmup_candidates(
        self,
        *,
        force_stranded: bool = False,
        force_stranded_immediate: bool = False,
    ) -> _AgentBeadWarmupCandidates:
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

        return _AgentBeadWarmupCandidates(
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

    def _apply_bead_warmup_results(
        self,
        results: _AgentBeadWarmupResults,
    ) -> None:
        """Patch rows whose confirmed bead state changed on the UI thread.

        Matches results back to the *current* agent objects by identity (the
        list may have been rebuilt since the worker snapshot). Only rows whose
        confirmed state changed appear in *results*, so this patches exactly the
        rows that gained or lost the bead glyph; the confirmed string itself
        lives in the bead cache that row rendering reads. ``_try_patch_agent_row``
        is a no-op off the Agents tab, where the warmed cache simply feeds the
        next render.
        """
        if not results:
            return
        blocked_for = self._warmup_activity_blocked_for()
        if blocked_for is not None:
            self.set_timer(  # type: ignore[attr-defined]
                blocked_for,
                lambda: self._apply_bead_warmup_results(results),
            )
            return
        if getattr(self, "current_tab", "agents") != "agents":
            return

        from ._roster_generation import get_roster_generation

        generation = get_roster_generation(self)
        if getattr(self, "_bead_warmup_index_generation", None) != generation:
            self._refresh_bead_warmup_indexes(generation)
        current_by_identity = getattr(self, "_bead_warmup_agent_by_identity", {})
        surfaced_agents = self._surfaced_bead_warmup_agents()
        surfaced_by_identity = {
            agent.identity: current_by_identity.get(agent.identity, agent)
            for agent in surfaced_agents
        }

        wait_status_maps = None
        needs_rebuild = False
        changed_identities = {
            *results.bead_display_results,
            *results.wait_bead_status_identities,
            *results.follow_progress_identities,
        }
        if results.stranded_warmed_projects:
            try:
                from ._stranded_toasts import announce_stranded_transitions

                announce_stranded_transitions(
                    self.notify,  # type: ignore[attr-defined]
                    results.stranded_warmed_projects,
                )
            except Exception:
                log.debug("stranded toast compare failed", exc_info=True)
        if results.stranded_changed_projects:
            from ...models._agent_clan import clan_members

            for identity, candidate in surfaced_by_identity.items():
                project_keys = {
                    stranded_project_key_for_agent(candidate),
                }
                if candidate.is_clan_container:
                    project_keys.update(
                        stranded_project_key_for_agent(member)
                        for member in clan_members(candidate)
                    )
                project_keys.discard(None)
                if project_keys & results.stranded_changed_projects:
                    changed_identities.add(identity)
        if results.wait_bead_status_identities:
            from ...models._agent_clan import clan_members

            for identity, candidate in surfaced_by_identity.items():
                if not candidate.is_clan_container:
                    continue
                if any(
                    member.identity in results.wait_bead_status_identities
                    for member in clan_members(candidate)
                ):
                    changed_identities.add(identity)

        for identity, target in surfaced_by_identity.items():
            if identity not in changed_identities:
                continue
            wait_counts = None
            if identity in results.wait_bead_status_identities:
                if wait_status_maps is None:
                    wait_status_maps = agent_wait_status_maps_for_app(self)
                    if wait_status_maps is None:
                        from ...agent_completion import collect_agent_wait_status_maps

                        wait_status_maps = collect_agent_wait_status_maps(
                            self._agents_with_children or self._agents
                        )
                wait_counts = wait_dependency_status_counts(
                    target,
                    wait_status_maps,
                    cached_wait_bead_status_snapshot(target),
                )
            patched = self._try_patch_agent_row(  # type: ignore[attr-defined]
                target,
                wait_dependency_counts=wait_counts,
            )
            if not patched:
                needs_rebuild = True

        if results.stranded_changed_projects:
            update_info = getattr(self, "_update_agents_info_panel", None)
            if callable(update_info) and getattr(self, "current_tab", None) == "agents":
                update_info()

        if needs_rebuild:
            refresh = getattr(self, "_refresh_agents_display", None)
            if callable(refresh):
                refresh(list_changed=True, defer_detail=True)
