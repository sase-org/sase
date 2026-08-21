"""Tests for Patch durable producer argv, keys, and completion mapping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.patch_durable import submit_patch_operation
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.durable_ops import patch_concurrency_key
from sase.ace.tui.proc_observer import ObservedProc as ProcInfo
from sase.ops.names import PATCH_STATUS


class _Host:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _submit_durable_proc(self, argv: list[str], **kwargs: Any) -> object:
        self.calls.append({"argv": argv, **kwargs})
        return SimpleNamespace(proc_id="p1")


def test_status_submit_uses_sase_patch_argv_and_project_key() -> None:
    host = _Host()
    assert submit_patch_operation(
        host,
        verb="status",
        name="demo",
        project_file="/proj/alpha/alpha.sase",
        extra_argv=("Ready",),
        payload={"status": "Ready"},
    )
    call = host.calls[0]
    assert call["argv"][1:4] == ["-m", "sase", "patch"]
    assert "status" in call["argv"]
    assert "demo" in call["argv"]
    assert "Ready" in call["argv"]
    assert "-p" in call["argv"]
    assert call["operation"] == PATCH_STATUS
    assert call["concurrency_keys"] == (
        patch_concurrency_key("/proj/alpha/alpha.sase", "demo"),
    )
    assert call["request"]["status"] == "Ready"
    assert call["request_fingerprint"].startswith("sha256:")


def test_two_projects_do_not_share_a_patch_key() -> None:
    host = _Host()
    submit_patch_operation(host, verb="revert", name="demo", project_file="/a/one.sase")
    submit_patch_operation(host, verb="revert", name="demo", project_file="/b/two.sase")
    assert host.calls[0]["concurrency_keys"] != host.calls[1]["concurrency_keys"]


def test_accept_completion_maps_payload_and_skips_collision() -> None:
    seen: list[str] = []

    def on_complete(completion: TrackedProcCompletion[object]) -> None:
        if completion.collision:
            return
        if completion.success:
            seen.append("mail")

    host = _Host()
    submit_patch_operation(
        host,
        verb="accept",
        name="demo",
        project_file="/p/p.sase",
        payload={"entries": [["2a", None]], "mark_ready_to_mail": True},
        on_complete=on_complete,
    )
    callback = host.calls[0]["on_complete"]
    info = ProcInfo(
        proc_id="x",
        proc_type="accept",
        cl_name="demo",
        project_file="/p/p.sase",
        status="success",
        message="ok",
        started_at=__import__("datetime").datetime.now(),
    )
    callback(
        TrackedProcCompletion(
            proc_info=info,
            success=False,
            message="busy",
            output="",
            collision=True,
        )
    )
    assert seen == []
    callback(
        TrackedProcCompletion(
            proc_info=info,
            success=True,
            message="accepted",
            output="",
            payload={"name": "demo"},
        )
    )
    assert seen == ["mail"]
