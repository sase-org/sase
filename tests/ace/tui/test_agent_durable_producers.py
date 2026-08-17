"""Tests for agent durable producer argv, keys, and rollback guards."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agent_durable import (
    submit_agent_cleanup,
    submit_agent_directive,
    submit_agent_launch,
    submit_agent_revert,
)
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.durable_ops import (
    agent_directive_concurrency_key,
    agent_tribe_concurrency_key,
    launch_concurrency_key,
)
from sase.ace.tui.proc_queue import ProcInfo
from sase.ops.names import AGENT_CLEANUP, AGENT_PERSIST_DIRECTIVE, RUN_LAUNCH


class _Host:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _submit_durable_proc(self, argv: list[str], **kwargs: Any) -> object:
        self.calls.append({"argv": argv, **kwargs})
        return SimpleNamespace(proc_id="p1")


def test_directive_argv_payload_and_key() -> None:
    host = _Host()
    assert submit_agent_directive(
        host,
        artifacts_dir="/tmp/arts",
        payload={"meta_set": {"approve": True}, "prompt": {"kind": "set_auto_mode"}},
        cl_name="demo",
        display_name="Persist auto",
    )
    call = host.calls[0]
    assert call["argv"][2:5] == ["sase", "agent", "persist-directive"]
    assert call["operation"] == AGENT_PERSIST_DIRECTIVE
    assert call["concurrency_keys"] == (agent_directive_concurrency_key("/tmp/arts"),)
    assert call["request"]["meta_set"] == {"approve": True}


def test_tribe_uses_shared_store_key() -> None:
    host = _Host()
    submit_agent_directive(
        host,
        artifacts_dir="/tmp/arts",
        payload={"updates": []},
        cl_name="tribes",
        display_name="Persist tribes",
        tribe_store=True,
    )
    assert host.calls[0]["concurrency_keys"] == (agent_tribe_concurrency_key(),)


def test_independent_artifacts_dirs_do_not_collide() -> None:
    host = _Host()
    submit_agent_directive(
        host,
        artifacts_dir="/tmp/a",
        payload={},
        cl_name="a",
        display_name="a",
    )
    submit_agent_directive(
        host,
        artifacts_dir="/tmp/b",
        payload={},
        cl_name="b",
        display_name="b",
    )
    assert host.calls[0]["concurrency_keys"] != host.calls[1]["concurrency_keys"]


def test_launch_and_cleanup_argv() -> None:
    host = _Host()
    submit_agent_launch(
        host,
        prompt="#git:sase do work",
        workflow="ace(run)-1",
        cl_name="sase",
        project_file="/p/p.sase",
        display_name="launch sase",
    )
    submit_agent_cleanup(
        host,
        proc_type="kill",
        identity="id-1",
        payload={"action": "kill", "message": "Killed"},
        cl_name="sase",
        project_file="/p/p.sase",
        display_name="kill agent",
    )
    launch = host.calls[0]
    cleanup = host.calls[1]
    assert launch["argv"][2:4] == ["sase", "run"]
    assert launch["operation"] == RUN_LAUNCH
    assert launch["concurrency_keys"] == (launch_concurrency_key("ace(run)-1"),)
    assert "do work" not in launch["argv"]
    assert launch["request"]["prompt"] == "#git:sase do work"
    assert launch["request"]["allow_force_reuse"] is True
    assert cleanup["argv"][2:5] == ["sase", "agent", "persist-cleanup"]
    assert cleanup["operation"] == AGENT_CLEANUP


def test_stale_callback_skips_rollback() -> None:
    rolled_back = []

    def on_complete(completion: TrackedProcCompletion[object]) -> None:
        if completion.collision or completion.success:
            return
        if token != "current":
            return
        rolled_back.append(True)

    token = "current"
    info = ProcInfo(
        proc_id="x",
        proc_type="agent-directive",
        cl_name="a",
        project_file="/tmp",
        status="error",
        message="fail",
        started_at=__import__("datetime").datetime.now(),
    )
    token = "newer"
    on_complete(
        TrackedProcCompletion(
            proc_info=info,
            success=False,
            message="fail",
            output="",
        )
    )
    assert rolled_back == []
    on_complete(
        TrackedProcCompletion(
            proc_info=info,
            success=False,
            message="busy",
            output="",
            collision=True,
        )
    )
    assert rolled_back == []


def test_revert_execute_carries_preview_in_request() -> None:
    host = _Host()
    submit_agent_revert(
        host,
        name="foo",
        payload={"preview": {"agent_name": "foo", "shas": ["abc"]}, "shas": ["abc"]},
        cl_name="cl",
        project_file="/p",
        display_name="Revert foo",
        concurrency_key="ace:agent-revert:execute:foo",
    )
    call = host.calls[0]
    assert call["argv"][2:5] == ["sase", "agent", "revert"]
    assert call["request"]["shas"] == ["abc"]
    assert "abc" not in call["argv"]
