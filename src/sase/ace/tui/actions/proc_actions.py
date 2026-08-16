"""Mixin providing read-only durable proc observation for the TUI app."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.core.time import local_now
from sase.procs import ProcSubmitError
from sase.project_display_names import humanize_cl_name, humanize_cl_names_in_text

from ..proc_observer import (
    ObservedProc,
    ProcCompletionRecord,
    ProcObserver,
    ProcObserverSnapshot,
    ProcProjection,
    compose_proc_projection,
)
from ..widgets.proc_indicator import ProcIndicator

if TYPE_CHECKING:
    from ...patch import Patch
    from ..durable_submit import DurableSubmitHandle

log = logging.getLogger(__name__)

PROC_RECONCILE_STARTUP_DELAY_SECONDS = 1.0
PROC_RECONCILE_INTERVAL_SECONDS = 30.0


@dataclass(frozen=True)
class TrackedProcResult[T]:
    """Result returned by durable result decoding or session-local work."""

    success: bool
    message: str
    payload: T | None = None
    error: str | None = None
    collision: bool = False


@dataclass(frozen=True)
class TrackedProcCompletion[T]:
    """UI-thread completion record for a background operation."""

    proc_info: ObservedProc
    success: bool
    message: str
    output: str
    payload: T | None = None
    error: str | None = None
    collision: bool = False


@dataclass(frozen=True)
class _SessionWorkerResult[T]:
    proc_id: str
    result: TrackedProcResult[T]
    output: str


@dataclass(frozen=True)
class _DurableSubmitWorkerResult:
    placeholder_id: str
    handle: DurableSubmitHandle | None = None
    result: TrackedProcResult[Any] | None = None


@dataclass(frozen=True)
class _ProcCallbackConfig:
    on_complete: Callable[[TrackedProcCompletion[Any]], None] | None
    reload_on_complete: bool
    notify_on_complete: bool
    on_settled: Callable[[], None] | None = None
    workspace_claim: Mapping[str, Any] | None = None


class ProcActionsMixin:
    """Mixin providing durable proc submission and read-only observation."""

    patches: list[Patch]
    current_idx: int

    def _init_proc_observer(self) -> None:
        """Initialize observer projection, short submit workers, and callbacks."""
        self._proc_projection = ProcProjection()
        self._durable_submit_workers: dict[str, Worker[Any]] = {}
        self._session_workers: dict[str, Worker[Any]] = {}
        self._session_completion_callbacks: dict[str, Any] = {}
        self._proc_completion_callbacks: dict[str, _ProcCallbackConfig] = {}
        self._proc_pending_scopes: dict[str, frozenset[str]] = {}
        self._proc_session_id = _resolve_current_session_id()
        self._proc_reconciler_worker: Worker[Any] | None = None
        self._proc_reconciler_start_timer = None
        self._proc_reconciler_interval_timer = None
        self._proc_observer = ProcObserver(
            on_snapshot=self._on_proc_observer_thread_snapshot,
        )
        self._proc_observer.start()

    def _stop_proc_observer(self) -> None:
        """Retire the observer thread without touching proc lifetimes."""
        self._stop_proc_reconciler()
        observer = getattr(self, "_proc_observer", None)
        if observer is not None:
            observer.stop(timeout=1.0)

    def _start_proc_reconciler(self) -> None:
        """Start slow best-effort orphaned-proc reconciliation workers."""
        set_timer = getattr(self, "set_timer", None)
        set_interval = getattr(self, "set_interval", None)
        if callable(set_timer):
            self._proc_reconciler_start_timer = set_timer(
                PROC_RECONCILE_STARTUP_DELAY_SECONDS,
                self._run_proc_reconciler,
                name="proc-reconciler-start",
            )
        if callable(set_interval):
            self._proc_reconciler_interval_timer = set_interval(
                PROC_RECONCILE_INTERVAL_SECONDS,
                self._run_proc_reconciler,
                name="proc-reconciler",
            )

    def _stop_proc_reconciler(self) -> None:
        """Stop ACE-side proc reconciliation timers and worker."""
        for attr in (
            "_proc_reconciler_start_timer",
            "_proc_reconciler_interval_timer",
        ):
            timer = getattr(self, attr, None)
            setattr(self, attr, None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass
        worker = getattr(self, "_proc_reconciler_worker", None)
        self._proc_reconciler_worker = None
        if worker is not None and getattr(worker, "is_running", False):
            try:
                worker.cancel()
            except Exception:
                pass

    def _run_proc_reconciler(self) -> None:
        """Run one orphaned-proc reconciliation pass in a thread worker."""
        worker = getattr(self, "_proc_reconciler_worker", None)
        if worker is not None and getattr(worker, "is_running", False):
            return
        from ..proc_reconciler import reconcile_running_procs_safely

        self._proc_reconciler_worker = self.run_worker(  # type: ignore[attr-defined]
            reconcile_running_procs_safely,
            thread=True,
            name="proc-reconciler",
            group="procs",
        )

    def _update_proc_indicator(self) -> None:
        """Update the top-bar proc indicator from the effective projection."""
        try:
            indicator = self.query_one("#proc-indicator", ProcIndicator)  # type: ignore[attr-defined]
            indicator.set_count(self._effective_proc_projection().active_count)
        except Exception:
            pass

    def _session_overlay_rows(self) -> tuple[ObservedProc, ...]:
        """Return ObservedProc rows for currently running session workers."""
        rows: list[ObservedProc] = []
        for recorded in getattr(self, "_session_completion_callbacks", {}).values():
            if not isinstance(recorded, tuple) or len(recorded) != 2:
                continue
            _on_complete, proc_info = recorded
            if isinstance(proc_info, ObservedProc):
                rows.append(proc_info)
        return tuple(rows)

    def _effective_proc_projection(self) -> ProcProjection:
        """Compose durable observer rows with live session-local workers."""
        durable = getattr(self, "_proc_projection", ProcProjection())
        if not isinstance(durable, ProcProjection):
            durable = ProcProjection()
        return compose_proc_projection(durable, self._session_overlay_rows())

    def _submit_durable_proc(
        self,
        argv: Sequence[str],
        *,
        operation: str,
        request: Any,
        result_path: str | Path | None = None,
        request_fingerprint: str,
        concurrency_keys: Sequence[str] = (),
        label: str | None = None,
        display_name: str | None = None,
        proc_type: str | None = None,
        cl_name: str = "",
        project_file: str = "",
        cwd: str | Path | None = None,
        workspace_claim: Mapping[str, Any] | None = None,
        duplicate_message: str | None = None,
        on_complete: Callable[[TrackedProcCompletion[Any]], None] | None = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
        on_settled: Callable[[], None] | None = None,
    ) -> ObservedProc | None:
        """Submit argv to the proc supervisor; completion comes from observation."""
        from ..durable_ops import (
            is_concurrency_collision,
            project_identity,
            release_workspace_claim,
        )
        from ..durable_submit import (
            coerce_operation_request,
            reject_callable_submission,
            submit_durable_proc_request,
        )
        from sase.ops import DurableSubmitError

        try:
            reject_callable_submission(argv, request)
            typed_request = coerce_operation_request(operation, request)
        except DurableSubmitError as exc:
            self.notify(str(exc), severity="error")  # type: ignore[attr-defined]
            return None

        if not hasattr(self, "_proc_observer"):
            self._init_proc_observer()

        requested_scopes = frozenset(concurrency_keys)
        projection = self._effective_proc_projection()
        existing = projection.scope_conflict(requested_scopes)
        if existing is None and requested_scopes:
            for pending_scopes in getattr(self, "_proc_pending_scopes", {}).values():
                if pending_scopes & requested_scopes:
                    existing = ObservedProc(
                        proc_id="pending",
                        proc_type=proc_type or operation,
                        cl_name=cl_name,
                        project_file=project_file,
                        status="pending",
                        message="pending",
                        started_at=(
                            projection.rows[0].started_at
                            if projection.rows
                            else local_now()
                        ),
                        display_name=display_name or label or operation,
                    )
                    break
        if existing is None:
            existing = self._session_worker_conflict(
                dedup_key=None,
                exclusive_scopes=requested_scopes,
            )
        if existing is not None:
            self.notify(  # type: ignore[attr-defined]
                duplicate_message
                or (
                    f"A {existing.proc_type} proc is already running for "
                    f"{humanize_cl_name(cl_name or existing.cl_name)}"
                ),
                severity="warning",
            )
            return None

        work_cwd = str(cwd or os.getcwd())
        submit_label = label or display_name or operation
        queue_type = proc_type or operation
        observer: ProcObserver = self._proc_observer
        presentation = observer.register_pending(
            proc_type=queue_type,
            cl_name=cl_name,
            project_file=project_file,
            display_name=display_name or submit_label,
            exclusive_scopes=requested_scopes,
            command=argv,
        )
        placeholder_id = presentation.proc_id
        self._proc_pending_scopes[placeholder_id] = requested_scopes
        self._proc_completion_callbacks[placeholder_id] = _ProcCallbackConfig(
            on_complete=on_complete,
            reload_on_complete=reload_on_complete,
            notify_on_complete=notify_on_complete,
            on_settled=on_settled,
            workspace_claim=workspace_claim,
        )

        def _submit() -> _DurableSubmitWorkerResult:
            try:
                handle = submit_durable_proc_request(
                    argv=argv,
                    operation=operation,
                    request=typed_request,
                    cwd=work_cwd,
                    label=submit_label,
                    result_path=result_path,
                    request_fingerprint=request_fingerprint,
                    concurrency_keys=concurrency_keys,
                    origin="ace",
                    project=project_identity(project_file) if project_file else None,
                    cl_name=cl_name or None,
                    session_id=getattr(self, "_proc_session_id", None),
                    workspace_claim=workspace_claim,
                )
                return _DurableSubmitWorkerResult(
                    placeholder_id=placeholder_id,
                    handle=handle,
                )
            except ProcSubmitError as exc:
                if is_concurrency_collision(exc):
                    release_workspace_claim(workspace_claim)
                    return _DurableSubmitWorkerResult(
                        placeholder_id=placeholder_id,
                        result=TrackedProcResult(
                            success=False,
                            message=str(exc),
                            error=str(exc),
                            collision=True,
                        ),
                    )
                log.exception("Durable proc %s failed to submit", operation)
                release_workspace_claim(workspace_claim)
                return _DurableSubmitWorkerResult(
                    placeholder_id=placeholder_id,
                    result=TrackedProcResult(
                        success=False,
                        message=str(exc),
                        error=str(exc),
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - submit worker must report.
                log.exception("Durable proc %s failed to submit", operation)
                release_workspace_claim(workspace_claim)
                return _DurableSubmitWorkerResult(
                    placeholder_id=placeholder_id,
                    result=TrackedProcResult(
                        success=False,
                        message=str(exc),
                        error=str(exc),
                    ),
                )

        worker: Worker[Any] = self.run_worker(_submit, thread=True)  # type: ignore[attr-defined]
        self._durable_submit_workers[placeholder_id] = worker
        self._update_proc_indicator()
        return presentation

    def _submit_session_worker[T](
        self,
        proc_type: str,
        body: Callable[[], TrackedProcResult[T]],
        *,
        on_complete: Callable[[TrackedProcCompletion[T]], None] | None = None,
        display_name: str | None = None,
        cl_name: str = "",
        project_file: str = "",
        dedup_key: str | None = None,
        exclusive_scopes: Collection[str] = (),
        duplicate_message: str | None = None,
    ) -> ObservedProc | None:
        """Run true UI-session-local work in a thread-backed worker."""
        from sase.core.time import local_now

        if not hasattr(self, "_session_workers"):
            self._session_workers = {}
        if not hasattr(self, "_session_completion_callbacks"):
            self._session_completion_callbacks = {}

        requested_scopes = frozenset(exclusive_scopes)
        existing = self._session_worker_conflict(
            dedup_key=dedup_key,
            exclusive_scopes=requested_scopes,
        )
        if existing is None:
            existing = self._effective_proc_projection().scope_conflict(
                requested_scopes
            )
        if existing is None and requested_scopes:
            for pending_scopes in getattr(self, "_proc_pending_scopes", {}).values():
                if pending_scopes & requested_scopes:
                    existing = ObservedProc(
                        proc_id="pending",
                        proc_type=proc_type,
                        cl_name=cl_name,
                        project_file=project_file,
                        status="pending",
                        message="pending",
                        started_at=local_now(),
                        display_name=display_name or proc_type,
                    )
                    break
        if existing is not None:
            self.notify(  # type: ignore[attr-defined]
                duplicate_message
                or (
                    f"A {existing.proc_type} proc is already running for "
                    f"{humanize_cl_name(cl_name or existing.cl_name)}"
                ),
                severity="warning",
            )
            return None

        durable = getattr(self, "_proc_projection", ProcProjection())
        if not isinstance(durable, ProcProjection):
            durable = ProcProjection()
        proc_info = ObservedProc(
            proc_id=f"session-{len(self._session_workers)}-{os.getpid()}",
            proc_type=proc_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=local_now(),
            display_name=display_name or proc_type,
            dedup_key=dedup_key,
            exclusive_scopes=requested_scopes,
            session_id=durable.session_id,
            session_live=True,
        )

        def _wrapped() -> _SessionWorkerResult[T]:
            try:
                result = body()
            except Exception as exc:
                log.exception("Session worker %s failed", proc_type)
                result = TrackedProcResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                )
            return _SessionWorkerResult(proc_info.proc_id, result, "")

        self._session_completion_callbacks[proc_info.proc_id] = (
            on_complete,
            proc_info,
        )
        worker: Worker[Any] = self.run_worker(_wrapped, thread=True)  # type: ignore[attr-defined]
        self._session_workers[proc_info.proc_id] = worker
        self._update_proc_indicator()
        return proc_info

    def _session_worker_conflict(
        self,
        *,
        dedup_key: str | None,
        exclusive_scopes: Collection[str],
    ) -> ObservedProc | None:
        """Return a live session worker claiming the requested key or scope."""
        requested_scopes = frozenset(exclusive_scopes)
        if dedup_key is None and not requested_scopes:
            return None
        for recorded in getattr(self, "_session_completion_callbacks", {}).values():
            if not isinstance(recorded, tuple) or len(recorded) != 2:
                continue
            _on_complete, proc_info = recorded
            if not isinstance(proc_info, ObservedProc):
                continue
            if dedup_key is not None and proc_info.dedup_key == dedup_key:
                return proc_info
            if requested_scopes and requested_scopes & proc_info.exclusive_scopes:
                return proc_info
        return None

    def _on_durable_submit_worker_completed(self, worker: Worker[Any]) -> None:
        """Register successful submit handles or surface submit failures."""
        result = worker.result
        if not isinstance(result, _DurableSubmitWorkerResult):
            return
        placeholder_id = result.placeholder_id
        self._durable_submit_workers.pop(placeholder_id, None)
        self._proc_pending_scopes.pop(placeholder_id, None)
        observer = getattr(self, "_proc_observer", None)
        config = self._proc_completion_callbacks.get(placeholder_id)
        if result.handle is not None:
            if config is not None:
                self._proc_completion_callbacks[result.handle.proc_id] = config
                self._proc_completion_callbacks.pop(placeholder_id, None)
            if observer is not None:
                observer.register_submitted(
                    placeholder_id=placeholder_id,
                    proc_id=result.handle.proc_id,
                    operation=result.handle.operation,
                    result_path=result.handle.result_path,
                )
            return

        proc_result = result.result or TrackedProcResult(
            success=False,
            message="durable submit failed",
            error="durable submit failed",
        )
        proc_info = self._placeholder_proc(placeholder_id)
        if observer is not None:
            observer.remove_pending(placeholder_id)
        self._proc_completion_callbacks.pop(placeholder_id, None)
        self._deliver_tracked_completion(
            proc_id=placeholder_id,
            proc_info=proc_info,
            result=proc_result,
            output=proc_info.get_live_output(),
            config=config,
        )
        self._update_proc_indicator()

    def _on_durable_submit_worker_error(self, worker: Worker[Any]) -> None:
        """Handle a submit worker that raised before returning a typed result."""
        placeholder_id = next(
            (
                key
                for key, item in getattr(self, "_durable_submit_workers", {}).items()
                if item is worker
            ),
            None,
        )
        if placeholder_id is None:
            return
        self._durable_submit_workers.pop(placeholder_id, None)
        self._proc_pending_scopes.pop(placeholder_id, None)
        observer = getattr(self, "_proc_observer", None)
        if observer is not None:
            observer.remove_pending(placeholder_id)
        error_msg = str(worker.error) if worker.error else "Unknown submit error"
        config = self._proc_completion_callbacks.pop(placeholder_id, None)
        if config is not None:
            from ..durable_ops import release_workspace_claim

            release_workspace_claim(config.workspace_claim)
        proc_info = self._placeholder_proc(placeholder_id)
        self._deliver_tracked_completion(
            proc_id=placeholder_id,
            proc_info=proc_info,
            result=TrackedProcResult(
                success=False,
                message=error_msg,
                error=error_msg,
            ),
            output="",
            config=config,
        )
        self._update_proc_indicator()

    def _on_proc_observer_thread_snapshot(
        self,
        snapshot: ProcObserverSnapshot,
    ) -> None:
        """Receive an immutable snapshot from the observer thread."""
        try:
            self.call_from_thread(self._apply_proc_observer_snapshot, snapshot)  # type: ignore[attr-defined]
        except Exception:
            log.debug("proc observer snapshot delivery failed", exc_info=True)

    def _apply_proc_observer_snapshot(self, snapshot: ProcObserverSnapshot) -> None:
        """Apply observer projection and deliver decoded completions once."""
        self._proc_projection = snapshot.projection
        self._update_proc_indicator()
        for completion in snapshot.completions:
            self._deliver_observed_completion(completion, snapshot.projection)

    def _deliver_observed_completion(
        self,
        completion: ProcCompletionRecord,
        projection: ProcProjection,
    ) -> None:
        config = self._proc_completion_callbacks.pop(completion.proc_id, None)
        if config is None:
            return
        row = next(
            (
                item
                for item in projection.rows
                if item.proc_id == completion.proc_id
                or item.durable_proc_id == completion.proc_id
            ),
            None,
        ) or self._placeholder_proc(completion.proc_id)
        result: TrackedProcResult[Any]
        if completion.result is None:
            message = completion.error or "durable proc did not write a typed result"
            result = TrackedProcResult(
                success=False,
                message=message,
                error=message,
            )
        else:
            decoded = completion.result
            result = TrackedProcResult(
                success=decoded.success,
                message=decoded.message,
                payload=None if decoded.payload is None else dict(decoded.payload),
                error=decoded.error,
            )
        self._deliver_tracked_completion(
            proc_id=completion.proc_id,
            proc_info=row,
            result=result,
            output=row.get_live_output(),
            config=config,
        )

    def _deliver_tracked_completion(
        self,
        *,
        proc_id: str,
        proc_info: ObservedProc,
        result: TrackedProcResult[Any],
        output: str,
        config: _ProcCallbackConfig | None,
    ) -> None:
        if config is None:
            config = _ProcCallbackConfig(
                on_complete=None,
                reload_on_complete=True,
                notify_on_complete=True,
            )
        try:
            if config.notify_on_complete:
                self._notify_tracked_proc_result(proc_info, result)
            if config.on_complete is not None:
                config.on_complete(
                    TrackedProcCompletion(
                        proc_info=proc_info,
                        success=result.success,
                        message=result.message,
                        output=output,
                        payload=result.payload,
                        error=result.error,
                        collision=result.collision,
                    )
                )
            if config.reload_on_complete:
                self._reload_and_reposition()  # type: ignore[attr-defined]
        finally:
            if config.on_settled is not None:
                try:
                    config.on_settled()
                except Exception:
                    log.exception("Background proc %s settle callback failed", proc_id)
            self._update_proc_indicator()

    def _notify_tracked_proc_result(
        self,
        proc_info: ObservedProc,
        result: TrackedProcResult[Any],
    ) -> None:
        display_message = humanize_cl_names_in_text(result.message)
        if result.collision:
            self.notify(  # type: ignore[attr-defined]
                (
                    f"A {proc_info.proc_type} proc is already running for "
                    f"{humanize_cl_name(proc_info.cl_name)}"
                ),
                severity="warning",
            )
        elif result.success:
            self.notify(display_message)  # type: ignore[attr-defined]
        else:
            self.notify(  # type: ignore[attr-defined]
                f"Proc failed: {display_message}",
                severity="error",
            )

    def _placeholder_proc(self, proc_id: str) -> ObservedProc:
        projection = self._effective_proc_projection()
        for row in projection.rows:
            if row.proc_id == proc_id or row.durable_proc_id == proc_id:
                return row
        from sase.core.time import local_now

        return ObservedProc(
            proc_id=proc_id,
            proc_type="proc",
            cl_name="",
            project_file="",
            status="error",
            message="proc failed",
            started_at=local_now(),
        )

    def _on_session_worker_completed(self, worker: Worker[Any]) -> None:
        """Deliver a session-local worker result on the UI thread."""
        result = worker.result
        if not isinstance(result, _SessionWorkerResult):
            return
        callbacks = getattr(self, "_session_completion_callbacks", {})
        recorded = callbacks.pop(result.proc_id, None)
        workers = getattr(self, "_session_workers", {})
        workers.pop(result.proc_id, None)
        self._update_proc_indicator()
        if recorded is None:
            return
        on_complete, proc_info = recorded
        if on_complete is None:
            return
        proc_result = result.result
        on_complete(
            TrackedProcCompletion(
                proc_info=proc_info,
                success=proc_result.success,
                message=proc_result.message,
                output=result.output,
                payload=proc_result.payload,
                error=proc_result.error,
                collision=proc_result.collision,
            )
        )

    def _on_session_worker_error(self, worker: Worker[Any]) -> None:
        """Deliver a session-local worker error on the UI thread."""
        workers = getattr(self, "_session_workers", {})
        proc_id = next((key for key, item in workers.items() if item is worker), None)
        if proc_id is None:
            return
        workers.pop(proc_id, None)
        callbacks = getattr(self, "_session_completion_callbacks", {})
        recorded = callbacks.pop(proc_id, None)
        self._update_proc_indicator()
        if recorded is None:
            return
        on_complete, proc_info = recorded
        if on_complete is None:
            return
        error_msg = str(worker.error) if worker.error else "Unknown error"
        on_complete(
            TrackedProcCompletion(
                proc_info=proc_info,
                success=False,
                message=error_msg,
                output="",
                error=error_msg,
            )
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Route worker state changes for proc submission and session workers."""
        if event.worker in getattr(self, "_durable_submit_workers", {}).values():
            if event.state == WorkerState.SUCCESS:
                self._on_durable_submit_worker_completed(event.worker)
            elif event.state == WorkerState.ERROR:
                self._on_durable_submit_worker_error(event.worker)
            return

        if event.worker in getattr(self, "_session_workers", {}).values():
            if event.state == WorkerState.SUCCESS:
                self._on_session_worker_completed(event.worker)
            elif event.state == WorkerState.ERROR:
                self._on_session_worker_error(event.worker)
            return

        axe_worker = getattr(self, "_axe_worker", None)
        if axe_worker is not None and event.worker is axe_worker:
            if event.state in (WorkerState.SUCCESS, WorkerState.ERROR):
                self._on_axe_worker_done(event.worker, event.state)  # type: ignore[attr-defined]

        if event.worker is getattr(self, "_proc_reconciler_worker", None):
            if event.state in (
                WorkerState.SUCCESS,
                WorkerState.ERROR,
                WorkerState.CANCELLED,
            ):
                self._proc_reconciler_worker = None
                observer = getattr(self, "_proc_observer", None)
                if observer is not None:
                    observer.request_poll()


def _resolve_current_session_id() -> str | None:
    """Return the current ACE session id if the registry is readable."""
    try:
        from sase.sessions import current_session_id

        return current_session_id()
    except Exception:
        return None
