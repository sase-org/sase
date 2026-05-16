"""Refresh coalescing and async scheduling for agent loading."""

from __future__ import annotations

import logging
from collections.abc import Callable

from ...util.trace import tui_trace
from ._loading_state import AgentLoadingStateMixin

log = logging.getLogger(__name__)


class AgentLoadingRefreshMixin(AgentLoadingStateMixin):
    """Methods that debounce and schedule asynchronous agent refreshes."""

    def _reserve_agents_load_generation(self) -> int:
        """Reserve a monotonic generation for one logical agent load."""
        generation = getattr(self, "_agents_load_request_generation", 0) + 1
        self._agents_load_request_generation = generation
        self._agents_load_latest_scheduled_generation = generation
        return generation

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
            source: Tag for telemetry / debug only — currently advisory.
            debounce_ms: Window during which subsequent requests are
                absorbed.
            latest_only: When True (default), an already-armed timer is
                left in place — the deferred refresh will pick up the
                latest on-disk state after the burst settles. When False,
                each request restarts the debounce window.
        """
        del source
        if self._agents_refresh_debounce_armed and latest_only:
            return
        self._agents_refresh_debounce_armed = True
        delay = max(0.0, debounce_ms / 1000.0)
        self.set_timer(delay, self._fire_debounced_agents_refresh)  # type: ignore[attr-defined]

    def _fire_debounced_agents_refresh(self) -> None:
        """Debounce-timer callback that posts the deferred refresh."""
        self._agents_refresh_debounce_armed = False
        self._schedule_agents_async_refresh()

    def _schedule_agents_async_refresh(
        self,
        *,
        full_history: bool = False,
        on_complete: Callable[[], None] | None = None,
        _reserved_generation: int | None = None,
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
        if on_complete is not None:
            self._agents_refresh_pending_callbacks.append(on_complete)
        generation = _reserved_generation or self._reserve_agents_load_generation()
        if self._agents_loading:
            self._agents_refresh_pending = True
            self._agents_refresh_pending_generation = generation
            if full_history:
                self._agents_refresh_pending_full_history = True
            return
        if self._agents_refresh_scheduled:
            self._agents_refresh_pending = True
            self._agents_refresh_pending_generation = generation
            if full_history:
                self._agents_refresh_pending_full_history = True
            return
        self._agents_refresh_scheduled = True
        self._agents_refresh_scheduled_full_history = full_history
        self._agents_refresh_scheduled_generation = generation
        self.call_later(self._run_agents_async_refresh)  # type: ignore[attr-defined]

    async def _run_agents_async_refresh(self) -> None:
        """Run the async agent refresh with loading guard.

        Defers when the user is mid-burst on j/k: the apply/finalize/render
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
            self.set_timer(delay, self._run_agents_async_refresh)  # type: ignore[attr-defined]
            return
        full_history = getattr(self, "_agents_refresh_scheduled_full_history", False)
        generation = getattr(self, "_agents_refresh_scheduled_generation", 0)
        if generation <= 0:
            generation = self._reserve_agents_load_generation()
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_full_history = False
        self._agents_refresh_scheduled_generation = 0
        if self._agents_loading:
            self._agents_refresh_pending = True
            if getattr(self, "_agents_refresh_pending_generation", 0) <= 0:
                self._agents_refresh_pending_generation = (
                    self._reserve_agents_load_generation()
                )
            if full_history:
                self._agents_refresh_pending_full_history = True
            return
        self._agents_loading = True
        callbacks = list(self._agents_refresh_pending_callbacks)
        self._agents_refresh_pending_callbacks.clear()
        try:
            import inspect

            load_agents_async = self._load_agents_async
            parameters = inspect.signature(load_agents_async).parameters
            with tui_trace(
                "agents.async_refresh",
                generation=generation,
                full_history=full_history,
            ):
                if "generation" in parameters and "full_history" in parameters:
                    await load_agents_async(
                        full_history=full_history, generation=generation
                    )
                elif "full_history" in parameters:
                    await load_agents_async(full_history=full_history)
                else:
                    await load_agents_async()
        finally:
            self._agents_loading = False
            for cb in callbacks:
                try:
                    cb()
                except Exception:
                    log.exception("agents async refresh callback failed")
            # If a refresh was requested while we were running, schedule one
            # more pass so the UI reflects the latest on-disk state.
            if self._agents_refresh_pending:
                self._agents_refresh_pending = False
                pending_full_history = getattr(
                    self, "_agents_refresh_pending_full_history", False
                )
                pending_generation = getattr(
                    self, "_agents_refresh_pending_generation", 0
                )
                self._agents_refresh_pending_full_history = False
                self._agents_refresh_pending_generation = 0
                self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
                    full_history=pending_full_history,
                    _reserved_generation=pending_generation or None,
                )
