"""Mixin providing background proc submission for the TUI app."""

from __future__ import annotations

import logging
import os
from inspect import Parameter, signature
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.procs import ProcSubmitError
from sase.project_display_names import humanize_cl_name, humanize_cl_names_in_text

from ..proc_mirror import ProcMirror
from ..proc_queue import ProcInfo, ProcQueue, redirect_print_to
from ..proc_subprocess import ProcReporter
from ..widgets.proc_indicator import ProcIndicator

if TYPE_CHECKING:
    from ...patch import Patch

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrackedProcResult[T]:
    """Result returned by a tracked background proc body."""

    success: bool
    message: str
    payload: T | None = None
    error: str | None = None


@dataclass(frozen=True)
class TrackedProcCompletion[T]:
    """UI-thread completion record for a tracked background proc."""

    proc_info: ProcInfo
    success: bool
    message: str
    output: str
    payload: T | None = None
    error: str | None = None


@dataclass(frozen=True)
class _ProcWorkerResult[T]:
    proc_id: str
    result: TrackedProcResult[T]
    output: str


@dataclass(frozen=True)
class _ProcCallbackConfig:
    on_complete: Callable[[TrackedProcCompletion[Any]], None] | None
    reload_on_complete: bool
    notify_on_complete: bool


class ProcActionsMixin:
    """Mixin providing background proc submission for the TUI app."""

    # Type hints for AceApp attributes used by this mixin
    patches: list[Patch]
    current_idx: int

    def _init_proc_queue(self) -> None:
        """Initialize the proc queue, worker tracking map, and durable mirror.

        Must be called during AceApp.__init__().
        """
        self._proc_queue = ProcQueue()
        self._proc_workers: dict[str, Worker[Any]] = {}
        self._proc_completion_callbacks: dict[str, _ProcCallbackConfig] = {}
        self._detached_proc_count = 0
        self._proc_mirror = ProcMirror(
            on_detached_count=self._on_detached_proc_count,
        )
        self._proc_mirror.start()

    def _stop_proc_mirror(self) -> None:
        """Drain and retire the durable proc mirror on the way out."""
        mirror = getattr(self, "_proc_mirror", None)
        if mirror is not None:
            mirror.stop(timeout=1.0)

    def _on_detached_proc_count(self, count: int) -> None:
        """Receive a detached-proc count from the mirror's writer thread."""
        try:
            self.call_from_thread(self._apply_detached_proc_count, count)  # type: ignore[attr-defined]
        except Exception:
            log.debug("detached proc count delivery failed", exc_info=True)

    def _apply_detached_proc_count(self, count: int) -> None:
        """Record the detached-proc count and repaint the indicator."""
        self._detached_proc_count = count
        self._update_proc_indicator()

    def _update_proc_indicator(self) -> None:
        """Update the top-bar proc indicator with the current running count.

        Counts global detached procs and this session's command procs, so an
        epic launch approved from Telegram shows up here as well.
        """
        try:
            indicator = self.query_one("#proc-indicator", ProcIndicator)  # type: ignore[attr-defined]
            detached = getattr(self, "_detached_proc_count", 0)
            indicator.set_count(self._proc_queue.running_count + detached)
        except Exception:
            pass

    def _submit_proc(
        self,
        proc_type: str,
        cl_name: str,
        project_file: str,
        proc_callable: Callable[..., tuple[bool, str]],
        on_success: Callable[[], None] | None = None,
    ) -> bool:
        """Submit a proc to run in background via run_worker().

        Returns False if a proc is already running for this Patch.
        The callable should return (success, message).
        Output capture (stdout/stderr redirect) is handled automatically.
        """

        def _callable(reporter: ProcReporter) -> TrackedProcResult[None]:
            success, message = _invoke_proc_callable(proc_callable, reporter)
            return TrackedProcResult(
                success=success,
                message=message,
                error=message if not success else None,
            )

        def _on_complete(completion: TrackedProcCompletion[None]) -> None:
            if not completion.success or on_success is None:
                return
            on_success()

        proc_info = self._submit_tracked_proc(
            proc_type,
            cl_name,
            project_file,
            _callable,
            on_complete=_on_complete if on_success is not None else None,
        )
        return proc_info is not None

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
        cl_name: str = "",
        project_file: str = "",
        cwd: str | Path | None = None,
        on_complete: Callable[[TrackedProcCompletion[Any]], None] | None = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> ProcInfo | None:
        """Submit argv through the detached proc service off the event loop.

        Completion is decoded only from the typed result envelope. The optional
        callback is a live-session convenience and is not authoritative after
        ACE restarts. Callable argv and request values are rejected here so
        this adapter never serializes or executes a Python callable.
        """
        from ..durable_submit import (
            DurableSubmitHandle,
            coerce_operation_request,
            decode_durable_completion,
            reject_callable_submission,
            submit_durable_proc_request,
        )
        from sase.ops import DurableSubmitError

        reject_callable_submission(argv, request)
        typed_request = coerce_operation_request(operation, request)
        work_cwd = str(cwd or os.getcwd())
        submit_label = label or display_name or operation

        if not hasattr(self, "_proc_completion_callbacks"):
            self._proc_completion_callbacks = {}
        if not hasattr(self, "_proc_workers"):
            self._proc_workers = {}

        existing = self._proc_queue.get_running_for_scopes(concurrency_keys)
        if existing is not None:
            self.notify(  # type: ignore[attr-defined]
                f"A {existing.proc_type} proc is already running for "
                f"{humanize_cl_name(cl_name or existing.cl_name)}",
                severity="warning",
            )
            return None

        presentation = self._proc_queue.submit(
            operation,
            cl_name,
            project_file,
            display_name=display_name or submit_label,
            exclusive_scopes=concurrency_keys,
        )

        def _off_loop() -> TrackedProcResult[Any]:
            handle: DurableSubmitHandle = submit_durable_proc_request(
                argv=argv,
                operation=operation,
                request=typed_request,
                cwd=work_cwd,
                label=submit_label,
                result_path=result_path,
                request_fingerprint=request_fingerprint,
                concurrency_keys=concurrency_keys,
                origin="ace",
                project=None,
                cl_name=cl_name or None,
            )
            presentation.durable_proc_id = handle.proc_id
            presentation.store_backed = True
            decoded = decode_durable_completion(handle)
            return TrackedProcResult(
                success=decoded.success,
                message=decoded.message,
                payload=None if decoded.payload is None else dict(decoded.payload),
                error=decoded.error,
            )

        def _wrapped() -> _ProcWorkerResult[Any]:
            try:
                result = _off_loop()
            except (DurableSubmitError, ProcSubmitError, Exception) as exc:
                log.exception("Durable proc %s failed to submit", operation)
                result = TrackedProcResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                )
            return _ProcWorkerResult(
                presentation.proc_id, result, presentation.get_live_output()
            )

        self._proc_completion_callbacks[presentation.proc_id] = _ProcCallbackConfig(
            on_complete=on_complete,  # type: ignore[arg-type]
            reload_on_complete=reload_on_complete,
            notify_on_complete=notify_on_complete,
        )
        worker: Worker[Any] = self.run_worker(  # type: ignore[attr-defined]
            _wrapped, thread=True
        )
        self._proc_workers[presentation.proc_id] = worker
        self._update_proc_indicator()
        return presentation

    def _submit_tracked_proc[T](
        self,
        proc_type: str,
        cl_name: str,
        project_file: str,
        proc_callable: Callable[..., TrackedProcResult[T]],
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        exclusive_scopes: Collection[str] = (),
        duplicate_message: str | None = None,
        on_complete: Callable[[TrackedProcCompletion[T]], None] | None = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> ProcInfo | None:
        """Submit a typed proc to run in a Textual worker thread.

        Returns None if a running proc already exists for the dedup scope.
        Existing Patch actions keep using :meth:`_submit_proc`;
        launch and other non-Patch work can provide ``display_name`` and
        ``dedup_key`` for clean proc-queue rows.
        """
        if not hasattr(self, "_proc_completion_callbacks"):
            self._proc_completion_callbacks = {}
        if not hasattr(self, "_proc_workers"):
            self._proc_workers = {}
        if not hasattr(self, "_proc_mirror"):
            # An unstarted mirror is inert, so callers that skipped
            # _init_proc_queue() simply do not mirror.
            self._proc_mirror = ProcMirror()

        existing = (
            self._proc_queue.get_running_for_key(dedup_key)
            if dedup_key is not None
            else self._proc_queue.get_running_for_cl(cl_name)
        )
        if existing is None:
            existing = self._proc_queue.get_running_for_scopes(exclusive_scopes)
        if existing is not None:
            msg = duplicate_message or (
                f"A {existing.proc_type} proc is already running for "
                f"{humanize_cl_name(cl_name)}"
            )
            self.notify(msg, severity="warning")  # type: ignore[attr-defined]
            return None

        proc_info = self._proc_queue.submit(
            proc_type,
            cl_name,
            project_file,
            display_name=display_name,
            dedup_key=dedup_key,
            exclusive_scopes=exclusive_scopes,
        )
        proc_id = proc_info.proc_id

        def _wrapped() -> _ProcWorkerResult[T]:
            """Run the callable with proc-local reporting."""
            reporter = ProcReporter(proc_info)
            with redirect_print_to(proc_info.log):
                try:
                    result = _invoke_proc_callable(proc_callable, reporter)
                except Exception as exc:
                    log.exception("Background proc %s failed", proc_id)
                    reporter.log(str(exc), stream="stderr")
                    result = TrackedProcResult(
                        success=False,
                        message=str(exc),
                        error=str(exc),
                    )
            if result.message:
                marker = "OK" if result.success else "ERROR"
                reporter.log(f"{marker}: {result.message}", stream="result")
            return _ProcWorkerResult(proc_id, result, proc_info.get_live_output())

        self._proc_completion_callbacks[proc_id] = _ProcCallbackConfig(
            on_complete=on_complete,  # type: ignore[arg-type]
            reload_on_complete=reload_on_complete,
            notify_on_complete=notify_on_complete,
        )

        self._proc_mirror.track(proc_info, cl_name=cl_name or None)

        worker: Worker[Any] = self.run_worker(  # type: ignore[attr-defined]
            _wrapped, thread=True
        )
        self._proc_workers[proc_id] = worker
        self._update_proc_indicator()
        return proc_info

    def _on_proc_worker_completed(
        self,
        worker: Worker[Any],
    ) -> None:
        """Handle a background-proc worker reaching SUCCESS state.

        Called from on_worker_state_changed; updates the ProcQueue, fires
        notifications, and triggers a reload.
        """
        result = worker.result
        if result is None:
            return

        if not isinstance(result, _ProcWorkerResult):
            proc_id, success, message, output = result
            result = _ProcWorkerResult(
                proc_id,
                TrackedProcResult(
                    success=success,
                    message=message,
                    error=message if not success else None,
                ),
                output,
            )

        proc_id = result.proc_id
        proc_result = result.result

        self._proc_queue.complete(
            proc_id,
            success=proc_result.success,
            message=proc_result.message,
            output=result.output,
            error=proc_result.error,
        )
        proc_info = self._proc_queue.get(proc_id)
        if proc_info is None:
            return
        self._proc_mirror.finish(
            proc_info,
            status="success" if proc_result.success else "error",
            message=proc_result.message,
            exit_code=proc_info.exit_code,
        )
        config = self._proc_completion_callbacks.pop(
            proc_id,
            _ProcCallbackConfig(
                on_complete=None,
                reload_on_complete=True,
                notify_on_complete=True,
            ),
        )

        if config.notify_on_complete:
            display_message = humanize_cl_names_in_text(proc_result.message)
            if proc_result.success:
                self.notify(display_message)  # type: ignore[attr-defined]
            else:
                self.notify(  # type: ignore[attr-defined]
                    f"Proc failed: {display_message}",
                    severity="error",
                )

        if config.on_complete is not None:
            try:
                config.on_complete(
                    TrackedProcCompletion(
                        proc_info=proc_info,
                        success=proc_result.success,
                        message=proc_result.message,
                        output=result.output,
                        payload=proc_result.payload,
                        error=proc_result.error,
                    )
                )
            except Exception:
                log.exception("Background proc %s completion callback failed", proc_id)

        # Reload the TUI
        if config.reload_on_complete:
            self._reload_and_reposition()  # type: ignore[attr-defined]

        self._proc_workers.pop(proc_id, None)

        self._update_proc_indicator()

    def _on_proc_worker_error(
        self,
        worker: Worker[Any],
    ) -> None:
        """Handle a background-proc worker reaching ERROR state.

        Called from on_worker_state_changed when the worker itself raised.
        """
        proc_id: str | None = None
        for tid, w in self._proc_workers.items():
            if w is worker:
                proc_id = tid
                break

        config = _ProcCallbackConfig(
            on_complete=None,
            reload_on_complete=True,
            notify_on_complete=True,
        )
        if proc_id is not None:
            error_msg = str(worker.error) if worker.error else "Unknown error"
            proc_info = self._proc_queue.get(proc_id)
            output = proc_info.get_live_output() if proc_info is not None else ""
            if proc_info is not None:
                proc_info.log.append(f"ERROR: {error_msg}", stream="result")
            self._proc_queue.complete(
                proc_id,
                success=False,
                message=error_msg,
                output=output,
                error=error_msg,
            )
            if proc_info is None:
                proc_info = self._proc_queue.get(proc_id)
            if proc_info is not None:
                self._proc_mirror.finish(
                    proc_info,
                    status="error",
                    message=error_msg,
                    exit_code=proc_info.exit_code,
                )
            config = self._proc_completion_callbacks.pop(
                proc_id,
                config,
            )
            if config.notify_on_complete:
                self.notify(  # type: ignore[attr-defined]
                    f"Proc failed: {error_msg}",
                    severity="error",
                )
            if config.on_complete is not None and proc_info is not None:
                try:
                    config.on_complete(
                        TrackedProcCompletion(
                            proc_info=proc_info,
                            success=False,
                            message=error_msg,
                            output=output,
                            error=error_msg,
                        )
                    )
                except Exception:
                    log.exception(
                        "Background proc %s completion callback failed", proc_id
                    )
            self._proc_workers.pop(proc_id, None)

        if proc_id is None or config.reload_on_complete:
            self._reload_and_reposition()  # type: ignore[attr-defined]
        self._update_proc_indicator()

    def _kill_proc(self, proc_id: str) -> bool:
        """Kill a running background proc by cancelling its worker.

        Returns True if the proc was found and killed.
        """
        worker = self._proc_workers.get(proc_id)
        if worker is None:
            return False

        proc_info = self._proc_queue.get(proc_id)
        if proc_info is not None:
            proc_info.terminate_processes()
            proc_info.log.append("ERROR: Killed by user", stream="result")

        worker.cancel()

        self._proc_queue.complete(
            proc_id,
            success=False,
            message="Killed by user",
            output=proc_info.get_live_output() if proc_info is not None else "",
            error="Killed by user",
        )

        if proc_info is not None:
            self._proc_mirror.finish(
                proc_info,
                status="killed",
                message="Killed by user",
                exit_code=proc_info.exit_code,
            )

        self._proc_workers.pop(proc_id, None)
        self._proc_completion_callbacks.pop(proc_id, None)

        self._update_proc_indicator()
        return True

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Route worker state changes for background procs."""
        if event.worker in self._proc_workers.values():
            if event.state == WorkerState.SUCCESS:
                self._on_proc_worker_completed(event.worker)
            elif event.state == WorkerState.ERROR:
                self._on_proc_worker_error(event.worker)
            return

        # Handle axe worker (defined in AxeMixin)
        axe_worker = getattr(self, "_axe_worker", None)
        if axe_worker is not None and event.worker is axe_worker:
            if event.state in (WorkerState.SUCCESS, WorkerState.ERROR):
                self._on_axe_worker_done(event.worker, event.state)  # type: ignore[attr-defined]


def _invoke_proc_callable[T](
    proc_callable: Callable[..., T], reporter: ProcReporter
) -> T:
    if _callable_accepts_reporter(proc_callable):
        return proc_callable(reporter)
    return proc_callable()


def _callable_accepts_reporter(proc_callable: Callable[..., object]) -> bool:
    try:
        params = signature(proc_callable).parameters.values()
    except (TypeError, ValueError):
        return False
    for param in params:
        if param.kind is Parameter.VAR_POSITIONAL:
            return True
        if param.kind in (
            Parameter.POSITIONAL_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False
