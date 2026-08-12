"""Tests for :mod:`sase.monitor.followup`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import sase.monitor.followup as followup_module
import sase.monitor.start as start_module
from sase.agent.launch_types import AgentLaunchResult
from sase.monitor.output import OutputCapture
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, write_project_file

_SETTLE_TIMEOUT = 2.0


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


class _FakeSupervisorPid:
    pid = 4242424


def _promote_and_start_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    settle_starter: bool = True,
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
    monkeypatch.setattr(
        start_module.subprocess, "Popen", lambda *a, **k: _FakeSupervisorPid()
    )
    request = StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
        next_action="Report that it finished.",
    )
    record = start_monitor(request)
    if settle_starter:
        (Path(starter_dir) / "done.json").write_text("{}", encoding="utf-8")
    return record.artifacts_dir, starter_dir, project_file


def _capture_with_output(monitor_dir: str, text: str) -> OutputCapture:
    capture = OutputCapture(str(Path(monitor_dir) / "live_reply.md"))
    capture.append(text)
    capture.close()
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


def test_launch_followup_agent_returns_false_without_a_next_action(
    tmp_path: Path,
) -> None:
    meta: dict[str, Any] = {"agent_family": "acme"}
    capture = _capture_with_output(str(tmp_path), "hi\n")

    result = followup_module.launch_followup_agent(
        str(tmp_path),
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        capture=capture,
        project_name="proj",
    )

    assert result is False


def test_launch_followup_agent_attaches_to_the_lane_and_transfers_the_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta["stopped_at"] = "2026-08-12T14:19:48+00:00"
    capture = _capture_with_output(monitor_dir, "hello world\n")

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result is True
    assert meta["monitor_followup_agent"] == "acme--1"
    assert "monitor_followup_error" not in meta

    assert captured["workspace_dir"] == str(tmp_path)
    assert captured["workspace_num"] == 3
    assert captured["retry_transfer_from_pid"] == os.getpid()
    assert captured["prompt"].startswith("#fork:acme--0\n\n")

    env = captured["extra_env"]
    assert env["SASE_INTERNAL_AGENT_NAME_BYPASS"] == "1"
    plan = json.loads(env["SASE_AGENT_FAMILY_ATTACH"])
    assert plan["agent_name"] == "acme--1"
    assert plan["parent_base"] == "acme"
    # The starter's own role ("root") is inherited rather than the generic
    # numeric-suffix default ("feedback").
    assert plan["agent_family_role"] == "root"
    assert plan["parent_is_running"] is False

    # Persisted to disk too, not just the in-memory dict.
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["monitor_followup_agent"] == "acme--1"


def test_launch_followup_agent_omits_the_fork_prefix_when_the_starter_never_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch, settle_starter=False
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    capture = _capture_with_output(monitor_dir, "hello\n")

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        followup_module,
        "spawn_agent_subprocess",
        lambda **kwargs: (captured.update(kwargs), _fake_result())[1],
    )

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=0.2,
    )

    assert result is True
    assert "#fork:" not in captured["prompt"]
    assert captured["prompt"].startswith("# Monitored command finished")


def test_launch_followup_agent_records_the_error_and_returns_false_on_failure(
    tmp_path: Path,
) -> None:
    # No promotion, no real family in the artifact index: resolution fails.
    write_project_file("proj")
    monitor_dir = str(tmp_path / "monitor-member")
    Path(monitor_dir).mkdir()
    meta: dict[str, Any] = {
        "agent_family": "acme",
        "monitor_next_action": "Report that it finished.",
        "monitor_command": "true",
        "monitor_id": "abc123def456",
    }
    (Path(monitor_dir) / "agent_meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )
    capture = _capture_with_output(monitor_dir, "hi\n")

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=0.2,
    )

    assert result is False
    assert meta["monitor_followup_error"]
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["monitor_followup_error"] == meta["monitor_followup_error"]
