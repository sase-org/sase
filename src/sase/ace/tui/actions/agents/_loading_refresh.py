"""Refresh coalescing and async scheduling for agent loading."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from inspect import Parameter, signature
from pathlib import Path
from typing import Any

from ..event_refresh._constants import AGENT_ARTIFACT_DELTA_QUEUE_LIMIT
from ...util.trace import trace_event, tui_trace
from ...util.pump_tasks import spawn_pump_free_task
from ._loading_state import AgentLoadingStateMixin
from ._refresh_trace import (
    classify_agents_data_cost,
    infer_broad_load_fallback_reason,
    normalize_refresh_source as _normalize_refresh_source,
    record_agents_refresh_trace,
)

log = logging.getLogger(__name__)

_StartingPollSignature = tuple[int, int] | None
_StartingPollMarkerState = tuple[_StartingPollSignature, _StartingPollSignature]

# Seconds of input quiet required before the deferred Tier 2
# full-history reconcile is scheduled in the background. Picked to land
# well outside any j/k burst while still completing before the user
# would typically reach for historic data.
TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S = 30.0


@dataclass
class _AgentArtifactDeltaRefreshRequest:
    """Bounded exact artifact-delta work retained across refresh contention."""

    source: str
    artifact_dirs: list[Path] = field(default_factory=list)
    deleted_artifact_dirs: list[Path] = field(default_factory=list)
    callbacks: list[Callable[[], None]] = field(default_factory=list)
    cancelled: bool = False


def _marker_signature(path: Path) -> _StartingPollSignature:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _callable_accepts_kwarg(callback: Callable[..., object], name: str) -> bool:
    try:
        params = signature(callback).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind == Parameter.VAR_KEYWORD or p.name == name for p in params)


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

    def _make_agent_artifact_delta_request(
        self,
        artifact_dirs: list[Path],
        *,
        source: str,
        on_complete: Callable[[], None] | None = None,
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> tuple[_AgentArtifactDeltaRefreshRequest | None, str | None]:
        """Normalize and bound one exact artifact-delta request."""
        unique_dirs: list[Path] = []
        seen: set[str] = set()
        for artifact_dir in artifact_dirs:
            path = Path(artifact_dir).expanduser()
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            unique_dirs.append(path)
        if not unique_dirs:
            return None, "missing_artifact_dir"
        if len(unique_dirs) > AGENT_ARTIFACT_DELTA_QUEUE_LIMIT:
            return None, "dirty_queue_overflow"

        deleted_keys = {
            str(Path(artifact_dir).expanduser())
            for artifact_dir in (deleted_artifact_dirs or [])
        }
        unique_deleted_dirs = [
            path for path in unique_dirs if str(path) in deleted_keys
        ]
        callbacks = [on_complete] if on_complete is not None else []
        return (
            _AgentArtifactDeltaRefreshRequest(
                source=_normalize_refresh_source(source),
                artifact_dirs=unique_dirs,
                deleted_artifact_dirs=unique_deleted_dirs,
                callbacks=callbacks,
            ),
            None,
        )

    def _record_agent_artifact_delta_request(
        self,
        request: _AgentArtifactDeltaRefreshRequest,
        *,
        stage: str,
    ) -> None:
        record_agents_refresh_trace(
            self,
            stage=stage,
            source=request.source,
            data_cost="artifact_delta_load",
            full_history=False,
            artifact_dirs=len(request.artifact_dirs),
            deleted_artifact_dirs=len(request.deleted_artifact_dirs),
        )

    def _append_agents_refresh_callbacks(
        self,
        callbacks: list[Callable[[], None]],
    ) -> None:
        if callbacks:
            self._agents_refresh_pending_callbacks.extend(callbacks)

    def _schedule_broad_fallback_for_agent_delta(
        self,
        request: _AgentArtifactDeltaRefreshRequest,
        *,
        reason: str,
        record_fallback: bool = True,
    ) -> None:
        if record_fallback:
            record_agents_refresh_trace(
                self,
                stage="fallback",
                source=request.source,
                data_cost="tier1_broad_load",
                fallback_reason=reason,
            )
        callbacks = list(request.callbacks)
        request.callbacks.clear()
        self._append_agents_refresh_callbacks(callbacks)
        self._schedule_agents_async_refresh(source=request.source)

    def _overflow_agent_artifact_delta_to_broad(
        self,
        *,
        source: str,
        requests: list[_AgentArtifactDeltaRefreshRequest],
    ) -> None:
        callbacks: list[Callable[[], None]] = []
        for request in requests:
            request.cancelled = True
            callbacks.extend(request.callbacks)
            request.callbacks.clear()
        broad_request = _AgentArtifactDeltaRefreshRequest(
            source=_normalize_refresh_source(source),
            callbacks=callbacks,
        )
        self._schedule_broad_fallback_for_agent_delta(
            broad_request,
            reason="dirty_queue_overflow",
        )

    def _merge_agent_artifact_delta_request(
        self,
        target: _AgentArtifactDeltaRefreshRequest,
        incoming: _AgentArtifactDeltaRefreshRequest,
    ) -> bool:
        seen = {str(path): path for path in target.artifact_dirs}
        new_dirs: list[Path] = []
        for path in incoming.artifact_dirs:
            key = str(path)
            if key not in seen:
                new_dirs.append(path)
                seen[key] = path
        if len(target.artifact_dirs) + len(new_dirs) > AGENT_ARTIFACT_DELTA_QUEUE_LIMIT:
            return False

        target.artifact_dirs.extend(new_dirs)
        deleted_seen = {str(path) for path in target.deleted_artifact_dirs}
        for path in incoming.deleted_artifact_dirs:
            key = str(path)
            if key not in deleted_seen:
                target.deleted_artifact_dirs.append(path)
                deleted_seen.add(key)
        target.callbacks.extend(incoming.callbacks)
        incoming.callbacks.clear()
        target.source = incoming.source
        return True

    def _queue_pending_agent_artifact_delta_request(
        self,
        request: _AgentArtifactDeltaRefreshRequest,
    ) -> None:
        pending = getattr(self, "_agents_artifact_delta_pending", None)
        if pending is None:
            self._agents_artifact_delta_pending = request
            self._record_agent_artifact_delta_request(request, stage="coalesced")
            return
        if self._merge_agent_artifact_delta_request(pending, request):
            self._record_agent_artifact_delta_request(pending, stage="coalesced")
            return
        self._agents_artifact_delta_pending = None
        self._overflow_agent_artifact_delta_to_broad(
            source=request.source,
            requests=[pending, request],
        )

    def _schedule_agent_artifact_delta_request(
        self,
        request: _AgentArtifactDeltaRefreshRequest,
    ) -> None:
        if request.cancelled:
            return
        self._agents_artifact_delta_scheduled = request
        self._record_agent_artifact_delta_request(request, stage="scheduled")
        self._spawn_agent_artifact_delta_refresh_task(request)

    def _drain_pending_agents_refresh_work(self) -> None:
        if self._agents_loading or self._agents_refresh_scheduled:
            return
        if getattr(self, "_agents_artifact_delta_scheduled", None) is not None:
            return

        if self._agents_refresh_pending:
            self._agents_refresh_pending = False
            pending_full_history = getattr(
                self, "_agents_refresh_pending_full_history", False
            )
            pending_full_history_reason = getattr(
                self, "_agents_refresh_pending_full_history_reason", None
            )
            pending_source = _normalize_refresh_source(
                getattr(self, "_agents_refresh_pending_source", "unknown")
            )
            self._agents_refresh_pending_source = "unknown"
            self._agents_refresh_pending_full_history = False
            self._agents_refresh_pending_full_history_reason = None
            self._schedule_agents_async_refresh(
                source=pending_source,
                full_history=pending_full_history,
                full_history_reason=pending_full_history_reason,
            )
            return

        pending_delta = getattr(self, "_agents_artifact_delta_pending", None)
        if pending_delta is None:
            return
        self._agents_artifact_delta_pending = None
        if pending_delta.cancelled:
            return
        self._record_agent_artifact_delta_request(pending_delta, stage="draining")
        self._schedule_agent_artifact_delta_request(pending_delta)

    def _schedule_agents_async_refresh(
        self,
        *,
        source: str = "unknown",
        full_history: bool = False,
        full_history_reason: str | None = None,
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
            return
        self._agents_refresh_scheduled = True
        self._agents_refresh_scheduled_source = source
        self._agents_refresh_scheduled_full_history = full_history
        self._agents_refresh_scheduled_full_history_reason = (
            full_history_reason if full_history else None
        )
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

    def _schedule_agent_artifact_delta_refresh(
        self,
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        on_complete: Callable[[], None] | None = None,
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> None:
        """Schedule an exact artifact-dir reconcile for a bounded row delta."""
        source = _normalize_refresh_source(source)
        request, fallback_reason = self._make_agent_artifact_delta_request(
            artifact_dirs,
            source=source,
            on_complete=on_complete,
            deleted_artifact_dirs=deleted_artifact_dirs,
        )
        if request is None:
            fallback_request = _AgentArtifactDeltaRefreshRequest(
                source=source,
                callbacks=[on_complete] if on_complete is not None else [],
            )
            self._schedule_broad_fallback_for_agent_delta(
                fallback_request,
                reason=fallback_reason or "missing_artifact_dir",
            )
            return
        if getattr(self, "_agent_search_query", ""):
            self._schedule_broad_fallback_for_agent_delta(
                request,
                reason="active_search",
            )
            return

        scheduled_delta = getattr(self, "_agents_artifact_delta_scheduled", None)
        if (
            scheduled_delta is not None
            and not self._agents_loading
            and not self._agents_refresh_scheduled
            and not self._agents_refresh_pending
        ):
            if self._merge_agent_artifact_delta_request(scheduled_delta, request):
                self._record_agent_artifact_delta_request(
                    scheduled_delta,
                    stage="coalesced",
                )
                return
            self._agents_artifact_delta_scheduled = None
            self._overflow_agent_artifact_delta_to_broad(
                source=request.source,
                requests=[scheduled_delta, request],
            )
            return

        if (
            self._agents_loading
            or self._agents_refresh_scheduled
            or self._agents_refresh_pending
            or scheduled_delta is not None
        ):
            self._queue_pending_agent_artifact_delta_request(request)
            return

        self._schedule_agent_artifact_delta_request(request)

    def _spawn_agent_artifact_delta_refresh_task(
        self,
        request: _AgentArtifactDeltaRefreshRequest,
    ) -> None:
        """Run an artifact delta without occupying Textual's message pump."""
        task = spawn_pump_free_task(
            self,
            self._run_agent_artifact_delta_refresh(request),
            name="sase-agents-artifact-delta-refresh",
            registry_attr="_pump_free_async_tasks",
        )
        if (
            task is None
            and getattr(self, "_agents_artifact_delta_scheduled", None) is request
        ):
            self._agents_artifact_delta_scheduled = None

    async def _run_agent_artifact_delta_refresh(
        self,
        request_or_dirs: _AgentArtifactDeltaRefreshRequest | tuple[Path, ...],
        source: str = "unknown",
        on_complete: Callable[[], None] | None = None,
        deleted_artifact_dirs: tuple[Path, ...] = (),
    ) -> None:
        """Run an exact artifact-dir reconcile with broad fallback on failure."""
        if isinstance(request_or_dirs, _AgentArtifactDeltaRefreshRequest):
            request = request_or_dirs
        else:
            maybe_request, fallback_reason = self._make_agent_artifact_delta_request(
                list(request_or_dirs),
                source=source,
                on_complete=on_complete,
                deleted_artifact_dirs=list(deleted_artifact_dirs),
            )
            if maybe_request is None:
                fallback_request = _AgentArtifactDeltaRefreshRequest(
                    source=_normalize_refresh_source(source),
                    callbacks=[on_complete] if on_complete is not None else [],
                )
                self._schedule_broad_fallback_for_agent_delta(
                    fallback_request,
                    reason=fallback_reason or "missing_artifact_dir",
                )
                return
            request = maybe_request

        if request.cancelled:
            if getattr(self, "_agents_artifact_delta_scheduled", None) is request:
                self._agents_artifact_delta_scheduled = None
            self._drain_pending_agents_refresh_work()
            return

        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(  # type: ignore[attr-defined]
                delay,
                partial(self._spawn_agent_artifact_delta_refresh_task, request),
            )
            return

        if getattr(self, "_agents_artifact_delta_scheduled", None) is request:
            self._agents_artifact_delta_scheduled = None
        source = _normalize_refresh_source(request.source)
        if self._agents_loading:
            self._queue_pending_agent_artifact_delta_request(request)
            return

        self._agents_loading = True
        self._agents_refresh_active_source = source
        callbacks_for_broad: list[Callable[[], None]] = []
        needs_broad_fallback = False
        fallback_already_recorded = False
        try:
            ok = await self._load_agent_artifact_delta_async(  # type: ignore[attr-defined]
                list(request.artifact_dirs),
                source=source,
                deleted_artifact_dirs=list(request.deleted_artifact_dirs),
            )
            if not ok:
                needs_broad_fallback = True
                fallback_already_recorded = True
                callbacks_for_broad = list(request.callbacks)
                request.callbacks.clear()
            else:
                for callback in list(request.callbacks):
                    try:
                        callback()
                    except Exception:
                        log.exception("agents artifact delta callback failed")
                request.callbacks.clear()
        except Exception:
            log.exception("Agents artifact delta refresh failed")
            record_agents_refresh_trace(
                self,
                stage="fallback",
                source=source,
                data_cost="tier1_broad_load",
                fallback_reason="delta_read_failure",
            )
            needs_broad_fallback = True
            fallback_already_recorded = True
            callbacks_for_broad = list(request.callbacks)
            request.callbacks.clear()
        finally:
            self._agents_loading = False
            self._agents_refresh_active_source = "unknown"

        if needs_broad_fallback:
            fallback_request = _AgentArtifactDeltaRefreshRequest(
                source=source,
                callbacks=callbacks_for_broad,
            )
            if self._agents_refresh_pending:
                if not fallback_already_recorded:
                    record_agents_refresh_trace(
                        self,
                        stage="fallback",
                        source=source,
                        data_cost="tier1_broad_load",
                        fallback_reason="delta_read_failure",
                    )
                self._append_agents_refresh_callbacks(fallback_request.callbacks)
                fallback_request.callbacks.clear()
            else:
                self._schedule_broad_fallback_for_agent_delta(
                    fallback_request,
                    reason="delta_read_failure",
                    record_fallback=not fallback_already_recorded,
                )
        self._drain_pending_agents_refresh_work()

    def _maybe_trigger_input_quiet_tier2_reconcile(
        self, *, now_mono: float | None = None
    ) -> bool:
        """Schedule the deferred Tier 2 reconcile once input has been quiet.

        Returns True iff a refresh was scheduled. The reconcile is the
        single largest startup span (~2.7 s) and is deferred until input
        has been quiet for ``TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S``; the
        quiet window is measured from the later of the last recorded
        input and the moment the pending flag was armed, so users
        who never touch input still get the reconcile in the
        background.
        """
        if not getattr(self, "_agents_history_reconcile_pending", False):
            return False
        if self._agents_loading or self._agents_refresh_scheduled:
            return False
        cur = time.monotonic() if now_mono is None else now_mono
        last_input = getattr(self, "_last_input_mono", 0.0)
        armed_at = getattr(self, "_agents_history_reconcile_armed_mono", 0.0)
        reference = max(last_input, armed_at)
        if reference <= 0.0:
            return False
        if cur - reference < TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S:
            return False
        self._agents_history_reconcile_pending = False
        self._schedule_agents_async_refresh(
            source="input_quiet_tier2_reconcile",
            full_history=True,
            full_history_reason="input_quiet_tier2_reconcile",
        )
        return True

    def _poll_starting_agent_transitions(self) -> None:
        """Nudge a refresh when a STARTING agent's markers land on disk.

        The inotify watcher is the intended fast path for the
        STARTING→RUNNING/WAITING transition, but it races the creation of
        the per-agent ``artifacts/<workflow>/<timestamp>/`` subtree and is
        unavailable on some platforms. This poll runs once per countdown
        tick (cheap; one ``stat`` per marker per STARTING agent) and
        bounds the worst-case visible time-to-row to ~1 s in that window.

        No-op when no STARTING agent is present, which is the steady
        state. The cache is keyed by ``agent.identity`` and shrinks back
        to empty once all STARTING agents have transitioned.
        """
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        starting_indices = panel_index.hidden_starting_indices
        cache = self._starting_poll_meta_cache
        if not starting_indices:
            if cache:
                cache.clear()
            return

        live_identities: set[tuple] = set()  # type: ignore[type-arg]
        dirty_artifact_dirs: list[Path] = []
        for i in starting_indices:
            agent = self._agents[i]
            identity = agent.identity
            live_identities.add(identity)
            artifacts_dir = agent.get_artifacts_dir()
            if not artifacts_dir:
                continue
            artifacts_path = Path(artifacts_dir)
            meta_path = artifacts_path / "agent_meta.json"
            waiting_path = artifacts_path / "waiting.json"
            try:
                current: _StartingPollMarkerState = (
                    _marker_signature(meta_path),
                    _marker_signature(waiting_path),
                )
            except OSError:
                continue
            had_entry = identity in cache
            previous = cache[identity] if had_entry else None
            cache[identity] = current
            if not had_entry:
                # First observation — record the baseline; only nudge if
                # either marker already exists, since that means the
                # watcher likely missed the CREATE event and the agent has
                # already written a loader-visible marker.
                if current != (None, None):
                    dirty_artifact_dirs.append(artifacts_path)
                continue
            if previous is not None and current != previous:
                # Marker appearance, removal, or update — watcher likely
                # missed a loader-visible event.
                dirty_artifact_dirs.append(artifacts_path)

        # Eviction: drop identities no longer STARTING.
        stale = [identity for identity in cache if identity not in live_identities]
        for identity in stale:
            cache.pop(identity, None)

        if dirty_artifact_dirs:
            self._schedule_agent_artifact_delta_refresh(
                dirty_artifact_dirs,
                source="starting_poll",
            )

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
        source = _normalize_refresh_source(
            getattr(self, "_agents_refresh_scheduled_source", "unknown")
        )
        self._agents_refresh_scheduled = False
        self._agents_refresh_scheduled_source = "unknown"
        self._agents_refresh_scheduled_full_history = False
        self._agents_refresh_scheduled_full_history_reason = None
        if self._agents_loading:
            self._agents_refresh_pending = True
            self._agents_refresh_pending_source = source
            if full_history:
                self._agents_refresh_pending_full_history = True
                self._agents_refresh_pending_full_history_reason = (
                    full_history_reason or "coalesced_full_history_refresh"
                )
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
