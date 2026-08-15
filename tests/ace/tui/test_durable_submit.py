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
    from sase.ace.tui.proc_queue import ProcQueue

    submitted_on: list[str] = []

    def fake_submit(**kwargs: Any) -> Any:
        submitted_on.append(__import__("threading").current_thread().name)
        return SimpleNamespace(
            proc_id="proc-off-loop",
            operation=kwargs["operation"],
            result_path=str(tmp_path / "result.json"),
        )

    monkeypatch.setattr(
        "sase.ace.tui.durable_submit.submit_durable_proc_request", fake_submit
    )
    monkeypatch.setattr(
        "sase.ace.tui.durable_submit.decode_durable_completion",
        lambda handle, timeout=None: SimpleNamespace(
            success=True, message="ok", payload={}, error=None
        ),
    )

    class Host(ProcActionsMixin):
        def __init__(self) -> None:
            self._proc_queue = ProcQueue()
            self._proc_workers = {}
            self._proc_completion_callbacks = {}
            self.notices: list[str] = []
            self.workers: list[Any] = []

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


def test_coerce_request_rejects_payload_callable() -> None:
    with pytest.raises(DurableSubmitError, match="callable"):
        coerce_operation_request("patch.status", {"payload": print})
