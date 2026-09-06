"""Pre-allocation of VCS workspace env across shell follow-up launches."""

from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.launch_spawn import _preallocated_workspace_env
from sase.agent.launch_types import AgentLaunchResult
from sase.gate_shell.followup import launch_gate_followup_agent
from sase.gate_shell.followup_policy import GateFollowupPolicy
from sase.running_field import WorkspaceClaimError
from sase.shells.followup import (
    FollowupLaunchResult,
    ShellFollowupWorkspace,
    _resolve_shell_followup_vcs_ref,
    _vcs_ref_from_prompt,
    launch_shell_followup,
    vcs_ref_from_meta,
)
from sase.workspace_provider import reset_workflow_metadata_caches
from sase.workspace_provider._hookspec import WorkflowMetadata
from tests.gate_shell.test_followup_launch import (
    _SETTLE_TIMEOUT,
    _envelope,
    _fake_result,
    _make_member,
    _response,
)
from tests.monitor._fixtures import write_project_file


def _gh_git_metadata() -> tuple[WorkflowMetadata, ...]:
    return (
        WorkflowMetadata(
            workflow_type="gh",
            ref_pattern=r"(?:^|(?<=\s))#gh(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="GitHub",
            pre_allocated_env_prefix="SASE_GH",
        ),
        WorkflowMetadata(
            workflow_type="git",
            ref_pattern=r"(?:^|(?<=\s))#git(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="Git",
            pre_allocated_env_prefix="SASE_GIT",
        ),
    )


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


@pytest.fixture
def gh_git_workflows(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    import sase.workspace_provider as workspace_provider
    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _gh_git_metadata)
    monkeypatch.setattr(
        workspace_provider, "get_all_workflow_metadata", _gh_git_metadata
    )
    reset_workflow_metadata_caches()
    yield
    reset_workflow_metadata_caches()


def _workspace_messages() -> ShellFollowupWorkspace:
    return ShellFollowupWorkspace(
        meta_pairing_reason=lambda original, primary: (
            f"unpaired {original} -> {primary}"
        ),
        fresh_claim_reason=lambda num, error: f"fresh #{num}: {error}",
        workspace_zero_reason=lambda num, error, directory: (
            f"zero from #{num} ({directory}): {error}"
        ),
    )


def test_vcs_ref_from_meta_accepts_launcher_tuple_shape() -> None:
    assert vcs_ref_from_meta({"vcs_ref": ["gh", "sase"]}) == ("gh", "sase")
    assert vcs_ref_from_meta({"vcs_ref": ("git", "home")}) == ("git", "home")
    assert vcs_ref_from_meta({"vcs_ref": ["gh"]}) is None
    assert vcs_ref_from_meta({"vcs_ref": "gh:sase"}) is None
    assert vcs_ref_from_meta({}) is None


def test_vcs_ref_from_prompt_uses_embedded_registry_pattern(
    gh_git_workflows: None,
) -> None:
    del gh_git_workflows
    assert _vcs_ref_from_prompt("#fork:acme\n#gh:sase continue") == ("gh", "sase")
    assert _vcs_ref_from_prompt("do work") is None


def test_resolve_prefers_recorded_ref_when_workflow_matches(
    gh_git_workflows: None,
) -> None:
    del gh_git_workflows
    assert _resolve_shell_followup_vcs_ref(
        ("gh", "canonical"),
        "#gh:sase continue",
    ) == ("gh", "canonical")
    assert _resolve_shell_followup_vcs_ref(None, "#gh:sase continue") == ("gh", "sase")
    assert _resolve_shell_followup_vcs_ref(("gh", "sase"), "no vcs tag") is None


def test_launch_shell_followup_forwards_resolved_vcs_ref(
    tmp_path: Path, gh_git_workflows: None
) -> None:
    del gh_git_workflows
    captured: dict[str, Any] = {}

    def spawn(
        prompt: str,
        workspace_dir: str,
        workspace_num: int,
        transfer_pid: int | None,
        vcs_ref: tuple[str, str] | None,
    ) -> AgentLaunchResult:
        captured.update(
            {
                "prompt": prompt,
                "workspace_dir": workspace_dir,
                "workspace_num": workspace_num,
                "transfer_pid": transfer_pid,
                "vcs_ref": vcs_ref,
            }
        )
        return AgentLaunchResult(
            pid=1,
            workspace_num=workspace_num,
            workspace_dir=workspace_dir,
            output_path="/tmp/out",
            artifacts_dir=str(tmp_path / "child-artifacts"),
            agent_name="acme--1",
        )

    result = launch_shell_followup(
        project_name="proj",
        meta_workspace_num=4,
        meta_workspace_dir=str(tmp_path / "ws4"),
        transfer_from_pid=99,
        compose_prompt=lambda _reason: "#gh:sase continue",
        spawn=spawn,
        workspace=_workspace_messages(),
        record_launched=lambda name, *, degraded_reason=None, artifacts_dir=None, pid=None: (
            FollowupLaunchResult(
                launched=True,
                agent_name=name,
                degraded_reason=degraded_reason,
                artifacts_dir=artifacts_dir,
                pid=pid,
            )
        ),
        record_not_launchable=lambda error, prompt: FollowupLaunchResult(
            launched=False, error=error, prompt_path=None
        ),
        recorded_vcs_ref=("gh", "sase"),
    )

    assert result.launched is True
    assert result.artifacts_dir == str(tmp_path / "child-artifacts")
    assert result.pid == 1
    assert captured["vcs_ref"] == ("gh", "sase")
    env = _preallocated_workspace_env(
        captured["vcs_ref"],
        workspace_num=captured["workspace_num"],
        workspace_dir=captured["workspace_dir"],
    )
    assert env == {
        "SASE_GH_PRE_ALLOCATED": "1",
        "SASE_GH_WORKSPACE_NUM": "4",
        "SASE_GH_WORKSPACE_DIR": str(tmp_path / "ws4"),
    }


def test_launch_shell_followup_zero_fallback_advertises_workspace_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gh_git_workflows: None
) -> None:
    del gh_git_workflows
    write_project_file("proj")
    primary = tmp_path / "primary"
    primary.mkdir()
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "sase.shells.followup._workspace_dir_for_num",
        lambda project_name, workspace_num: str(primary),
    )
    monkeypatch.setattr(
        "sase.shells.followup._workspace_is_claimed",
        lambda project_name, workspace_num: True,
    )

    def spawn_zero_ok(
        prompt: str,
        workspace_dir: str,
        workspace_num: int,
        transfer_pid: int | None,
        vcs_ref: tuple[str, str] | None,
    ) -> AgentLaunchResult:
        calls.append(
            {
                "prompt": prompt,
                "workspace_dir": workspace_dir,
                "workspace_num": workspace_num,
                "transfer_pid": transfer_pid,
                "vcs_ref": vcs_ref,
            }
        )
        if workspace_num != 0:
            raise WorkspaceClaimError(
                f"workspace #{workspace_num} is already claimed",
                workspace_num=workspace_num,
            )
        return AgentLaunchResult(
            pid=1,
            workspace_num=0,
            workspace_dir=workspace_dir,
            output_path="/tmp/out",
            agent_name="acme--1",
        )

    result = launch_shell_followup(
        project_name="proj",
        meta_workspace_num=3,
        meta_workspace_dir=str(tmp_path / "ws3"),
        transfer_from_pid=42,
        compose_prompt=lambda reason: (
            "#gh:sase continue" if reason is None else f"#gh:sase continue\n{reason}"
        ),
        spawn=spawn_zero_ok,
        workspace=_workspace_messages(),
        record_launched=lambda name, *, degraded_reason=None, artifacts_dir=None, pid=None: (
            FollowupLaunchResult(
                launched=True,
                agent_name=name,
                degraded_reason=degraded_reason,
                artifacts_dir=artifacts_dir,
                pid=pid,
            )
        ),
        record_not_launchable=lambda error, prompt: FollowupLaunchResult(
            launched=False, error=error, prompt_path=None
        ),
        recorded_vcs_ref=("gh", "sase"),
    )

    assert result.launched is True
    assert result.pid == 1
    assert [call["workspace_num"] for call in calls] == [3, 3, 0]
    zero = calls[-1]
    assert zero["vcs_ref"] == ("gh", "sase")
    env = _preallocated_workspace_env(
        zero["vcs_ref"],
        workspace_num=zero["workspace_num"],
        workspace_dir=zero["workspace_dir"],
    )
    assert env["SASE_GH_PRE_ALLOCATED"] == "1"
    assert env["SASE_GH_WORKSPACE_NUM"] == "0"
    assert env["SASE_GH_WORKSPACE_DIR"] == str(primary)


def test_launch_shell_followup_without_vcs_sets_no_preallocation_env(
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def spawn(
        prompt: str,
        workspace_dir: str,
        workspace_num: int,
        transfer_pid: int | None,
        vcs_ref: tuple[str, str] | None,
    ) -> AgentLaunchResult:
        captured["vcs_ref"] = vcs_ref
        captured["workspace_num"] = workspace_num
        captured["workspace_dir"] = workspace_dir
        return AgentLaunchResult(
            pid=1,
            workspace_num=workspace_num,
            workspace_dir=workspace_dir,
            output_path="/tmp/out",
            agent_name="acme--1",
        )

    result = launch_shell_followup(
        project_name="proj",
        meta_workspace_num=3,
        meta_workspace_dir=str(tmp_path / "ws3"),
        transfer_from_pid=None,
        compose_prompt=lambda _reason: "continue without a vcs tag",
        spawn=spawn,
        workspace=_workspace_messages(),
        record_launched=lambda name, *, degraded_reason=None, artifacts_dir=None, pid=None: (
            FollowupLaunchResult(
                launched=True,
                agent_name=name,
                degraded_reason=degraded_reason,
                artifacts_dir=artifacts_dir,
                pid=pid,
            )
        ),
        record_not_launchable=lambda error, prompt: FollowupLaunchResult(
            launched=False, error=error, prompt_path=None
        ),
    )

    assert result.launched is True
    assert result.pid == 1
    assert captured["vcs_ref"] is None
    assert (
        _preallocated_workspace_env(
            captured["vcs_ref"],
            workspace_num=captured["workspace_num"],
            workspace_dir=captured["workspace_dir"],
        )
        == {}
    )


def test_gh_gate_followup_is_spawned_with_preallocation_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gh_git_workflows: None
) -> None:
    del gh_git_workflows
    member_dir, meta = _make_member(tmp_path)
    meta["vcs_ref"] = ["gh", "sase"]
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr("sase.gate_shell.followup.spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        member_dir,
        meta,
        project_name="proj",
        gate_state="answered",
        policy=GateFollowupPolicy(
            branch_key="cleanup",
            prompt="#gh:sase Verify the cleanup landed.",
            output=("results",),
            fork="none",
            model=None,
            raw_prompt=True,
        ),
        envelope=_envelope(),
        response=_response(),
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert captured["prompt"].startswith("#gh:sase ")
    assert captured["vcs_ref"] == ("gh", "sase")
    env = _preallocated_workspace_env(
        captured["vcs_ref"],
        workspace_num=captured["workspace_num"],
        workspace_dir=captured["workspace_dir"],
    )
    assert env["SASE_GH_PRE_ALLOCATED"] == "1"
    assert env["SASE_GH_WORKSPACE_NUM"] == str(captured["workspace_num"])
    assert env["SASE_GH_WORKSPACE_DIR"] == captured["workspace_dir"]


def test_gate_followup_recovers_vcs_ref_from_composed_prompt_without_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gh_git_workflows: None
) -> None:
    del gh_git_workflows
    member_dir, meta = _make_member(tmp_path)
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr("sase.gate_shell.followup.spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        member_dir,
        meta,
        project_name="proj",
        gate_state="answered",
        policy=GateFollowupPolicy(
            branch_key="cleanup",
            prompt="#gh:sase Verify the cleanup landed.",
            output=("results",),
            fork="none",
            model=None,
            raw_prompt=True,
        ),
        envelope=_envelope(),
        response=_response(),
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert captured["vcs_ref"] == ("gh", "sase")


def test_extract_directives_records_starter_vcs_ref(
    tmp_path: Path, gh_git_workflows: None
) -> None:
    del gh_git_workflows
    from tests._agent_names_extract_fixtures import run_extract

    result = run_extract(tmp_path, prompt="#gh:sase do stuff")

    assert result["meta"]["vcs_ref"] == ["gh", "sase"]


def test_monitor_followup_forwards_recorded_vcs_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gh_git_workflows: None
) -> None:
    del gh_git_workflows
    import sase.monitor.followup as monitor_followup
    from tests.monitor.test_monitor_followup import (
        _SETTLE_TIMEOUT as MONITOR_SETTLE,
        _capture_with_output,
        _fake_result as _monitor_fake_result,
        _promote_and_start_monitor,
    )

    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta["vcs_ref"] = ["gh", "sase"]
    meta["monitor_next_action"] = "#gh:sase Report that it finished."
    capture = _capture_with_output(monitor_dir, "hello world\n")
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _monitor_fake_result()

    monkeypatch.setattr(monitor_followup, "spawn_agent_subprocess", fake_spawn)

    result = monitor_followup.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=MONITOR_SETTLE,
    )

    assert result.launched is True
    assert captured["vcs_ref"] == ("gh", "sase")
    env = _preallocated_workspace_env(
        captured["vcs_ref"],
        workspace_num=captured["workspace_num"],
        workspace_dir=captured["workspace_dir"],
    )
    assert env["SASE_GH_PRE_ALLOCATED"] == "1"
    assert env["SASE_GH_WORKSPACE_NUM"] == str(captured["workspace_num"])
    assert env["SASE_GH_WORKSPACE_DIR"] == captured["workspace_dir"]
