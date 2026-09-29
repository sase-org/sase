"""Shared harness for the ``test_proc_actions_session_workers_*`` test modules.

Public helpers used by more than one split module live here under public
names so no new module imports a ``_``-prefixed name from another new
module.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.proc_actions import ProcActionsMixin, TrackedProcResult
from sase.ace.tui.proc_observer import ObservedProc, ProcProjection
from sase.core.time import local_now

__all__ = [
    "ProcHost",
    "durable_row",
    "ok_result",
    "sync_row",
]


class ProcHost(ProcActionsMixin):
    def __init__(self, projection: ProcProjection | None = None) -> None:
        self._proc_projection = projection or ProcProjection()
        self._durable_submit_workers: dict[str, Any] = {}
        self._session_workers: dict[str, Any] = {}
        self._session_completion_callbacks: dict[str, Any] = {}
        self._proc_completion_callbacks: dict[str, Any] = {}
        self._proc_pending_scopes: dict[str, frozenset[str]] = {}
        self.submitted_handles: list[Any] = []
        self._proc_observer = SimpleNamespace(
            register_pending=self._register_pending,
            register_submitted=self._register_submitted,
            remove_pending=lambda _placeholder_id: None,
        )
        self.notices: list[tuple[str, str]] = []
        self.workers: list[Any] = []
        self.pending_count = 0
        self.indicator_counts: list[int] = []

    def _register_submitted(self, **kwargs: Any) -> None:
        self.submitted_handles.append(kwargs)

    def _register_pending(self, **kwargs: Any) -> ObservedProc:
        self.pending_count += 1
        return ObservedProc(
            proc_id=f"pending-{self.pending_count}",
            proc_type=kwargs["proc_type"],
            cl_name=kwargs["cl_name"],
            project_file=kwargs["project_file"],
            status="pending",
            message="pending",
            started_at=local_now(),
            display_name=kwargs["display_name"],
            exclusive_scopes=frozenset(kwargs.get("exclusive_scopes", ())),
        )

    def notify(self, message: str, severity: str = "information") -> None:
        self.notices.append((message, severity))

    def run_worker(self, fn: Any, *, thread: bool = False) -> Any:
        assert thread is True
        worker = SimpleNamespace(result=None, error=None, _fn=fn)
        self.workers.append(worker)
        return worker

    def _update_proc_indicator(self) -> None:
        self.indicator_counts.append(self._effective_proc_projection().active_count)

    def _reload_and_reposition(self) -> None:
        return None

    def complete_session_worker(self, index: int = 0) -> None:
        worker = self.workers[index]
        worker.result = worker._fn()
        self._on_session_worker_completed(worker)

    def fail_session_worker(self, index: int = 0) -> None:
        worker = self.workers[index]
        worker.error = RuntimeError("boom")
        self._on_session_worker_error(worker)


def ok_result() -> TrackedProcResult[None]:
    return TrackedProcResult(success=True, message="ok")


def durable_row(*, scope: str) -> ObservedProc:
    return ObservedProc(
        proc_id="durable-1",
        proc_type="durable-update",
        cl_name="sase",
        project_file="",
        status="running",
        message="running",
        started_at=local_now(),
        exclusive_scopes=frozenset({scope}),
    )


def sync_row(proc_id: str) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type="sync",
        cl_name="",
        project_file="",
        status="running",
        message="running",
        started_at=local_now(),
        display_name="sync",
    )
