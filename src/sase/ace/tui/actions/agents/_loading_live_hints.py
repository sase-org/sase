"""Deferred, coalesced live-workspace pencil-hint refresh for the Agents tab.

The loader's status-override pass classifies only the cheap *persisted* diff
badge (``diff_has_real_edits`` from a finalized ``diff_path``). The live
workspace edit hint for an active row requires a per-agent VCS probe
(``get_vcs_provider`` +
``diff_with_untracked``). Running that inline on the first agents load
dominated startup (hundreds of live diffs → ~18 s).

This mixin moves that work off the startup-critical loader path. After the
first agents load has applied, a coalesced background worker computes live
hints for active, non-terminal rows, runs the VCS probes off the event loop,
and patches the affected rows in place by identity. A persisted primary diff
remains the fallback for clean or unresolvable workspaces. Startup is no
longer gated on live VCS work; the pencil badge fills in shortly after the TUI
is already interactive.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sase.agent.status_buckets import agent_status_bucket

from ...models._agent_status_overrides import classify_live_file_change_hint
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

log = logging.getLogger(__name__)


def _agent_allows_live_hint(agent: Agent) -> bool:
    from sase.ace.tui.widgets.file_panel._diff import resolve_agent_diff_source

    source = resolve_agent_diff_source(agent)
    return agent_status_bucket(source) not in {"Done", "Failed"}


def carry_over_live_hints(
    previous_agents: list[Agent],
    current_agents: list[Agent],
) -> None:
    """Carry stale-while-revalidate live hints onto freshly loaded rows.

    Agents reloads rebuild ``Agent`` objects from disk, but the deferred live
    hint is intentionally in-memory row state. Preserve the last known boolean
    for rows that still qualify for a live hint; the scheduled background scan
    revalidates and patches any genuine changes.
    """
    previous_hints: dict[tuple[AgentType, str, str | None], bool] = {}
    for agent in previous_agents:
        hint = agent.live_file_change_hint
        if hint is None:
            continue
        previous_hints[agent.identity] = hint

    if not previous_hints:
        return

    for agent in current_agents:
        if agent.live_file_change_hint is not None:
            continue
        hint = previous_hints.get(agent.identity)
        if hint is None:
            continue
        if not _agent_allows_live_hint(agent):
            continue
        agent.live_file_change_hint = hint


class AgentLiveHintMixin(AgentLoadingStateMixin):
    """Schedule and apply deferred live-workspace pencil hints off startup."""

    # Coalescing state (initialized by ``_init_app_state``):
    #   ``_live_hints_scan_scheduled`` — a pump-free loop task is queued.
    #   ``_live_hints_scan_running``  — a worker is mid-flight (off-thread).
    #   ``_live_hints_scan_pending``  — a request arrived while one ran, so the
    #                                   in-flight worker re-arms itself on exit.
    #   ``_live_hints_scan_source``   — telemetry tag for the queued scan.
    _live_hints_scan_scheduled: bool
    _live_hints_scan_running: bool
    _live_hints_scan_pending: bool
    _live_hints_scan_source: str

    def _schedule_live_hint_refresh(self, *, source: str = "unknown") -> None:
        """Queue a coalesced live-hint scan once the first load has applied.

        No-op before the first agents load (the loader path owns first paint)
        and while a scan is already queued. If a scan is mid-flight, mark a
        trailing request so a burst of refreshes (auto-refresh, artifact
        watcher, launch fan-out) collapses to a single follow-up scan rather
        than overlapping VCS probe batches.
        """
        if not self._agents_first_load_done:
            return
        if self._live_hints_scan_running:
            self._live_hints_scan_pending = True
            return
        if self._live_hints_scan_scheduled:
            return
        self._live_hints_scan_scheduled = True
        self._live_hints_scan_source = source
        self._spawn_live_hint_refresh_task()

    def _spawn_live_hint_refresh_task(self) -> None:
        """Run the scan without making Textual's message pump await it."""
        task = spawn_pump_free_task(
            self,
            self._run_live_hint_refresh(),
            name="sase-agents-live-hints",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._live_hints_scan_scheduled = False

    async def _run_live_hint_refresh(self) -> None:
        """Compute live hints off-thread, then patch affected rows by identity.

        Defers behind the navigation gate so the post-await apply leg never
        lands mid j/k burst. The VCS work runs in a worker thread; results
        are keyed by agent identity so they re-attach correctly even if an
        interleaved refresh rebuilt the agent list while the worker ran.
        """
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            # Timer callbacks run on Textual's message pump, so the timer may
            # only invoke the synchronous spawner.
            self.set_timer(delay, self._spawn_live_hint_refresh_task)  # type: ignore[attr-defined]
            return
        self._live_hints_scan_scheduled = False
        candidates = self._live_hint_candidates()
        if not candidates:
            return
        self._live_hints_scan_running = True
        try:
            with tui_trace(
                "agents.live_hint_refresh",
                candidates=len(candidates),
                source=self._live_hints_scan_source,
            ):
                results = await asyncio.to_thread(_compute_live_hints, candidates)
            # Re-match against the current agent objects after the await; an
            # interleaved refresh may have rebuilt the list while VCS ran.
            self._apply_live_hint_results(results)
        except Exception:
            log.exception("Live workspace hint refresh failed")
        finally:
            self._live_hints_scan_running = False
            if self._live_hints_scan_pending:
                self._live_hints_scan_pending = False
                self._schedule_live_hint_refresh(source="live_hint_followup")

    def _live_hint_candidates(self) -> list[Agent]:
        """Snapshot visible rows that may need a live workspace hint.

        Scope is keyed on the *resolved diff source* so it stays consistent
        with both the detail panel and ``live_agent_file_change_hint``:

        - An ordinary row resolves to itself. Every active row qualifies even
          when it has a persisted primary fallback, because dirty live state
          has higher precedence.
        - A redirected root Plan row resolves to its active coder child, so it
          is included even when either row carries a persisted ``diff_path``.

        Source resolution is a cheap in-memory walk of plan/follow-up
        relationships; the actual VCS probe is offloaded to the background
        worker, which fails closed for rows whose workspace cannot be resolved.
        """
        from sase.ace.tui.widgets.file_panel._diff import resolve_agent_diff_source

        candidates: list[Agent] = []
        for agent in self._agents:
            source = resolve_agent_diff_source(agent)
            if agent_status_bucket(source) in {"Done", "Failed"}:
                continue
            candidates.append(agent)
        return candidates

    def _apply_live_hint_results(
        self,
        results: dict[tuple[AgentType, str, str | None], bool | None],
    ) -> None:
        """Apply computed hints on the UI thread and patch changed rows.

        Matches results back to the *current* agent objects by identity (the
        list may have been rebuilt since the worker snapshot). Only rows whose
        hint actually changed are patched; ``_try_patch_agent_row`` is a no-op
        off the Agents tab, but the in-memory hint still feeds the next full
        render.
        """
        if not results:
            return
        current_by_identity: dict[tuple[AgentType, str, str | None], Agent] = {}
        for agent in self._agents_with_children:
            current_by_identity.setdefault(agent.identity, agent)
        for agent in self._agents:
            current_by_identity[agent.identity] = agent

        for identity, hint in results.items():
            target = current_by_identity.get(identity)
            if target is None:
                continue
            if hint is None and target.live_file_change_hint is not None:
                continue
            if target.live_file_change_hint == hint:
                continue
            target.live_file_change_hint = hint
            self._try_patch_agent_row(target)  # type: ignore[attr-defined]


def _compute_live_hints(
    candidates: list[Agent],
) -> dict[tuple[AgentType, str, str | None], bool | None]:
    """Compute live workspace hints for *candidates* off the event loop.

    Returns a mapping keyed by agent identity (rather than object reference)
    so the result can be re-attached on the UI thread even when an interleaved
    refresh replaced the agent objects.
    """
    results: dict[tuple[AgentType, str, str | None], bool | None] = {}
    for agent in candidates:
        results[agent.identity] = classify_live_file_change_hint(agent)
    return results
