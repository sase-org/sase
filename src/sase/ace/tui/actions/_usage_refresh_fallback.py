"""ACE fallback that requests due usage refreshes after first paint.

AXE is the primary scheduler. While ACE is open, this loop submits the same
coalesced durable refresh used by CLI and AXE so due work still runs when
AXE is absent. It never probes on the UI thread or the message pump. When
the scheduler owns collection (an enabled ``sase_job_usage_refresh`` job in
any routine), the loop stays quiet and lets the ``usage`` routine do the
work.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)

_USAGE_REFRESH_FALLBACK_TASKS = "_usage_refresh_fallback_tasks"
_USAGE_REFRESH_FALLBACK_INTERVAL_SECONDS = 60.0
_USAGE_REFRESH_JOB_SCRIPT = "sase_job_usage_refresh"


def _scheduler_owns_usage_collection() -> bool:
    """Return whether the scheduler owns subscription-usage collection."""
    from sase.axe.process import is_axe_running

    try:
        if not is_axe_running():
            return False
    except Exception:
        log.debug("ACE usage-refresh scheduler probe failed", exc_info=True)
        return False
    try:
        from sase.axe.config import load_axe_config

        config = load_axe_config()
    except Exception:
        log.debug("ACE usage-refresh axe config load failed", exc_info=True)
        return False
    for lumberjack in config.lumberjacks.values():
        for chop in lumberjack.chops:
            if not chop.enabled:
                continue
            if (chop.script or chop.name) == _USAGE_REFRESH_JOB_SCRIPT:
                return True
    return False


def _maybe_request_due_refresh() -> None:
    """Submit due usage work unless the scheduler owns collection."""
    from sase.llm_provider.usage.refresh import request_due_usage_refresh

    if _scheduler_owns_usage_collection():
        return
    request_due_usage_refresh(origin="ace")


class UsageRefreshFallbackMixin:
    """Mixin scheduling pump-free due usage refreshes while ACE is open."""

    def _schedule_usage_refresh_fallback(self: Any) -> None:
        """Start the due-refresh fallback after first paint."""
        spawn_pump_free_task(
            self,
            self._run_usage_refresh_fallback_loop(),
            name="sase-usage-refresh-fallback",
            registry_attr=_USAGE_REFRESH_FALLBACK_TASKS,
        )

    async def _run_usage_refresh_fallback_loop(self: Any) -> None:
        """Submit due work immediately, then every sixty seconds."""
        while True:
            try:
                await asyncio.to_thread(_maybe_request_due_refresh)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("ACE usage-refresh fallback failed", exc_info=True)
            await asyncio.sleep(_USAGE_REFRESH_FALLBACK_INTERVAL_SECONDS)
