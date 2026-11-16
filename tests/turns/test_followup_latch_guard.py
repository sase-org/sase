"""Follow-up fallbacks must not swallow a hijack latch refusal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.hijack import ledger
from sase.agent.hijack.spawn_guard import (
    HijackLatchedError,
    latch_guard_from_predecessor,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.running_field import ClaimResult, WorkspaceClaimError
from sase.turns.followup import (
    FollowupLaunchResult,
    TurnFollowupWorkspace,
    launch_turn_followup,
)
from sase.workspace_provider._hookspec import WorkflowMetadata
from tests._workspace_provider_helpers import _patch_workflow_metadata


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


@pytest.fixture
def gh_git_workflows(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_workflow_metadata(monkeypatch, _gh_git_metadata)


@pytest.fixture
def latch_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ledger, "_hijack_ledger_root", lambda: tmp_path / "ledger")
    monkeypatch.setattr(ledger, "agent_hijack_wire_schema_version", lambda: 1)
    return tmp_path / "ledger"


def _workspace_messages() -> TurnFollowupWorkspace:
    return TurnFollowupWorkspace(
        meta_pairing_reason=lambda original, primary: (
            f"unpaired {original} -> {primary}"
        ),
        fresh_claim_reason=lambda num, error: f"fresh #{num}: {error}",
        pool_claim_reason=lambda num, error, pool_num, pool_dir: (
            f"pool from #{num} to #{pool_num} ({pool_dir}): {error}"
        ),
        workspace_zero_reason=lambda num, error, directory: (
            f"zero from #{num} ({directory}): {error}"
        ),
    )


def _guard(tmp_path: Path, *, state: str = "latched") -> Any:
    artifacts = tmp_path / "pred"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent.1",
                "agent_session": "session-1",
                "project_file": "/tmp/sample.sase",
            }
        ),
        encoding="utf-8",
    )
    target_key = ledger.target_key_for("/tmp/sample.sase", "session-1")
    record = ledger.new_requested_record(
        hijack_id="hijack-1",
        agent_name="agent.1",
        artifacts_dir=str(artifacts),
        session="session-1",
        project_file="/tmp/sample.sase",
        target_key=target_key,
    )
    record["state"] = state
    record["latched_at"] = 1
    ledger.create_record(record)
    return latch_guard_from_predecessor(
        project_file="/tmp/sample.sase",
        session_or_agent="session-1",
        artifacts_dir=str(artifacts),
        member="agent.1",
    )


def _record_launched(
    name: str | None,
    *,
    degraded_reason: str | None = None,
    artifacts_dir: str | None = None,
    pid: int | None = None,
) -> FollowupLaunchResult:
    return FollowupLaunchResult(
        launched=True,
        agent_name=name,
        degraded_reason=degraded_reason,
        artifacts_dir=artifacts_dir,
        pid=pid,
    )


def _record_not_launchable(error: str, prompt: str) -> FollowupLaunchResult:
    return FollowupLaunchResult(launched=False, error=error, prompt_path=None)


def test_latched_followup_does_not_spawn_or_fall_back(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latch_store
    calls: list[int] = []

    def spawn(
        prompt: str,
        workspace_dir: str,
        workspace_num: int,
        transfer_pid: int | None,
        vcs_ref: tuple[str, str] | None,
    ) -> AgentLaunchResult:
        del prompt, workspace_dir, transfer_pid, vcs_ref
        calls.append(workspace_num)
        raise AssertionError("latched follow-up must not spawn")

    monkeypatch.setattr(
        "sase.turns.followup_launch._workspace_is_claimed",
        lambda project_name, workspace_num: True,
    )
    with pytest.raises(HijackLatchedError, match="pending"):
        launch_turn_followup(
            project_name="proj",
            meta_workspace_num=3,
            meta_workspace_dir=str(tmp_path / "ws3"),
            transfer_from_pid=42,
            compose_prompt=lambda _reason: "continue",
            spawn=spawn,
            workspace=_workspace_messages(),
            record_launched=_record_launched,
            record_not_launchable=_record_not_launchable,
            latch_guard=_guard(tmp_path),
        )
    assert calls == []


def test_spawn_latched_error_is_not_turned_into_fresh_or_zero_fallback(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latch_store
    artifacts = tmp_path / "pred"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    guard = latch_guard_from_predecessor(
        project_file="/tmp/sample.sase",
        session_or_agent="session-1",
        artifacts_dir=str(artifacts),
        member="agent.1",
    )
    calls: list[int] = []

    def spawn(
        prompt: str,
        workspace_dir: str,
        workspace_num: int,
        transfer_pid: int | None,
        vcs_ref: tuple[str, str] | None,
    ) -> AgentLaunchResult:
        del prompt, workspace_dir, transfer_pid, vcs_ref
        calls.append(workspace_num)
        raise HijackLatchedError(
            "hijack latch hijack-1 is pending; successor launch refused",
            hijack_id="hijack-1",
            verdict="pending",
        )

    monkeypatch.setattr(
        "sase.turns.followup_launch._workspace_is_claimed",
        lambda project_name, workspace_num: True,
    )
    with pytest.raises(HijackLatchedError, match="pending"):
        launch_turn_followup(
            project_name="proj",
            meta_workspace_num=3,
            meta_workspace_dir=str(tmp_path / "ws3"),
            transfer_from_pid=42,
            compose_prompt=lambda _reason: "continue",
            spawn=spawn,
            workspace=_workspace_messages(),
            record_launched=_record_launched,
            record_not_launchable=_record_not_launchable,
            latch_guard=guard,
        )
    assert calls == [3]


def test_pool_workspace_is_released_when_spawn_raises_latched(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gh_git_workflows: None,
) -> None:
    del latch_store, gh_git_workflows
    artifacts = tmp_path / "pred"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    guard = latch_guard_from_predecessor(
        project_file="/tmp/sample.sase",
        session_or_agent="session-1",
        artifacts_dir=str(artifacts),
        member="agent.1",
    )
    pool = tmp_path / "pool11"
    pool.mkdir()
    released: list[int] = []
    calls: list[int] = []

    monkeypatch.setattr(
        "sase.turns.followup_launch._workspace_is_claimed",
        lambda project_name, workspace_num: True,
    )
    monkeypatch.setattr(
        "sase.turns.followup_launch.get_project_file_path",
        lambda _name: "/tmp/proj.sase",
    )
    monkeypatch.setattr(
        "sase.turns.followup_launch.claim_next_axe_workspace_dir",
        lambda *_args, **_kwargs: (11, str(pool), "proj_11"),
    )

    def release(
        project_file: str,
        workspace_num: int,
        workflow: str | None = None,
        caller_tag: str | None = None,
        **_kwargs: Any,
    ) -> ClaimResult:
        del project_file, workflow, caller_tag
        released.append(workspace_num)
        return ClaimResult(success=True)

    monkeypatch.setattr("sase.turns.followup_launch.release_workspace", release)

    def spawn(
        prompt: str,
        workspace_dir: str,
        workspace_num: int,
        transfer_pid: int | None,
        vcs_ref: tuple[str, str] | None,
    ) -> AgentLaunchResult:
        del prompt, workspace_dir, transfer_pid, vcs_ref
        calls.append(workspace_num)
        if workspace_num != 11:
            raise WorkspaceClaimError(
                f"workspace #{workspace_num} is already claimed",
                workspace_num=workspace_num,
            )
        raise HijackLatchedError(
            "hijack latch hijack-1 is pending; successor launch refused",
            hijack_id="hijack-1",
            verdict="pending",
        )

    with pytest.raises(HijackLatchedError, match="pending"):
        launch_turn_followup(
            project_name="proj",
            meta_workspace_num=3,
            meta_workspace_dir=str(tmp_path / "ws3"),
            transfer_from_pid=42,
            compose_prompt=lambda _reason: "#gh:sase continue",
            spawn=spawn,
            workspace=_workspace_messages(),
            record_launched=_record_launched,
            record_not_launchable=_record_not_launchable,
            recorded_vcs_ref=("gh", "sase"),
            latch_guard=guard,
        )
    assert calls == [3, 3, 11]
    assert released == [11]


def test_ordinary_followup_without_latch_guard_still_launches(tmp_path: Path) -> None:
    result = launch_turn_followup(
        project_name="proj",
        meta_workspace_num=4,
        meta_workspace_dir=str(tmp_path / "ws4"),
        transfer_from_pid=99,
        compose_prompt=lambda _reason: "continue",
        spawn=lambda prompt, workspace_dir, workspace_num, transfer_pid, vcs_ref: (
            AgentLaunchResult(
                pid=1,
                workspace_num=workspace_num,
                workspace_dir=workspace_dir,
                output_path="/tmp/out",
                artifacts_dir=str(tmp_path / "child"),
                agent_name="acme--1",
            )
        ),
        workspace=_workspace_messages(),
        record_launched=_record_launched,
        record_not_launchable=_record_not_launchable,
    )
    assert result.launched is True
    assert result.pid == 1
