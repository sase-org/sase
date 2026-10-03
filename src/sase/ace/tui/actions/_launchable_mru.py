"""App-owned launchable-MRU snapshot (epic sase-1ex, phase mru-snapshot).

``LaunchableMruMixin`` owns one immutable
:class:`~sase.ace.tui.launchable_mru.LaunchableMruSnapshot` on ``AceApp``.
A single-flight pump-free thread worker builds it; a ~2 s peek-token tick
plus explicit launch/set-current triggers keep it fresh. ``ctrl+n/p``
only peek it (see ``_vcs_mru_cycling``), so key paths do no disk I/O and
spawn no subprocesses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..launchable_mru import (
    COLD_LAUNCHABLE_MRU_SNAPSHOT,
    LaunchableMruSnapshot,
    build_launchable_mru_data,
)
from ..util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)

#: Peek-token tick cadence. The peek itself is a time-gated ``os.stat`` plus
#: config token, so this stays affordable; real builds run off-thread.
_MRU_TICK_SECONDS = 2.0

#: Forced recompute cadence, in ticks. Covers project-spec and Patch drift
#: the MRU peek token cannot see; gated on idle (no prompt, nav gate idle).
_MRU_RECOMPUTE_EVERY_TICKS = 30

__all__ = [
    "LaunchableMruMixin",
    "init_launchable_mru_state",
]


def init_launchable_mru_state(self: Any) -> None:
    """Initialize launchable-MRU snapshot state alongside other app state."""
    self._launchable_mru_snapshot = COLD_LAUNCHABLE_MRU_SNAPSHOT
    self._launchable_mru_generation = 0
    self._launchable_mru_build_in_flight = False
    self._launchable_mru_pending = None
    self._launchable_mru_token = None
    self._launchable_mru_last_signature = None
    self._launchable_mru_tick_count = 0
    self._launchable_mru_tick_timer = None
    self._pending_space_prefill = None
    self._macro_identity_warm_in_flight = False
    self._macro_identity_cold_fallback_pending = False


class LaunchableMruMixin:
    """Mixin owning the app's launchable-MRU snapshot and its worker."""

    _launchable_mru_snapshot: LaunchableMruSnapshot
    _launchable_mru_generation: int
    _launchable_mru_build_in_flight: bool
    _launchable_mru_pending: tuple[str, bool] | None
    _launchable_mru_token: tuple[object, ...] | None
    _launchable_mru_last_signature: tuple[object, ...] | None
    _launchable_mru_tick_count: int

    def _init_launchable_mru_state(self: Any) -> None:
        """Initialize launchable-MRU snapshot state (method alias)."""
        init_launchable_mru_state(self)

    def peek_launchable_mru_snapshot(self: Any) -> LaunchableMruSnapshot:
        """Return the current snapshot; memory-only, never blocks or reads."""
        snapshot = getattr(
            self, "_launchable_mru_snapshot", COLD_LAUNCHABLE_MRU_SNAPSHOT
        )
        if not isinstance(snapshot, LaunchableMruSnapshot):
            return COLD_LAUNCHABLE_MRU_SNAPSHOT
        return snapshot

    def mark_launchable_mru_refresh_pending(self: Any) -> None:
        """Flag the snapshot stale; pure memory, safe on the submit path."""
        try:
            snapshot = self.peek_launchable_mru_snapshot()
        except Exception:  # noqa: BLE001 - submit paths never fail on this.
            log.debug("Launchable MRU pending-mark skipped", exc_info=True)
            return
        self._launchable_mru_snapshot = snapshot.with_refresh_pending()

    def request_launchable_mru_refresh(
        self: Any, *, reason: str, force: bool = False
    ) -> bool:
        """Request a snapshot rebuild; single-flight, last request wins.

        Returns whether a build is now in flight (or was already). When a
        build is running, exactly one follow-up is remembered; it starts
        when the in-flight build publishes.
        """
        if getattr(self, "_launchable_mru_build_in_flight", False):
            self._launchable_mru_pending = (reason, force)
            return True
        self._launchable_mru_build_in_flight = True
        generation = getattr(self, "_launchable_mru_generation", 0) + 1
        task = spawn_pump_free_task(
            self,
            self._run_launchable_mru_build(
                generation=generation,
                last_signature=getattr(self, "_launchable_mru_last_signature", None),
                force=force,
            ),
            name="launchable-mru-build",
            registry_attr="_launchable_mru_tasks",
        )
        if task is None:
            self._launchable_mru_build_in_flight = False
            self._launchable_mru_pending = (reason, force)
            return False
        return True

    async def _run_launchable_mru_build(
        self: Any,
        *,
        generation: int,
        last_signature: tuple[object, ...] | None,
        force: bool,
    ) -> None:
        """Build the snapshot off-thread, then publish on the main thread.

        The ``asyncio.to_thread`` continuation resumes on the event-loop
        (app) thread, so the finish helpers are called directly: a
        ``call_from_thread`` here would raise ``RuntimeError``.
        """
        try:
            built = await asyncio.to_thread(
                build_launchable_mru_data,
                force=force,
                last_signature=last_signature,
            )
        except Exception as error:  # noqa: BLE001 - publish error, not stale.
            log.debug("Launchable MRU build failed: %s", error, exc_info=True)
            self._finish_launchable_mru_build_error(generation)
            return
        if built is None:
            self._finish_launchable_mru_build_skipped(generation)
            return
        signature, pairs, token = built
        self._finish_launchable_mru_build(
            generation,
            signature,
            tuple(pairs),
            token,
        )

    def _finish_launchable_mru_build(
        self: Any,
        generation: int,
        signature: tuple[object, ...],
        pairs: tuple[tuple[str, str], ...],
        token: tuple[object, ...],
    ) -> None:
        """Publish a finished build when its generation is still current."""
        if generation <= getattr(self, "_launchable_mru_generation", 0):
            return
        self._launchable_mru_snapshot = LaunchableMruSnapshot(
            state="ready",
            pairs=pairs,
            generation=generation,
            token=token,
            inputs_signature=signature,
        )
        self._launchable_mru_generation = generation
        self._launchable_mru_token = token
        self._launchable_mru_last_signature = signature
        self._drain_launchable_mru_build()
        if getattr(self, "_pending_space_prefill", None) is not None:
            try:
                from sase.ace.tui.actions.agent_workflow._space_prefill import (
                    try_apply_pending_space_prefill,
                )

                try_apply_pending_space_prefill(self, pairs)
            except Exception:  # noqa: BLE001 - late prefill never breaks publish.
                log.debug("Pending <space> prefill skipped", exc_info=True)

    def _finish_launchable_mru_build_skipped(self: Any, generation: int) -> None:
        """Close out a fast-path-skipped build; the snapshot stays current."""
        if generation <= getattr(self, "_launchable_mru_generation", 0):
            return
        self._drain_launchable_mru_build()

    def _finish_launchable_mru_build_error(self: Any, generation: int) -> None:
        """Publish an error snapshot; the next tick retries the build."""
        if generation <= getattr(self, "_launchable_mru_generation", 0):
            return
        self._launchable_mru_snapshot = LaunchableMruSnapshot(
            state="error",
            pairs=(),
            generation=generation,
            token=getattr(self, "_launchable_mru_token", None),
            inputs_signature=getattr(self, "_launchable_mru_last_signature", ()) or (),
        )
        self._launchable_mru_generation = generation
        self._drain_launchable_mru_build()
        # An error publish carries no prefill: drop the pending entry so the
        # blank bar stays blank instead of waiting on a stale session.
        try:
            self._pending_space_prefill = None
        except Exception:  # noqa: BLE001 - pending state is best-effort.
            pass

    def request_macro_project_identity_warm(self: Any) -> bool:
        """Request one off-thread macro-identity warm; single-flight.

        Memory-only on the keystroke path: when the registry is already
        built this returns ``False`` without spawning anything. Requests
        made while a warm is in flight coalesce and return ``True``.
        The warm runs ``warm_macro_project_identity()`` in a pump-free
        thread task and is cancelled at teardown with the other pump-free
        tasks. When the warm makes a previously cold fallback ready, the
        visible prompt surfaces are re-resolved once.
        """
        from sase.macro.project_identity import macro_project_identity_ready

        try:
            if macro_project_identity_ready():
                return False
        except Exception:  # noqa: BLE001 - readiness check never blocks.
            log.debug("Macro identity readiness check skipped", exc_info=True)
            return False
        if getattr(self, "_macro_identity_warm_in_flight", False):
            return True
        self._macro_identity_warm_in_flight = True
        self._macro_identity_cold_fallback_pending = True
        task = spawn_pump_free_task(
            self,
            self._run_macro_identity_warm(),
            name="macro-identity-warm",
            registry_attr="_macro_identity_warm_tasks",
        )
        if task is None:
            self._macro_identity_warm_in_flight = False
            return False
        return True

    async def _run_macro_identity_warm(self: Any) -> None:
        """Build the identity registry off-thread, then refresh surfaces.

        The ``asyncio.to_thread`` continuation resumes on the event-loop
        thread, so the refresh helper is called directly.
        """
        from sase.macro.project_identity import warm_macro_project_identity

        try:
            await asyncio.to_thread(warm_macro_project_identity)
        except Exception:  # noqa: BLE001 - warm never breaks the pump.
            log.debug("Macro identity warm failed", exc_info=True)
        finally:
            self._macro_identity_warm_in_flight = False
        self._maybe_refresh_visible_prompt_after_identity_warm()

    def _maybe_refresh_visible_prompt_after_identity_warm(self: Any) -> None:
        """Re-resolve visible prompt surfaces once identity becomes ready."""
        if not getattr(self, "_macro_identity_cold_fallback_pending", False):
            return
        try:
            from sase.macro.project_identity import macro_project_identity_ready

            if not macro_project_identity_ready():
                return
        except Exception:  # noqa: BLE001 - refresh is best-effort.
            return
        self._macro_identity_cold_fallback_pending = False
        refresher = getattr(self, "_refresh_visible_prompt_catalog_surfaces", None)
        if not callable(refresher):
            return
        try:
            refresher()
        except Exception:  # noqa: BLE001 - late refresh never breaks publish.
            log.debug("Post-warm prompt surface refresh skipped", exc_info=True)

    def _drain_launchable_mru_build(self: Any) -> None:
        """Mark the in-flight build done and start one pending follow-up."""
        self._launchable_mru_build_in_flight = False
        self._maybe_refresh_visible_prompt_after_identity_warm()
        pending = getattr(self, "_launchable_mru_pending", None)
        self._launchable_mru_pending = None
        if pending is not None:
            reason, force = pending
            self.request_launchable_mru_refresh(reason=reason, force=force)

    def _start_launchable_mru_warm_and_ticks(self: Any) -> None:
        """Warm the snapshot after first paint and arm the freshness tick."""
        try:
            self.request_launchable_mru_refresh(reason="startup")
        except Exception:  # noqa: BLE001 - warmup never breaks startup.
            log.debug("Launchable MRU startup warm skipped", exc_info=True)
        if getattr(self, "_launchable_mru_tick_timer", None) is not None:
            return
        try:
            self._launchable_mru_tick_timer = self.set_interval(
                _MRU_TICK_SECONDS,
                self._launchable_mru_tick,
                name="launchable-mru-tick",
            )
        except Exception:  # noqa: BLE001 - ticks are best-effort.
            log.debug("Launchable MRU tick not armed", exc_info=True)

    def _launchable_mru_tick(self: Any) -> None:
        """Peek the change token; rebuild on drift, recompute when idle."""
        try:
            from sase.current_project import peek_current_project_change_token

            snapshot = self.peek_launchable_mru_snapshot()
            if snapshot.state != "ready":
                self.request_launchable_mru_refresh(reason="tick-cold")
                return
            token = peek_current_project_change_token()
            if token != self._launchable_mru_token:
                self.request_launchable_mru_refresh(reason="token-drift")
                return
            self._launchable_mru_tick_count = (
                getattr(self, "_launchable_mru_tick_count", 0) + 1
            )
            if (
                self._launchable_mru_tick_count >= _MRU_RECOMPUTE_EVERY_TICKS
                and self._launchable_mru_recompute_idle()
            ):
                self._launchable_mru_tick_count = 0
                self.request_launchable_mru_refresh(reason="recompute", force=True)
        except Exception:  # noqa: BLE001 - ticks never break the pump.
            log.debug("Launchable MRU tick skipped", exc_info=True)

    def _launchable_mru_recompute_idle(self: Any) -> bool:
        """Return whether a forced recompute may run now."""
        try:
            if callable(getattr(self, "_prompt_input_active", None)):
                if self._prompt_input_active():
                    return False
        except Exception:  # noqa: BLE001 - degrade to idle.
            pass
        try:
            gate = getattr(self, "_nav_gate", None)
            if gate is not None and gate.is_navigating():
                return False
        except Exception:  # noqa: BLE001 - degrade to idle.
            pass
        return True
