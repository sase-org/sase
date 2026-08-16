"""Deferred, coalesced agent-family plan-preview warmup.

Prompt-target completion rows must stay synchronous and memory-only: opening
``%wait:`` or ``#fork:`` cannot read plan files or bead storage. This mixin
warms the family-preview cache after Agents data has loaded, and also lets a
completion-menu open kick the same background lane when it sees an unresolved
family row. Finished batches do not patch rows; the next completion menu build
simply reads the now-warm cache.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ...models.agent_family_preview_cache import (
    should_resolve_family_plan_preview,
    warm_family_plan_previews,
)
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent

log = logging.getLogger(__name__)


class AgentFamilyPreviewMixin(AgentLoadingStateMixin):
    """Schedule deferred family plan-preview cache warmups off the UI path."""

    _family_preview_scan_scheduled: bool
    _family_preview_scan_running: bool
    _family_preview_scan_pending: bool
    _family_preview_scan_source: str
    _family_preview_async_tasks: set[asyncio.Task[None]]

    def _schedule_family_plan_preview_warmup(
        self,
        *,
        source: str = "unknown",
    ) -> None:
        """Queue a coalesced family-preview warmup once agents have loaded."""
        if not self._agents_first_load_done:
            return
        if self._family_preview_scan_running:
            self._family_preview_scan_pending = True
            return
        if self._family_preview_scan_scheduled:
            return
        self._family_preview_scan_scheduled = True
        self._family_preview_scan_source = source
        self._spawn_family_plan_preview_warmup_task()

    def _spawn_family_plan_preview_warmup_task(self) -> None:
        """Run the warmup outside Textual's serial app message pump."""
        task = spawn_pump_free_task(
            self,
            self._run_family_plan_preview_warmup(),
            name="sase-agents-family-previews",
            registry_attr="_family_preview_async_tasks",
        )
        if task is None:
            self._family_preview_scan_scheduled = False

    async def _run_family_plan_preview_warmup(self) -> None:
        """Resolve visible family previews off-thread under nav-gate deferral."""
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(  # type: ignore[attr-defined]
                delay,
                self._spawn_family_plan_preview_warmup_task,
            )
            return
        self._family_preview_scan_scheduled = False
        candidates = self._family_preview_candidates()
        if not candidates:
            return
        self._family_preview_scan_running = True
        try:
            with tui_trace(
                "agents.family_plan_preview_warmup",
                candidates=len(candidates),
                source=self._family_preview_scan_source,
            ):
                await asyncio.to_thread(warm_family_plan_previews, candidates)
        except Exception:
            log.exception("Family plan-preview warmup failed")
        finally:
            self._family_preview_scan_running = False
            if self._family_preview_scan_pending:
                self._family_preview_scan_pending = False
                self._schedule_family_plan_preview_warmup(
                    source="family_preview_followup"
                )

    def _family_preview_candidates(self) -> list[Agent]:
        """Snapshot visible family rows whose preview cache needs resolution."""
        candidates: list[Agent] = []
        for agent in self._agents:
            if should_resolve_family_plan_preview(agent):
                candidates.append(agent)
        return candidates
