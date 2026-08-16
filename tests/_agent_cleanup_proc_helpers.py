"""Shared harness helpers for tracked kill/dismiss cleanup-task tests.

The kill/dismiss persistence stage is submitted through
``CleanupProcMixin._submit_cleanup_proc`` -> ``_submit_session_worker``. Test
harnesses mix in :class:`TrackedProcRecorderMixin` to record those
submissions, and :func:`run_tracked_proc` replays a recorded task body and
its completion callback synchronously (including any coroutine callbacks the
completion schedules via ``call_later``, e.g. the off-thread
notification-count refresh).
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime
from typing import Any

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.proc_queue import ProcInfo


class TrackedProcRecorderMixin:
    """Records session-worker submissions for later synchronous replay."""

    tracked_procs: list[dict[str, Any]]

    def _init_tracked_task_recorder(self) -> None:
        self.tracked_procs = []

    def _submit_cleanup_proc(
        self,
        *,
        proc_type: str,
        display_name: str,
        cl_name: str,
        project_file: str,
        payload: dict[str, object] | None = None,
        proc_callable: Any = None,
        on_settled: Any = None,
    ) -> bool:
        del payload

        def _callable() -> Any:
            try:
                if proc_callable is None:
                    return TrackedProcResult(success=True, message="ok")
                return _coerce_tracked_result(proc_callable())
            finally:
                if on_settled is not None:
                    on_settled()

        self._submit_tracked_proc(
            proc_type,
            cl_name,
            project_file,
            _callable,
            display_name=display_name,
            on_complete=self._on_cleanup_proc_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        return True

    def _submit_durable_proc(
        self,
        argv: Any,
        *,
        operation: str = "",
        request: Any = None,
        request_fingerprint: str = "",
        concurrency_keys: Any = (),
        proc_type: str | None = None,
        display_name: str | None = None,
        cl_name: str = "",
        project_file: str = "",
        on_complete: Any = None,
        reload_on_complete: bool = False,
        notify_on_complete: bool = False,
        live_body: Any = None,
        on_settled: Any = None,
        **kwargs: Any,
    ) -> ProcInfo:
        del argv, operation, request_fingerprint, concurrency_keys, kwargs
        payload = dict(request or {})

        def _callable() -> Any:
            try:
                if live_body is not None:
                    return _coerce_tracked_result(live_body())
                return TrackedProcResult(
                    success=payload.get("success", True) is not False,
                    message=str(payload.get("message") or "ok"),
                    payload=payload,
                )
            finally:
                if on_settled is not None:
                    on_settled()

        return self._submit_tracked_proc(
            proc_type or "cleanup",
            cl_name,
            project_file,
            _callable,
            display_name=display_name,
            on_complete=on_complete,
            reload_on_complete=reload_on_complete,
            notify_on_complete=notify_on_complete,
        )

    def _submit_session_worker(
        self,
        proc_type: str,
        proc_callable: Any,
        *,
        display_name: str | None = None,
        cl_name: str = "",
        project_file: str = "",
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        exclusive_scopes: Any = (),
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> ProcInfo:
        del exclusive_scopes
        return self._submit_tracked_proc(
            proc_type,
            cl_name,
            project_file,
            proc_callable,
            display_name=display_name,
            dedup_key=dedup_key,
            duplicate_message=duplicate_message,
            on_complete=on_complete,
            reload_on_complete=reload_on_complete,
            notify_on_complete=notify_on_complete,
        )

    def _submit_tracked_proc(
        self,
        proc_type: str,
        cl_name: str,
        project_file: str,
        proc_callable: Any,
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> ProcInfo:
        del duplicate_message
        proc_info = ProcInfo(
            proc_id=f"task-{len(self.tracked_procs)}",
            proc_type=proc_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="",
            started_at=datetime(2026, 1, 1, 12, 0, 0),
            display_name=display_name,
            dedup_key=dedup_key,
        )
        self.tracked_procs.append(
            {
                "proc_type": proc_type,
                "cl_name": cl_name,
                "project_file": project_file,
                "proc_callable": proc_callable,
                "display_name": display_name,
                "dedup_key": dedup_key,
                "on_complete": on_complete,
                "reload_on_complete": reload_on_complete,
                "notify_on_complete": notify_on_complete,
                "proc_info": proc_info,
            }
        )
        return proc_info


def run_tracked_proc(app: Any, task: dict[str, Any]) -> TrackedProcCompletion[Any]:
    """Run a recorded task body, fire its completion, and drain async effects."""
    result = _coerce_tracked_result(task["proc_callable"]())
    proc_info = task["proc_info"]
    proc_info.status = "success" if result.success else "error"
    proc_info.message = result.message
    completion: TrackedProcCompletion[Any] = TrackedProcCompletion(
        proc_info=proc_info,
        success=result.success,
        message=result.message,
        output="",
        payload=result.payload,
        error=result.error,
    )

    async def _run_completion_effects() -> None:
        on_complete = task["on_complete"]
        if on_complete is not None:
            on_complete(completion)

        # New completion effects use retained pump-free tasks. Drain until
        # stable because a coalesced completion may spawn one follow-up.
        while tasks := list(getattr(app, "_pump_free_async_tasks", ())):
            await asyncio.gather(*tasks)
            await asyncio.sleep(0)

        # Keep compatibility for unrelated synchronous test doubles that
        # intentionally record coroutine callbacks in ``_scheduled``.
        scheduled = getattr(app, "_scheduled", None)
        if scheduled is not None:
            for entry in list(scheduled):
                callback, args = entry
                if inspect.iscoroutinefunction(callback):
                    await callback(*args)
                    scheduled.remove(entry)

    asyncio.run(_run_completion_effects())
    return completion


def _coerce_tracked_result(result: Any) -> TrackedProcResult[Any]:
    """Normalize cleanup test callables to the central tracked-result shape."""
    if isinstance(result, TrackedProcResult):
        return result

    from sase.ace.tui.actions.agents._cleanup_procs import CleanupProcOutcome

    if isinstance(result, CleanupProcOutcome):
        return TrackedProcResult(
            success=result.success,
            message=result.message,
            payload=result,
            error=result.message if not result.success else None,
        )
    return TrackedProcResult(
        success=bool(getattr(result, "success", True)),
        message=str(getattr(result, "message", "ok")),
        payload=result,
        error=None if getattr(result, "success", True) else str(result),
    )
