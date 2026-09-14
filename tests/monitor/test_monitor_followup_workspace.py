"""Workspace repair and fallback tests for :mod:`sase.monitor.followup`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sase.monitor.followup as followup_module
import sase.shells.followup as shells_followup_module
import sase.workspace_provider.store as workspace_store_module
from sase.agent.launch_types import AgentLaunchResult
from sase.running_field import WorkspaceClaimError

from ._fixtures import register_workspace_checkout
from ._followup_fixtures import (
    _SETTLE_TIMEOUT,
    _capture_with_output,
    _fake_result,
    _promote_and_start_monitor,
    _sandbox_home as _sandbox_home,
)


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
        shells_followup_module,
        "_workspace_dir_for_num",
        lambda project_name, workspace_num: str(tmp_path / "primary"),
    )
    monkeypatch.setattr(
        shells_followup_module,
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


def test_launch_followup_agent_repairs_a_nested_managed_dir_to_its_owning_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A monitor cwd nested inside a managed checkout -- not just the
    checkout root -- must repair via the real registry containment lookup
    to that checkout's workspace instead of degrading to workspace #0 (plan
    ``202609/monitor_nested_cwd_workspace_resolution.md``)."""
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    # ``_promote_and_start_monitor`` patches the global ``subprocess.Popen``
    # to a supervisor-argv-only fake; keep the real workspace-registry
    # lookups below from tripping it via their own ``git remote -v`` probe.
    monkeypatch.setattr(
        workspace_store_module, "_list_git_remote_urls", lambda primary_dir: []
    )
    primary = tmp_path / "primary"
    primary.mkdir()
    workspace_dir = register_workspace_checkout(primary, 7)
    nested = Path(workspace_dir) / "sase" / "repos" / "external" / "gh" / "x"
    nested.mkdir(parents=True)

    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta["workspace_num"] = 0
    meta["workspace_dir"] = str(nested)
    capture = _capture_with_output(monitor_dir, "hello world\n")

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result(workspace_num=7, workspace_dir=workspace_dir)

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)
    monkeypatch.setattr(
        shells_followup_module,
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
    )

    assert result.launched is True
    assert result.degraded_reason is None
    # Repaired to the checkout root that owns the nested dir -- never left
    # squatting in the nested dir itself or degraded to #0.
    assert captured["workspace_dir"] == workspace_dir
    assert captured["workspace_num"] == 7


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
        shells_followup_module,
        "_workspace_dir_for_num",
        lambda project_name, workspace_num: str(primary),
    )
    monkeypatch.setattr(
        shells_followup_module,
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
        shells_followup_module,
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
