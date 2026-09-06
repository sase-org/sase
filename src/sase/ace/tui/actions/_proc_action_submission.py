"""Durable submission and session-worker support for proc actions."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Collection, Mapping, Sequence
from inspect import Parameter, signature
from pathlib import Path
from typing import Any

from textual.worker import Worker

from sase.core.time import local_now
from sase.procs import ProcSubmitError
from sase.project_display_names import humanize_cl_name

from ..proc_observer import ObservedProc, ProcObserver, ProcProjection
from ..session_proc_reporter import SessionProcReporter
from ._proc_action_observer import ProcObserverActionsMixin
from ._proc_action_types import (
    DurableSubmitWorkerResult,
    ProcCallbackConfig,
    SessionWorkerResult,
    TrackedProcCompletion,
    TrackedProcResult,
)

log = logging.getLogger(__name__)


class ProcSubmissionActionsMixin(ProcObserverActionsMixin):
    """Submit durable procs and UI-session-local workers."""

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
        on_handle: Callable[[str, str], None] | None = None,
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
        self._proc_completion_callbacks[placeholder_id] = ProcCallbackConfig(
            on_complete=on_complete,
            reload_on_complete=reload_on_complete,
            notify_on_complete=notify_on_complete,
            on_handle=on_handle,
            on_settled=on_settled,
            workspace_claim=workspace_claim,
        )

        def _submit() -> DurableSubmitWorkerResult:
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
                return DurableSubmitWorkerResult(
                    placeholder_id=placeholder_id,
                    handle=handle,
                )
            except ProcSubmitError as exc:
                if is_concurrency_collision(exc):
                    release_workspace_claim(workspace_claim)
                    return DurableSubmitWorkerResult(
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
                return DurableSubmitWorkerResult(
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
                return DurableSubmitWorkerResult(
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
        body: Callable[..., TrackedProcResult[T]],
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
            session_id=durable.session_id or getattr(self, "_proc_session_id", None),
            session_live=True,
        )

        def _wrapped() -> SessionWorkerResult[T]:
            reporter = SessionProcReporter(proc_info)
            try:
                result = _invoke_session_worker_body(body, reporter)
            except Exception as exc:
                log.exception("Session worker %s failed", proc_type)
                reporter.log(str(exc), stream="stderr")
                result = TrackedProcResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                )
            if result.message:
                marker = "OK" if result.success else "ERROR"
                reporter.log(f"{marker}: {result.message}", stream="result")
            return SessionWorkerResult(
                proc_info.proc_id,
                result,
                proc_info.get_live_output(),
            )

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


def _invoke_session_worker_body[T](
    body: Callable[..., TrackedProcResult[T]],
    reporter: SessionProcReporter,
) -> TrackedProcResult[T]:
    """Call *body* with *reporter* when the callable accepts that argument."""
    if _callable_accepts_reporter(body):
        return body(reporter)
    return body()


def _callable_accepts_reporter(body: Callable[..., object]) -> bool:
    try:
        params = signature(body).parameters.values()
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
