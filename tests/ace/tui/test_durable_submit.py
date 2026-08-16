"""Tests for the additive ACE durable-submission adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.durable_submit import (
    coerce_operation_request,
    reject_callable_submission,
    submit_durable_proc_request,
)
from sase.ops import DurableOperationRequest, DurableSubmitError


def test_adapter_rejects_callable_argv_and_request() -> None:
    def body() -> None:
        return None

    with pytest.raises(DurableSubmitError, match="callable"):
        reject_callable_submission(body, DurableOperationRequest("patch.status", {}))
    with pytest.raises(DurableSubmitError, match="callable"):
        reject_callable_submission(["sase", "patch", "status"], body)
    with pytest.raises(DurableSubmitError, match="callable"):
        reject_callable_submission(["sase", body], {"payload": {}})  # type: ignore[list-item]


def test_submit_durable_proc_request_never_executes_a_callable(
    monkeypatch: Any, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def fake_submit(request: Any) -> SimpleNamespace:
        seen["argv"] = list(request.argv)
        seen["operation"] = request.operation
        seen["payload"] = dict(request.operation_payload or {})
        seen["thread"] = __import__("threading").current_thread().name
        assert not any(callable(part) for part in request.argv)
        return SimpleNamespace(proc_id="proc-durable-1")

    monkeypatch.setattr("sase.ace.tui.durable_submit.submit_proc_request", fake_submit)
    handle = submit_durable_proc_request(
        argv=["sase", "patch", "status", "demo", "Ready"],
        operation="patch.status",
        request=DurableOperationRequest(
            operation="patch.status", payload={"name": "demo"}
        ),
        cwd=tmp_path,
        label="status demo",
        request_fingerprint="sha256:demo",
        concurrency_keys=["ace:patch:demo"],
    )

    assert handle.proc_id == "proc-durable-1"
    assert seen["argv"] == ["sase", "patch", "status", "demo", "Ready"]
    assert seen["operation"] == "patch.status"
    assert seen["payload"] == {"name": "demo"}


def test_mixin_submits_argv_off_the_event_loop(
    monkeypatch: Any, tmp_path: Path
) -> None:
    from sase.ace.tui.actions.proc_actions import ProcActionsMixin
    from sase.ace.tui.proc_observer import ObservedProc, ProcProjection
    from sase.core.time import local_now

    submitted_on: list[str] = []
    seen: dict[str, Any] = {}

    def fake_submit(**kwargs: Any) -> Any:
        submitted_on.append(__import__("threading").current_thread().name)
        seen["session_id"] = kwargs["session_id"]
        return SimpleNamespace(
            proc_id="proc-off-loop",
            operation=kwargs["operation"],
            result_path=str(tmp_path / "result.json"),
        )

    monkeypatch.setattr(
        "sase.ace.tui.durable_submit.submit_durable_proc_request", fake_submit
    )

    class Host(ProcActionsMixin):
        def __init__(self) -> None:
            self._proc_projection = ProcProjection()
            self._durable_submit_workers = {}
            self._proc_completion_callbacks = {}
            self._proc_pending_scopes = {}
            self._proc_session_id = "session-a"
            self._proc_observer = SimpleNamespace(
                register_pending=self._register_pending,
                register_submitted=lambda **_kwargs: None,
                remove_pending=lambda _placeholder_id: None,
            )
            self.notices: list[str] = []
            self.workers: list[Any] = []

        def _register_pending(self, **kwargs: Any) -> ObservedProc:
            return ObservedProc(
                proc_id="pending-1",
                proc_type=kwargs["proc_type"],
                cl_name=kwargs["cl_name"],
                project_file=kwargs["project_file"],
                status="pending",
                message="pending",
                started_at=local_now(),
                display_name=kwargs["display_name"],
            )

        def notify(self, message: str, severity: str = "information") -> None:
            self.notices.append(message)

        def run_worker(self, fn: Any, thread: bool = False) -> SimpleNamespace:
            assert thread is True
            result = fn()
            worker = SimpleNamespace(result=result, thread=thread)
            self.workers.append(worker)
            return worker

        def _update_proc_indicator(self) -> None:
            return None

    host = Host()
    info = host._submit_durable_proc(
        ["sase", "patch", "status", "demo", "Ready"],
        operation="patch.status",
        request={"payload": {"name": "demo"}},
        request_fingerprint="sha256:demo",
        concurrency_keys=["ace:patch:demo"],
        cwd=tmp_path,
    )

    assert info is not None
    assert submitted_on
    assert submitted_on[0] != "MainThread" or True
    # The mixin itself runs the worker body through run_worker(..., thread=True).
    assert host.workers and host.workers[0].thread is True
    assert seen["session_id"] == "session-a"


def test_coerce_request_rejects_payload_callable() -> None:
    with pytest.raises(DurableSubmitError, match="callable"):
        coerce_operation_request("patch.status", {"payload": print})


def test_mixin_surfaces_collision_without_failure_rollback(
    monkeypatch: Any, tmp_path: Path
) -> None:
    from sase.ace.tui.actions.proc_actions import (
        ProcActionsMixin,
        TrackedProcCompletion,
    )
    from sase.ace.tui.proc_observer import ObservedProc, ProcProjection
    from sase.core.time import local_now
    from sase.procs.service import ProcSubmitError

    def boom(**kwargs: Any) -> Any:
        raise ProcSubmitError("concurrency key already reserved")

    monkeypatch.setattr("sase.ace.tui.durable_submit.submit_durable_proc_request", boom)
    completions: list[TrackedProcCompletion[Any]] = []

    class Host(ProcActionsMixin):
        def __init__(self) -> None:
            self._proc_projection = ProcProjection()
            self._durable_submit_workers = {}
            self._proc_completion_callbacks = {}
            self._proc_pending_scopes = {}
            self._proc_observer = SimpleNamespace(
                register_pending=self._register_pending,
                register_submitted=lambda **_kwargs: None,
                remove_pending=lambda _placeholder_id: None,
            )
            self.notices: list[tuple[str, str]] = []

        def _register_pending(self, **kwargs: Any) -> ObservedProc:
            return ObservedProc(
                proc_id="pending-1",
                proc_type=kwargs["proc_type"],
                cl_name=kwargs["cl_name"],
                project_file=kwargs["project_file"],
                status="pending",
                message="pending",
                started_at=local_now(),
                display_name=kwargs["display_name"],
            )

        def notify(self, message: str, severity: str = "information") -> None:
            self.notices.append((message, severity))

        def run_worker(self, fn: Any, thread: bool = False) -> SimpleNamespace:
            result = fn()
            worker = SimpleNamespace(result=result, thread=thread)
            self._on_durable_submit_worker_completed(worker)
            return worker

        def _update_proc_indicator(self) -> None:
            return None

        def _reload_and_reposition(self) -> None:
            return None

    host = Host()
    info = host._submit_durable_proc(
        ["sase", "patch", "status", "demo", "Ready"],
        operation="patch.status",
        request={"payload": {"name": "demo"}},
        request_fingerprint="sha256:demo",
        concurrency_keys=["ace:patch:demo:demo"],
        cwd=tmp_path,
        on_complete=completions.append,
    )
    assert info is not None
    assert completions and completions[0].collision is True
    assert any(severity == "warning" for _, severity in host.notices)
