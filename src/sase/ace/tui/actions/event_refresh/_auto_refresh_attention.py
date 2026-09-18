"""Remote-attention fallback polling for TUI auto-refresh."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ...util.pump_tasks import spawn_pump_free_task
from ._helpers import callable_accepts_kwarg

log = logging.getLogger(__name__)


class EventAutoRefreshAttentionMixin:
    """Mixin for scheduling narrow fallback attention-inventory polls."""

    def _fallback_record_attention_inventory_completion(
        self,
        *,
        result: Any,
        cache_only: bool,
        duration_ms: float,
        error: bool,
    ) -> None:
        """Record completion counters when only a bare poll function exists."""
        record_completion = getattr(
            self,
            "_record_fleet_attention_inventory_completion",
            None,
        )
        if callable(record_completion):
            return
        counters = dict(
            getattr(self, "_fleet_attention_inventory_completed_counters", {}) or {}
        )
        counters["fleet_attention_poll_batches"] = (
            int(counters.get("fleet_attention_poll_batches", 0)) + 1
        )
        cache_polls = getattr(result, "cache_polls", None)
        network_polls = getattr(result, "network_polls", None)
        counters["fleet_attention_cache_polls"] = int(
            counters.get("fleet_attention_cache_polls", 0)
        ) + (
            cache_polls
            if isinstance(cache_polls, int) and not isinstance(cache_polls, bool)
            else int(cache_only)
        )
        counters["fleet_attention_network_polls"] = int(
            counters.get("fleet_attention_network_polls", 0)
        ) + (
            network_polls
            if isinstance(network_polls, int) and not isinstance(network_polls, bool)
            else int(not cache_only)
        )
        changed = bool(result)
        result_error = bool(getattr(result, "error", False)) or error
        counters["fleet_attention_changed"] = int(
            counters.get("fleet_attention_changed", 0)
        ) + int(changed)
        counters["fleet_attention_errors"] = int(
            counters.get("fleet_attention_errors", 0)
        ) + int(result_error)
        counters["fleet_attention_duration_ms"] = round(
            float(counters.get("fleet_attention_duration_ms", 0.0)) + duration_ms,
            3,
        )
        counters["fleet_attention_modes"] = "cache" if cache_only else "network"
        counters["fleet_attention_outcome"] = (
            "error" if result_error else "changed" if changed else "unchanged"
        )
        self._fleet_attention_inventory_completed_counters = counters  # type: ignore[attr-defined]

    async def _run_fallback_attention_inventory_poll(
        self,
        poll_attention_inventory: Any,
        *,
        source: str,
        cache_only: bool,
    ) -> None:
        """Run a test-double/bare attention poll without blocking the tick."""
        self._fleet_attention_inventory_refresh_scheduled = False  # type: ignore[attr-defined]
        self._fleet_attention_inventory_refresh_running = True  # type: ignore[attr-defined]
        started = time.perf_counter()
        result: Any = None
        error = False
        try:
            kwargs: dict[str, Any] = {}
            if callable_accepts_kwarg(poll_attention_inventory, "source"):
                kwargs["source"] = source
            if callable_accepts_kwarg(poll_attention_inventory, "cache_only"):
                kwargs["cache_only"] = cache_only
            result = await poll_attention_inventory(**kwargs)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - fallback polling must not kill refresh.
            error = True
            log.debug("remote attention inventory fallback poll failed", exc_info=True)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
            self._fleet_attention_inventory_refresh_running = False  # type: ignore[attr-defined]
            self._fleet_attention_inventory_refresh_scheduled = False  # type: ignore[attr-defined]
        if bool(result):
            self._dirty_notifications = True
            schedule = getattr(self, "_schedule_notification_snapshot_refresh", None)
            if callable(schedule):
                schedule()
        self._fallback_record_attention_inventory_completion(
            result=result,
            cache_only=cache_only,
            duration_ms=duration_ms,
            error=error,
        )

    def _schedule_fallback_attention_inventory_poll(
        self,
        poll_attention_inventory: Any,
        *,
        source: str,
        cache_only: bool,
    ) -> bool:
        """Schedule a bare attention poll function for narrow test doubles."""
        if getattr(
            self, "_fleet_attention_inventory_refresh_running", False
        ) or getattr(
            self,
            "_fleet_attention_inventory_refresh_scheduled",
            False,
        ):
            return False
        self._fleet_attention_inventory_refresh_scheduled = True  # type: ignore[attr-defined]
        task = spawn_pump_free_task(
            self,
            self._run_fallback_attention_inventory_poll(
                poll_attention_inventory,
                source=source,
                cache_only=cache_only,
            ),
            name="sase-agents-fleet-attention-inventory",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._fleet_attention_inventory_refresh_scheduled = False  # type: ignore[attr-defined]
            return False
        return True
