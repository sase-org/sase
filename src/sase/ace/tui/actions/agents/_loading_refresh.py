"""Refresh coalescing and async scheduling for agent loading.

This module is the public facade for :class:`AgentLoadingRefreshMixin`.
Exact artifact-delta work and periodic refresh triggers live in narrow
private mixins so each implementation file remains focused.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from inspect import Parameter, signature
from typing import Any

from ._loading_refresh_delta import AgentArtifactDeltaRefreshMixin
from ._loading_refresh_polling import (
    AgentRefreshPollingMixin,
    TIER1_INDEX_REVALIDATE_INPUT_QUIET_THRESHOLD_S as TIER1_INDEX_REVALIDATE_INPUT_QUIET_THRESHOLD_S,
    TIER1_INDEX_REVALIDATE_MIN_INTERVAL_S as TIER1_INDEX_REVALIDATE_MIN_INTERVAL_S,
    TIER1_INDEX_REVALIDATE_SOURCE as TIER1_INDEX_REVALIDATE_SOURCE,
    TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S as TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S,
)
from ._refresh_trace import (
    classify_agents_data_cost,
    infer_broad_load_fallback_reason,
    normalize_refresh_source as _normalize_refresh_source,
    record_agents_refresh_trace,
)
from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import trace_event, tui_trace

log = logging.getLogger(__name__)


def _callable_accepts_kwarg(callback: Callable[..., object], name: str) -> bool:
    try:
        params = signature(callback).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind == Parameter.VAR_KEYWORD or p.name == name for p in params)


class AgentLoadingRefreshMixin(
    AgentRefreshPollingMixin,
    AgentArtifactDeltaRefreshMixin,
):
    """Methods that debounce and schedule asynchronous agent refreshes."""

    def request_agents_refresh(
        self,
        source: str,
        *,
        debounce_ms: int = 150,
        latest_only: bool = True,
    ) -> None:
        """Request a coalesced agents refresh.

        Multiple calls within ``debounce_ms`` collapse into one refresh,
        so launch fan-out (multi-prompt, multi-model, repeat, bulk) does
        not schedule a refresh per spawned agent. The deferred refresh
        still routes through :meth:`_schedule_agents_async_refresh`, so
        the navigation-gate and last-request-wins guards in
        :meth:`_run_agents_async_refresh` remain in force.

        Args:
            source: Tag for telemetry / debug only.
            debounce_ms: Window during which subsequent requests are
                absorbed.
            latest_only: When True (default), an already-armed timer is
                left in place — the deferred refresh will pick up the
                latest on-disk state after the burst settles. When False,
                each request restarts the debounce window.
        """
        source = _normalize_refresh_source(source)
        if self._agents_refresh_debounce_armed and latest_only:
            return
        self._agents_refresh_debounce_armed = True
        self._agents_refresh_debounce_source = source
        delay = max(0.0, debounce_ms / 1000.0)
        self.set_timer(  # type: ignore[attr-defined]
            delay,
            partial(self._fire_debounced_agents_refresh, source),
        )

    def _fire_debounced_agents_refresh(self, source: str | None = None) -> None:
        """Debounce-timer callback that posts the deferred refresh."""
        source = _normalize_refresh_source(
            source or getattr(self, "_agents_refresh_debounce_source", "unknown")
        )
        self._agents_refresh_debounce_armed = False
        self._agents_refresh_debounce_source = "unknown"
        self._schedule_agents_async_refresh(source=source)

    def _schedule_agents_async_refresh(
        self,
        *,
        source: str = "unknown",
        full_history: bool = False,
        full_history_reason: str | None = None,
        revalidate_index: bool = False,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Schedule an async agent reload without blocking.

        If a refresh is already in flight, mark a pending follow-up so the
        in-flight run re-schedules itself once it finishes. This gives
        last-request-wins semantics: a stampede of refresh requests
        produces at most two full loads (the one already running plus one
        follow-up), and the final UI state reflects whatever was on disk
        after the last trigger.

        ``on_complete``, when supplied, runs on the UI thread after the
        apply step of the next refresh that actually executes. Callbacks
        accumulate and fire in FIFO order; a callback only runs once.
        """
        source = _normalize_refresh_source(source)
        if on_complete is not None:
            self._agents_refresh_pending_callbacks.append(on_complete)
        if (
            self._agents_loading
            or self._agents_refresh_scheduled
            or getattr(self, "_agents_artifact_delta_scheduled", None) is not None
        ):
            self._agents_refresh_pending = True
            self._agents_refresh_pending_source = source
            if full_history:
                self._agents_refresh_pending_full_history = True
                self._agents_refresh_pending_full_history_reason = (
                    full_history_reason or "coalesced_full_history_refresh"
                )
            if revalidate_index:
                self._agents_refresh_pending_revalidate_index = True
            return
        self._agents_refresh_scheduled = True
        self._agents_refresh_scheduled_source = source
        self._agents_refresh_scheduled_full_history = full_history
        self._agents_refresh_scheduled_full_history_reason = (
            full_history_reason if full_history else None
        )
        self._agents_refresh_scheduled_revalidate_index = revalidate_index
        data_cost = classify_agents_data_cost(full_history=full_history)
        fallback_reason = infer_broad_load_fallback_reason(
            source=source,
            full_history_reason=full_history_reason if full_history else None,
        )
        trace_event(
            "agents.refresh_scheduled",
            source=source,
            full_history=full_history,
            full_history_reason=full_history_reason,
            index_freshness="revalidate" if revalidate_index else "cached",
            data_cost=data_cost,
            fallback_reason=fallback_reason,
        )
        record_agents_refresh_trace(
            self,
            stage="scheduled",
            source=source,
            data_cost=data_cost,
            fallback_reason=fallback_reason,
            full_history=full_history,
            index_freshness="revalidate" if revalidate_index else "cached",
        )
        self._spawn_agents_refresh_task()

    def _spawn_agents_refresh_task(self) -> None:
        """Run a refresh outside Textual's serial app message pump."""
        task = spawn_pump_free_task(
            self,
            self._run_agents_async_refresh(),
            name="sase-agents-refresh",
            registry_attr="_agents_refresh_async_tasks",
        )
        if task is None:
            self._agents_refresh_scheduled = False

    async def _run_agents_async_refresh(self) -> None:
        """Run the async agent refresh with loading guard.

        This coroutine runs as an app-held asyncio task, not as a Textual
        ``call_later`` callback, so awaiting a slow loader cannot starve the
        app's serial message pump. Defers when the user is mid-burst on j/k:
        the apply/finalize/render
        leg of this refresh runs on the UI thread and would block the event
        loop through the user's first navigation burst after a launch (or
        any other state-mutating action that triggered a refresh). Re-arm
        via ``set_timer`` for the gate boundary; ``_agents_refresh_scheduled``
        stays True so concurrent triggers collapse into the
        ``_agents_refresh_pending`` flag rather than scheduling duplicate
        timers.
        """
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(delay, self._spawn_agents_refresh_task)  # type: ignore[attr-defined]
            return
        full_history = getattr(self, "_agents_refresh_scheduled_full_history", False)
        full_history_reason = getattr(
            self, "_agents_refresh_scheduled_full_history_reason", None
        )
        revalidate_index = getattr(
            self, "_agents_refresh_scheduled_revalidate_index", False
        )
        source = _normalize_refresh_source(
            getattr(self, "_agents_refresh_scheduled_source", "unknown")
        )
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_source = "unknown"
        self._agents_refresh_scheduled_full_history = False
        self._agents_refresh_scheduled_full_history_reason = None
        self._agents_refresh_scheduled_revalidate_index = False
        if self._agents_loading:
            self._agents_refresh_pending = True
            self._agents_refresh_pending_source = source
            if full_history:
                self._agents_refresh_pending_full_history = True
                self._agents_refresh_pending_full_history_reason = (
                    full_history_reason or "coalesced_full_history_refresh"
                )
            if revalidate_index:
                self._agents_refresh_pending_revalidate_index = True
            return
        self._agents_loading = True
        self._agents_refresh_active_source = source
        callbacks = list(self._agents_refresh_pending_callbacks)
        self._agents_refresh_pending_callbacks.clear()
        try:
            load_agents_async = self._load_agents_async
            kwargs: dict[str, Any] = {}
            if _callable_accepts_kwarg(load_agents_async, "full_history"):
                kwargs["full_history"] = full_history
            if _callable_accepts_kwarg(load_agents_async, "source"):
                kwargs["source"] = source
            if _callable_accepts_kwarg(load_agents_async, "index_freshness"):
                kwargs["index_freshness"] = (
                    "revalidate" if revalidate_index else "cached"
                )
            if full_history and "full_history" in kwargs:
                reason = full_history_reason or "unspecified_full_history_refresh"
                log.info("agents full-history refresh requested: %s", reason)
                with tui_trace(
                    "agents.full_history_refresh",
                    reason=reason,
                    source=source,
                    data_cost="tier2_full_history",
                ):
                    await load_agents_async(**kwargs)
            else:
                await load_agents_async(**kwargs)
        finally:
            self._agents_loading = False
            self._agents_refresh_active_source = "unknown"
            for cb in callbacks:
                try:
                    cb()
                except Exception:
                    log.exception("agents async refresh callback failed")
            self._drain_pending_agents_refresh_work()
