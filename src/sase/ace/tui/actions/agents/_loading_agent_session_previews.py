"""Deferred, coalesced agent-session plan-preview warmup.

Prompt-target completion rows must stay synchronous and memory-only: opening
``%wait:`` or ``#fork:`` cannot read plan files or bead storage. This mixin
warms the session-preview cache after Agents data has loaded, and also lets a
completion-menu open kick the same background lane when it sees an unresolved
session row. Finished batches do not patch rows; the next completion menu build
simply reads the now-warm cache.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ...models.agent_session_preview_cache import (
    should_resolve_agent_session_plan_preview,
    warm_agent_session_plan_previews,
)
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace
from ._loading_state import AgentLoadingStateMixin

if TYPE_CHECKING:
    from ...models import Agent

log = logging.getLogger(__name__)


class AgentSessionPreviewMixin(AgentLoadingStateMixin):
    """Schedule deferred session plan-preview cache warmups off the UI path."""

    _agent_session_preview_scan_scheduled: bool
    _agent_session_preview_scan_running: bool
    _agent_session_preview_scan_pending: bool
    _agent_session_preview_scan_source: str
    _agent_session_preview_async_tasks: set[asyncio.Task[None]]

    def _schedule_agent_session_plan_preview_warmup(
        self,
        *,
        source: str = "unknown",
    ) -> None:
        """Queue a coalesced session-preview warmup once agents have loaded."""
        if not self._agents_first_load_done:
            return
        if self._agent_session_preview_scan_running:
            self._agent_session_preview_scan_pending = True
            return
        if self._agent_session_preview_scan_scheduled:
            return
        self._agent_session_preview_scan_scheduled = True
        self._agent_session_preview_scan_source = source
        self._spawn_agent_session_plan_preview_warmup_task()

    def _spawn_agent_session_plan_preview_warmup_task(self) -> None:
        """Run the warmup outside Textual's serial app message pump."""
        task = spawn_pump_free_task(
            self,
            self._run_agent_session_plan_preview_warmup(),
            name="sase-agents-session-previews",
            registry_attr="_agent_session_preview_async_tasks",
        )
        if task is None:
            self._agent_session_preview_scan_scheduled = False

    async def _run_agent_session_plan_preview_warmup(self) -> None:
        """Resolve visible session previews off-thread under nav-gate deferral."""
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(  # type: ignore[attr-defined]
                delay,
                self._spawn_agent_session_plan_preview_warmup_task,
            )
            return
        self._agent_session_preview_scan_scheduled = False
        candidates = self._agent_session_preview_candidates()
        if not candidates:
            return
        self._agent_session_preview_scan_running = True
        try:
            with tui_trace(
                "agents.agent_session_plan_preview_warmup",
                candidates=len(candidates),
                source=self._agent_session_preview_scan_source,
            ):
                await asyncio.to_thread(warm_agent_session_plan_previews, candidates)
        except Exception:
            log.exception("Session plan-preview warmup failed")
        finally:
            self._agent_session_preview_scan_running = False
            if self._agent_session_preview_scan_pending:
                self._agent_session_preview_scan_pending = False
                self._schedule_agent_session_plan_preview_warmup(
                    source="agent_session_preview_followup"
                )

    def _agent_session_preview_candidates(self) -> list[Agent]:
        """Snapshot visible session rows whose preview cache needs resolution."""
        candidates: list[Agent] = []
        for agent in self._agents:
            if should_resolve_agent_session_plan_preview(agent):
                candidates.append(agent)
        return candidates
