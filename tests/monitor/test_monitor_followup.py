"""Tests for :mod:`sase.monitor.followup`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import sase.monitor.followup as followup_module
import sase.monitor.spawn as spawn_module
from sase.agent.launch_types import AgentLaunchResult
from sase.core.artifact_file_facade import list_explicit_artifact_files
from sase.monitor.output import OutputCapture
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.monitor.transaction import monitor_started_path, write_json_marker_atomic
from sase.running_field import WorkspaceClaim, WorkspaceClaimError

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
        artifacts_dir = argv[argv.index("--artifacts-dir") + 1]
        pass_fds = kwargs["pass_fds"]
        assert isinstance(pass_fds, tuple)
        pid_fd = pass_fds[0]
        assert isinstance(pid_fd, int)
        os.write(pid_fd, json.dumps({"pid": _FakeSupervisorPid.pid}).encode() + b"\n")
        # A real supervisor acknowledges startup almost immediately; simulate
        # that here so `start_monitor`'s ack wait does not block on (or time
        # out against) this fixture's pid, which names no real process.
        write_json_marker_atomic(
            monitor_started_path(artifacts_dir),
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
        lane="acme",
        next_action="Report that it finished.",
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

    assert result.launched is False


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

    assert result.launched is True
    assert meta["monitor_followup_agent"] == "acme--1"
    assert "monitor_followup_error" not in meta

    assert captured["workspace_dir"] == str(tmp_path)
    assert captured["workspace_num"] == 3
    assert captured["retry_transfer_from_pid"] == os.getpid()
    # The starter's routing (set by `make_starter_agent()` above) is carried
    # onto the follow-up as %model:/%effort: prefix directives.
    assert captured["prompt"].startswith(
        "#fork:acme--0\n%model:claude-sonnet-5\n%effort:high\n\n"
    )

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


def test_launch_followup_agent_repairs_a_meta_workspace_num_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """meta["workspace_num"] can still read ``0`` while the monitor's cwd is a
    numbered directory (the monitor-claim defect this epic tracks separately);
    the follow-up must repair the pair via the registry lookup instead of
    defaulting to ``0`` and squatting in the numbered directory unclaimed."""
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta["workspace_num"] = 0
    capture = _capture_with_output(monitor_dir, "hello world\n")

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    monkeypatch.setattr(
        followup_module,
        "_workspace_dir_for_num",
        lambda project_name, workspace_num: str(tmp_path / "primary"),
    )
    monkeypatch.setattr(
        followup_module,
        "resolve_consistent_workspace_pair",
        lambda primary_dir, workspace_dir, workspace_num: (workspace_dir, 3),
    )

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

    assert result.launched is True
    assert result.degraded_reason is None
    # Repaired to the real number the directory maps to -- never 0 paired
    # with the numbered directory.
    assert captured["workspace_dir"] == str(tmp_path)
    assert captured["workspace_num"] == 3


def test_launch_followup_agent_falls_back_to_primary_when_meta_pairing_is_unresolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta["workspace_num"] = 0
    capture = _capture_with_output(monitor_dir, "hello world\n")
    primary = tmp_path / "primary"
    primary.mkdir()

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result(workspace_num=0, workspace_dir=str(primary))

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    monkeypatch.setattr(
        followup_module,
        "_workspace_dir_for_num",
        lambda project_name, workspace_num: str(primary),
    )
    monkeypatch.setattr(
        followup_module,
        "resolve_consistent_workspace_pair",
        lambda primary_dir, workspace_dir, workspace_num: None,
    )

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

    assert result.launched is True
    assert result.degraded_reason is not None
    assert "workspace #0" in result.degraded_reason
    assert str(primary) in result.degraded_reason
    # Never squats in the numbered directory with a 0 claim: both the spawn
    # call and the prompt name the primary checkout.
    assert captured["workspace_dir"] == str(primary)
    assert captured["workspace_num"] == 0
    assert "## Follow-up workspace" in captured["prompt"]
    assert str(primary) in captured["prompt"]


def test_launch_followup_agent_falls_back_to_fresh_claim_after_transfer_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    capture = _capture_with_output(monitor_dir, "hello world\n")
    calls: list[dict[str, Any]] = []

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        calls.append(kwargs)
        if len(calls) == 1:
            raise WorkspaceClaimError(
                "workspace #3 with pid 4242424 was not found",
                workspace_num=3,
            )
        return _fake_result(agent_name="acme--1")

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
        transfer_from_pid=4_242_424,
    )

    assert result.launched is True
    assert result.degraded_reason is not None
    assert "fresh claim on the same workspace" in result.degraded_reason
    assert len(calls) == 2
    assert calls[0]["retry_transfer_from_pid"] == 4_242_424
    assert calls[1]["retry_transfer_from_pid"] is None
    assert calls[1]["workspace_num"] == 3
    assert "## Follow-up workspace" in calls[1]["prompt"]
    assert "fresh claim on the same workspace" in calls[1]["prompt"]
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["monitor_followup_degraded_reason"] == result.degraded_reason


def test_launch_followup_agent_falls_back_to_workspace_zero_when_workspace_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    capture = _capture_with_output(monitor_dir, "hello world\n")
    primary = tmp_path / "primary"
    primary.mkdir()
    calls: list[dict[str, Any]] = []

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        calls.append(kwargs)
        if len(calls) < 3:
            raise WorkspaceClaimError(
                "workspace #3 is already claimed",
                workspace_num=3,
            )
        return _fake_result(
            agent_name="acme--1",
            workspace_num=kwargs["workspace_num"],
            workspace_dir=kwargs["workspace_dir"],
        )

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    monkeypatch.setattr(
        followup_module,
        "_workspace_dir_for_num",
        lambda project_name, workspace_num: str(primary),
    )

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
        transfer_from_pid=4_242_424,
    )

    assert result.launched is True
    assert result.degraded_reason is not None
    assert "workspace #0" in result.degraded_reason
    assert [call["workspace_num"] for call in calls] == [3, 3, 0]
    assert calls[2]["workspace_dir"] == str(primary)
    assert calls[2]["retry_transfer_from_pid"] is None
    assert "workspace #0" in calls[2]["prompt"]
    assert "Do not assume" in calls[2]["prompt"]
    env = calls[2]["extra_env"]
    plan = json.loads(env["SASE_AGENT_FAMILY_ATTACH"])
    assert plan["parent_workspace_num"] == 0
    assert plan["parent_workspace_dir"] == str(primary)


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

    assert result.launched is True
    assert "#fork:" not in captured["prompt"]
    # No #fork prefix, but the starter's routing still carries over.
    assert captured["prompt"].startswith("%model:claude-sonnet-5\n%effort:high\n\n")
    assert "# Monitored command finished" in captured["prompt"]


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

    assert result.launched is False
    assert meta["monitor_followup_error"]
    assert "follow-up prompt saved to" in meta["monitor_followup_error"]
    prompt_path = Path(result.prompt_path or "")
    assert prompt_path.name == "monitor_followup_prompt.md"
    persisted_prompt = prompt_path.read_text(encoding="utf-8")
    assert "Report that it finished." in persisted_prompt
    assert persisted_prompt.endswith("%xprompts_enabled:true")
    artifacts = list_explicit_artifact_files(Path(monitor_dir))
    assert [artifact.label for artifact in artifacts] == [
        "Unlaunched monitor follow-up prompt"
    ]
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["monitor_followup_error"] == meta["monitor_followup_error"]
    assert on_disk["monitor_followup_prompt_path"] == str(prompt_path)
