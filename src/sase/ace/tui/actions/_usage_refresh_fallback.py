"""ACE fallback that requests due usage refreshes after first paint.

AXE is the primary scheduler. While ACE is open, this loop submits the same
coalesced durable refresh used by CLI and AXE so due work still runs when
AXE is absent. It never probes on the UI thread or the message pump.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)

_USAGE_REFRESH_FALLBACK_TASKS = "_usage_refresh_fallback_tasks"


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
        """Submit due work immediately, then on the configured cadence."""
        from sase.llm_provider.usage.config import get_usage_metrics_settings
        from sase.llm_provider.usage.refresh import request_due_usage_refresh

        while True:
            try:
                await asyncio.to_thread(request_due_usage_refresh, origin="ace")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("ACE usage-refresh fallback failed", exc_info=True)
            try:
                interval = max(
                    float(get_usage_metrics_settings().refresh_seconds), 60.0
                )
            except Exception:
                interval = 300.0
            await asyncio.sleep(interval)
