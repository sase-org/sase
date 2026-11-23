"""Coalesced scheduling and off-thread execution for bead warmup.

This module owns the scan lifecycle: queueing a coalesced warmup once a load
has applied, running the bead-store reads off the event loop, and deferring
behind navigation or prompt activity. Candidate construction
(:meth:`_bead_warmup_candidates`) and result application
(:meth:`_apply_bead_warmup_results`) live in sibling mixins and are reached
through ``self`` so this module never imports a ``_``-prefixed name.
"""

from __future__ import annotations

import asyncio
import logging

from ...models.agent_bead import warm_confirmed_bead_displays
from ...models.agent_epic_follow_progress import warm_epic_follow_progress
from ...models.agent_stranded import warm_stranded_work_reports
from ...models.agent_wait_beads import warm_wait_bead_statuses
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import is_enabled as tui_trace_enabled, tui_trace
from ._loading_bead_warmup_types import (
    AgentBeadWarmupCandidates,
    AgentBeadWarmupResults,
)
from ._loading_state import AgentLoadingStateMixin

log = logging.getLogger(__name__)

__all__ = [
    "AgentBeadWarmupScanMixin",
]


def _warm_agent_bead_caches(
    candidates: AgentBeadWarmupCandidates,
    *,
    telemetry: dict[str, int] | None = None,
) -> AgentBeadWarmupResults:
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
    return AgentBeadWarmupResults(
        bead_display_results=bead_display_results,
        wait_bead_status_identities=wait_bead_status_identities,
        follow_progress_identities=follow_progress_identities,
        stranded_changed_projects=frozenset(stranded_changed),
        stranded_warmed_projects=frozenset(
            {*candidates.stranded_projects, *candidates.force_stranded_projects}
        ),
    )


class AgentBeadWarmupScanMixin(AgentLoadingStateMixin):
    """Schedule and run deferred bead-confirmation warmups off startup."""

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
    _bead_warmup_scheduled_candidates: AgentBeadWarmupCandidates | None
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
        candidates = self._bead_warmup_candidates(  # type: ignore[attr-defined]
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
        candidates: AgentBeadWarmupCandidates | None = getattr(
            self, "_bead_warmup_scheduled_candidates", None
        )
        self._bead_warmup_scan_scheduled = False
        self._bead_warmup_scheduled_candidates = None
        if candidates is None:
            candidates = self._bead_warmup_candidates(  # type: ignore[attr-defined]
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
                    "stranded_liveness_checks": 0,
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
                self._apply_bead_warmup_results(results)  # type: ignore[attr-defined]
            elif results:
                self.set_timer(  # type: ignore[attr-defined]
                    blocked_for,
                    lambda: self._apply_bead_warmup_results(results),  # type: ignore[attr-defined]
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
