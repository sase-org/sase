"""Launch behavior tests for :mod:`sase.monitor.followup`."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

import sase.monitor.followup as followup_module
from sase.agent.launch_types import AgentLaunchResult
from sase.core.artifact_file_facade import list_explicit_artifact_files
from sase.llm_provider.continuation_budget import MONITOR_CONTINUATION_ENV

from ._fixtures import write_project_file
from ._followup_fixtures import (
    _SETTLE_TIMEOUT,
    _capture_with_output,
    _fake_result,
    _promote_and_start_monitor,
    _sandbox_home as _sandbox_home,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_workspace(workspace: Path, *, dirty: bool) -> None:
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Test User")
    (workspace / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    _git(workspace, "commit", "-m", "init")
    if dirty:
        (workspace / "tracked.txt").write_text("dirty tracked\n", encoding="utf-8")
        (workspace / "untracked.txt").write_text("dirty untracked\n", encoding="utf-8")


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
    assert env[MONITOR_CONTINUATION_ENV] == "1"
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


def test_launch_followup_agent_uses_explicit_next_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch, next_model="@small"
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert meta["monitor_next_model"] == "@small"
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
    assert captured["prompt"].startswith("#fork:acme--0\n%model:@small\n\n")
    assert "%effort:high" not in captured["prompt"]
    assert "%model:claude-sonnet-5" not in captured["prompt"]


def test_launch_followup_agent_reauthors_auto_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta.update(
        {
            "approve": True,
            "auto_approve_plan_action": "tale",
            "auto_approve_argument": "tale",
            "stopped_at": "2026-08-12T14:19:48+00:00",
        }
    )
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
    assert captured["prompt"].startswith(
        "%auto:tale\n#fork:acme--0\n%model:claude-sonnet-5\n%effort:high\n\n"
    )


def test_launch_followup_agent_omits_auto_prefix_without_auto_state(
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
    assert "%auto" not in captured["prompt"]


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
    workspace = tmp_path / "workspace"
    _init_git_workspace(workspace, dirty=True)
    monitor_dir = str(tmp_path / "monitor-member")
    Path(monitor_dir).mkdir()
    meta: dict[str, Any] = {
        "agent_family": "acme",
        "monitor_next_action": "Report that it finished.",
        "monitor_command": "true",
        "monitor_cwd": str(workspace),
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
    assert "Worktree recovery diff" in persisted_prompt
    assert persisted_prompt.endswith("%xprompts_enabled:true")
    snapshot_path = Path(meta["monitor_worktree_recovery_diff_path"])
    snapshot = snapshot_path.read_text(encoding="utf-8")
    assert "dirty tracked" in snapshot
    assert "dirty untracked" in snapshot
    assert str(snapshot_path) in persisted_prompt
    artifacts = list_explicit_artifact_files(Path(monitor_dir))
    assert [artifact.label for artifact in artifacts] == [
        "Unlaunched monitor follow-up prompt"
    ]
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["monitor_followup_error"] == meta["monitor_followup_error"]
    assert on_disk["monitor_followup_prompt_path"] == str(prompt_path)
    assert on_disk["monitor_worktree_recovery_diff_path"] == str(snapshot_path)


def test_launch_followup_agent_skips_recovery_snapshot_for_clean_tree(
    tmp_path: Path,
) -> None:
    write_project_file("proj")
    workspace = tmp_path / "workspace"
    _init_git_workspace(workspace, dirty=False)
    monitor_dir = str(tmp_path / "monitor-member")
    Path(monitor_dir).mkdir()
    meta: dict[str, Any] = {
        "agent_family": "acme",
        "monitor_next_action": "Report that it finished.",
        "monitor_command": "true",
        "monitor_cwd": str(workspace),
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
    assert "monitor_worktree_recovery_diff_path" not in meta
    assert not (Path(monitor_dir) / "diagnostics/worktree_recovery.diff").exists()
