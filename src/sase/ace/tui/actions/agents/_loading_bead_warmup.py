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
from typing import TYPE_CHECKING

from ...models.agent_bead import (
    should_resolve_bead_display,
    warm_confirmed_bead_displays,
)
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

log = logging.getLogger(__name__)


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
    _bead_warmup_async_tasks: set[asyncio.Task[None]]

    def _schedule_bead_confirmation_warmup(self, *, source: str = "unknown") -> None:
        """Queue a coalesced bead-confirmation warmup once a load has applied.

        No-op before the first agents load (the loader path owns first paint)
        and while a scan is already queued. If a scan is mid-flight, mark a
        trailing request so a burst of refreshes (auto-refresh, ``sdd/beads``
        watcher, launch fan-out) collapses to a single follow-up scan rather
        than overlapping bead-store reads.
        """
        if not self._agents_first_load_done:
            return
        if self._bead_warmup_scan_running:
            self._bead_warmup_scan_pending = True
            return
        if self._bead_warmup_scan_scheduled:
            return
        self._bead_warmup_scan_scheduled = True
        self._bead_warmup_scan_source = source
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
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(  # type: ignore[attr-defined]
                delay,
                self._spawn_bead_confirmation_warmup_task,
            )
            return
        self._bead_warmup_scan_scheduled = False
        candidates = self._bead_warmup_candidates()
        if not candidates:
            return
        self._bead_warmup_scan_running = True
        try:
            with tui_trace(
                "agents.bead_confirmation_warmup",
                candidates=len(candidates),
                source=self._bead_warmup_scan_source,
            ):
                results = await asyncio.to_thread(
                    warm_confirmed_bead_displays, candidates
                )
            self._apply_bead_warmup_results(results)
        except Exception:
            log.exception("Bead confirmation warmup failed")
        finally:
            self._bead_warmup_scan_running = False
            if self._bead_warmup_scan_pending:
                self._bead_warmup_scan_pending = False
                self._schedule_bead_confirmation_warmup(source="bead_warmup_followup")

    def _bead_warmup_candidates(self) -> list[Agent]:
        """Snapshot visible rows with a bead candidate that needs resolution.

        Bounded to the currently visible agents and to candidates whose cache
        entry is missing or expired (``should_resolve_bead_display``). Fresh
        known-missing and already-confirmed candidates are skipped, so rapid
        refreshes do not repeatedly re-resolve them until the cache TTL expires.
        """
        candidates: list[Agent] = []
        for agent in self._agents:
            if should_resolve_bead_display(agent):
                candidates.append(agent)
        return candidates

    def _apply_bead_warmup_results(
        self,
        results: dict[tuple[AgentType, str, str | None], bool],
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
        current_by_identity: dict[tuple[AgentType, str, str | None], Agent] = {}
        for agent in self._agents_with_children:
            current_by_identity.setdefault(agent.identity, agent)
        for agent in self._agents:
            current_by_identity[agent.identity] = agent

        for identity in results:
            target = current_by_identity.get(identity)
            if target is None:
                continue
            self._try_patch_agent_row(target)  # type: ignore[attr-defined]
