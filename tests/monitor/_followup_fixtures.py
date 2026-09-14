"""Shared fixtures for monitor follow-up tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import sase.procs.spawn as spawn_module
from sase.agent.launch_types import AgentLaunchResult
from sase.monitor.output import OutputCapture
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.procs.runtime import proc_started_path, write_json_atomic
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, write_project_file

_SETTLE_TIMEOUT = 2.0


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


class _FakeSupervisorPid:
    pid = 4242424

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0


def _promote_and_start_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    settle_starter: bool = True,
    next_model: str | None = None,
) -> tuple[str, str, str]:
    """Return ``(monitor_dir, starter_dir, project_file)`` from a real promotion.

    Uses the real ``start_monitor()`` so the starter is genuinely promoted to
    a family root and the monitor member inherits real lineage, without
    actually spawning a detached supervisor subprocess.
    """
    project_file = write_project_file(
        "proj", running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())]
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        llm_provider="anthropic",
        reasoning_effort="high",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )

    def fake_popen(*args: object, **kwargs: object) -> _FakeSupervisorPid:
        argv = args[0]
        assert isinstance(argv, list)
        proc_id = argv[argv.index("--proc-id") + 1]
        pass_fds = kwargs["pass_fds"]
        assert isinstance(pass_fds, tuple)
        pid_fd = pass_fds[0]
        assert isinstance(pid_fd, int)
        os.write(pid_fd, json.dumps({"pid": _FakeSupervisorPid.pid}).encode() + b"\n")
        write_json_atomic(
            proc_started_path(proc_id),
            {"pid": _FakeSupervisorPid.pid},
        )
        return _FakeSupervisorPid()

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)
    request = StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        start_status="MONITORING",
        stop_status="MONITORED",
        lane="acme",
        next_action="Report that it finished.",
        next_model=next_model,
    )
    record = start_monitor(request)
    if settle_starter:
        (Path(starter_dir) / "done.json").write_text("{}", encoding="utf-8")
    return record.artifacts_dir, starter_dir, project_file


def _capture_with_output(monitor_dir: str, text: str) -> OutputCapture:
    del monitor_dir
    capture = OutputCapture()
    capture.append_bytes(text.encode())
    return capture


def _fake_result(**overrides: Any) -> AgentLaunchResult:
    defaults: dict[str, Any] = {
        "pid": 999999,
        "workspace_num": 3,
        "workspace_dir": "/tmp/whatever",
        "output_path": "/tmp/whatever.txt",
        "agent_name": "acme--1",
    }
    defaults.update(overrides)
    return AgentLaunchResult(**defaults)
