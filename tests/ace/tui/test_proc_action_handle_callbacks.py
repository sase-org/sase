"""Durable proc handle-arrival callback coverage."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.proc_actions import ProcActionsMixin, TrackedProcCompletion
from sase.ace.tui.durable_submit import DurableSubmitHandle
from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcCompletionRecord,
    ProcProjection,
)
from sase.core.time import local_now
from sase.ops import DurableOperationResult
from sase.procs import ProcSubmitError


class _HandleHost(ProcActionsMixin):
    def __init__(self) -> None:
        self._proc_projection = ProcProjection()
        self._durable_submit_workers: dict[str, Any] = {}
        self._proc_completion_callbacks: dict[str, Any] = {}
        self._proc_pending_scopes: dict[str, frozenset[str]] = {}
        self.workers: list[Any] = []
        self.submitted: list[dict[str, Any]] = []
        self.removed: list[str] = []
        self._proc_observer = SimpleNamespace(
            register_pending=self._register_pending,
            register_submitted=lambda **kwargs: self.submitted.append(kwargs),
            remove_pending=self.removed.append,
        )

    def _register_pending(self, **kwargs: Any) -> ObservedProc:
        return _proc_row("pending-1", status="pending", **kwargs)

    def run_worker(self, fn: Any, *, thread: bool = False) -> Any:
        assert thread is True
        worker = SimpleNamespace(result=None, error=None, fn=fn)
        self.workers.append(worker)
        return worker

    def notify(self, message: str, *, severity: str | None = None) -> None:
        del message, severity

    def _update_proc_indicator(self) -> None:
        pass

    def _reload_and_reposition(self) -> None:
        pass


def _proc_row(
    proc_id: str,
    *,
    status: str,
    proc_type: str = "launch",
    cl_name: str = "demo",
    project_file: str = "/tmp/demo.sase",
    display_name: str = "launch demo",
    **kwargs: object,
) -> ObservedProc:
    del kwargs
    return ObservedProc(
        proc_id=proc_id,
        proc_type=proc_type,
        cl_name=cl_name,
        project_file=project_file,
        status=status,
        message=status,
        started_at=local_now(),
        display_name=display_name,
    )


def _submit(
    host: _HandleHost,
    *,
    on_handle: Any,
    on_complete: Any,
) -> ObservedProc:
    proc = host._submit_durable_proc(
        ["sase", "run"],
        operation="run.launch",
        request={"prompt": "do work"},
        request_fingerprint="sha256:test",
        on_handle=on_handle,
        on_complete=on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )
    assert proc is not None
    return proc


def test_handle_callback_fires_once_and_completion_uses_durable_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.durable_submit.submit_durable_proc_request",
        lambda **kwargs: DurableSubmitHandle(
            proc_id="durable-1",
            operation=kwargs["operation"],
            result_path="/tmp/result.json",
        ),
    )
    host = _HandleHost()
    handles: list[tuple[str, str]] = []
    completions: list[TrackedProcCompletion[Any]] = []
    placeholder = _submit(
        host,
        on_handle=lambda old, new: handles.append((old, new)),
        on_complete=completions.append,
    )

    worker = host.workers[0]
    worker.result = worker.fn()
    host._on_durable_submit_worker_completed(worker)

    assert handles == [(placeholder.proc_id, "durable-1")]
    assert placeholder.proc_id not in host._proc_completion_callbacks
    assert "durable-1" in host._proc_completion_callbacks
    assert host.submitted[0]["placeholder_id"] == placeholder.proc_id

    durable_row = _proc_row("durable-1", status="success")
    host._deliver_observed_completion(
        ProcCompletionRecord(
            proc_id="durable-1",
            operation="run.launch",
            result=DurableOperationResult(
                operation="run.launch",
                proc_id="durable-1",
                success=True,
                message="done",
            ),
        ),
        ProcProjection(rows=(durable_row,)),
    )

    assert len(completions) == 1
    assert completions[0].proc_info.proc_id == "durable-1"


def test_handle_callback_does_not_fire_when_submit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_submit(**kwargs: object) -> None:
        del kwargs
        raise ProcSubmitError("submit failed")

    monkeypatch.setattr(
        "sase.ace.tui.durable_submit.submit_durable_proc_request",
        fail_submit,
    )
    host = _HandleHost()
    handles: list[tuple[str, str]] = []
    completions: list[TrackedProcCompletion[Any]] = []
    placeholder = _submit(
        host,
        on_handle=lambda old, new: handles.append((old, new)),
        on_complete=completions.append,
    )

    worker = host.workers[0]
    worker.result = worker.fn()
    host._on_durable_submit_worker_completed(worker)

    assert handles == []
    assert len(completions) == 1
    assert completions[0].proc_info.proc_id == placeholder.proc_id
    assert completions[0].success is False
    assert placeholder.proc_id not in host._proc_completion_callbacks


def test_handle_callback_failure_does_not_break_completion_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.durable_submit.submit_durable_proc_request",
        lambda **kwargs: DurableSubmitHandle(
            proc_id="durable-1",
            operation=kwargs["operation"],
            result_path="/tmp/result.json",
        ),
    )
    host = _HandleHost()

    def fail_handle(old_proc_id: str, new_proc_id: str) -> None:
        raise RuntimeError(f"cannot rekey {old_proc_id} to {new_proc_id}")

    _submit(host, on_handle=fail_handle, on_complete=lambda completion: None)
    worker = host.workers[0]
    worker.result = worker.fn()

    host._on_durable_submit_worker_completed(worker)

    assert "durable-1" in host._proc_completion_callbacks
    assert host.submitted[0]["proc_id"] == "durable-1"
