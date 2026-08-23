"""Proc fingerprint and guarded-argv coverage for approved-epic launch."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.bead.epic_launch import build_epic_launch_argv, start_epic_launch_monitor
from sase.dev_update.code_swap_lock import (
    guarded_exec_argv,
    logical_argv_from_guarded_exec,
)
from sase.procs.request import (
    ProcSubmitRequest,
    proc_request_fingerprint,
    request_sidecar_payload,
)

from .epic_launch_test_helpers import fake_lease, start_epic_launch_monitor_request


def test_epic_launch_proc_fingerprint_uses_logical_command_not_bootstrap() -> None:
    logical = ["sase", "bead", "work", "/tmp/epic.md", "--yes-to-all"]
    first = ProcSubmitRequest(
        argv=guarded_exec_argv(logical),
        command=logical,
        label="Epic launch · epic",
        cwd="/tmp",
        origin="api",
        project="sase",
        tags=["epic", "launch"],
    )
    second = ProcSubmitRequest(
        argv=[
            "/other/python",
            "/other/code_swap_guarded_exec.py",
            "/other/code-swap.lock",
            "--",
            *logical,
        ],
        command=logical,
        label="Epic launch · epic",
        cwd="/tmp",
        origin="api",
        project="sase",
        tags=["epic", "launch"],
    )
    kwargs = {"proc_id": "p1", "cwd": "/tmp"}
    assert proc_request_fingerprint(
        first, argv=list(first.argv), **kwargs
    ) == proc_request_fingerprint(second, argv=list(second.argv), **kwargs)


def test_epic_launch_sidecar_persists_execution_argv_and_logical_command() -> None:
    logical = ["sase", "bead", "work", "/tmp/epic.md", "--yes-to-all"]
    execution = guarded_exec_argv(logical)
    request = ProcSubmitRequest(
        argv=execution,
        command=logical,
        label="Epic launch · epic",
        cwd="/tmp",
        origin="api",
    )
    payload = request_sidecar_payload(
        request,
        proc_id="p1",
        argv=execution,
        cwd="/tmp",
        log_path="/tmp/p1.log",
        fingerprint="sha256:test",
    )
    assert payload["argv"] == execution
    assert payload["command"] == logical
    reconstructed = logical_argv_from_guarded_exec(payload["argv"])
    assert reconstructed == logical


def test_monitor_and_fallback_proc_share_guarded_execution_argv(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "auth rewrite.md"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "planner", "agent_family": "planner"}) + "\n",
        encoding="utf-8",
    )
    logical = build_epic_launch_argv(
        plan,
        artifacts_dir=artifacts,
        cl_name="demo",
    )
    execution = guarded_exec_argv(logical)
    monitor_request = start_epic_launch_monitor_request(
        tmp_path,
        agent_meta={"name": "planner", "agent_family": "planner"},
        plan=plan,
        artifacts=artifacts,
        cl_name="demo",
    )
    lease = fake_lease(tmp_path)
    task = SimpleNamespace(task_id="k7m2xyz", kind="command", session_id=None)
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[]),
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            return_value=lease,
        ),
        patch("sase.workspace_provider.lease.release_operational_lease"),
        patch(
            "sase.workspace_provider.lease.submit_via_lease",
            return_value=task,
        ) as submit_via_lease,
    ):
        start_epic_launch_monitor(
            plan,
            project="sase",
            artifacts_dir=artifacts,
            cl_name="demo",
            origin="telegram",
        )
    fallback_request = submit_via_lease.call_args.args[0]
    assert list(monitor_request.execution_argv) == execution
    assert shlex.split(monitor_request.command) == logical
    assert list(fallback_request.argv) == execution
    assert list(fallback_request.command) == logical
