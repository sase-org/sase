"""Exact artifact-delta scheduling for agent loading refreshes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from ..event_refresh._constants import AGENT_ARTIFACT_DELTA_QUEUE_LIMIT
from ._loading_state import AgentLoadingStateMixin
from ._refresh_trace import (
    normalize_refresh_source as _normalize_refresh_source,
    record_agents_refresh_trace,
)
from ...util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)


@dataclass
class _AgentArtifactDeltaRefreshRequest:
    """Bounded exact artifact-delta work retained across refresh contention."""

    source: str
    artifact_dirs: list[Path] = field(default_factory=list)
    deleted_artifact_dirs: list[Path] = field(default_factory=list)
    callbacks: list[Callable[[], None]] = field(default_factory=list)
    cancelled: bool = False


class AgentArtifactDeltaRefreshMixin(AgentLoadingStateMixin):
    """Methods that schedule and run exact agent artifact reconciles."""

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
        self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
            source=request.source
        )

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
            pending_revalidate_index = getattr(
                self, "_agents_refresh_pending_revalidate_index", False
            )
            pending_prefix_completion = getattr(
                self, "_agents_refresh_pending_prefix_completion", False
            )
            pending_source = _normalize_refresh_source(
                getattr(self, "_agents_refresh_pending_source", "unknown")
            )
            self._agents_refresh_pending_source = "unknown"
            self._agents_refresh_pending_full_history = False
            self._agents_refresh_pending_full_history_reason = None
            self._agents_refresh_pending_revalidate_index = False
            self._agents_refresh_pending_prefix_completion = False
            self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
                source=pending_source,
                full_history=pending_full_history,
                full_history_reason=pending_full_history_reason,
                revalidate_index=pending_revalidate_index,
                complete_prefix=pending_prefix_completion,
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
