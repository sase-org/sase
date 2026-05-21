"""Refresh coalescing and async scheduling for agent loading."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from ._loading_state import AgentLoadingStateMixin

log = logging.getLogger(__name__)

# Seconds of input idleness required before the deferred Tier 2
# full-history reconcile is scheduled in the background. Picked to land
# well outside any j/k burst while still completing before the user
# would typically reach for historic data.
TIER2_RECONCILE_IDLE_THRESHOLD_S = 30.0

# Delay (seconds) between the first incomplete-history Tier 1 apply and
# the one-shot startup Tier 2 reconcile eligibility check. The check still
# obeys the idle/prompt gates below; it exists so already-idle sessions can
# converge promptly without bypassing input-latency protections.
STARTUP_TIER2_RECONCILE_DELAY_S = 2.0


class AgentLoadingRefreshMixin(AgentLoadingStateMixin):
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
        if self._agents_loading:
            self._agents_refresh_pending = True
            if full_history:
                self._agents_refresh_pending_full_history = True
            return
        if self._agents_refresh_scheduled:
            self._agents_refresh_pending = True
            if full_history:
                self._agents_refresh_pending_full_history = True
            return
        self._agents_refresh_scheduled = True
        self._agents_refresh_scheduled_full_history = full_history
        self.call_later(self._run_agents_async_refresh)  # type: ignore[attr-defined]

    def _maybe_trigger_idle_tier2_reconcile(
        self, *, now_mono: float | None = None
    ) -> bool:
        """Schedule the deferred Tier 2 reconcile once the user is idle.

        Returns True iff a refresh was scheduled. The reconcile is the
        single largest startup span (~2.7 s) and is deferred until input
        has been quiet for ``TIER2_RECONCILE_IDLE_THRESHOLD_S``; the
        idle window is measured from the later of the last recorded
        keypress and the moment the pending flag was armed, so users
        who never touch input still get the reconcile in the
        background.
        """
        if not getattr(self, "_agents_history_reconcile_pending", False):
            return False
        prompt_input_active = getattr(self, "_prompt_input_active", None)
        if callable(prompt_input_active) and prompt_input_active():
            return False
        if self._agents_loading or self._agents_refresh_scheduled:
            return False
        cur = time.monotonic() if now_mono is None else now_mono
        last_activity = getattr(self, "_last_activity_time", 0.0)
        armed_at = getattr(self, "_agents_history_reconcile_armed_mono", 0.0)
        reference = max(last_activity, armed_at)
        if reference <= 0.0:
            return False
        if cur - reference < TIER2_RECONCILE_IDLE_THRESHOLD_S:
            return False
        self._agents_history_reconcile_pending = False
        self._schedule_agents_async_refresh(full_history=True)
        return True

    def _fire_startup_tier2_reconcile(self) -> None:
        """One-shot startup Tier 2 reconcile trigger.

        Checks ~``STARTUP_TIER2_RECONCILE_DELAY_S`` after the first
        incomplete-history apply whether the deferred full-history pass is
        eligible to run. The same prompt and idle gates used by the idle
        tick apply here, so startup never bypasses recent typing.
        """
        self._maybe_trigger_idle_tier2_reconcile()

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
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_full_history = False
        if self._agents_loading:
            self._agents_refresh_pending = True
            if full_history:
                self._agents_refresh_pending_full_history = True
            return
        self._agents_loading = True
        callbacks = list(self._agents_refresh_pending_callbacks)
        self._agents_refresh_pending_callbacks.clear()
        try:
            import inspect

            load_agents_async = self._load_agents_async
            if "full_history" in inspect.signature(load_agents_async).parameters:
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
                self._agents_refresh_pending_full_history = False
                self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
                    full_history=pending_full_history
                )
