"""Tests for :mod:`sase.gate_shell.followup`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sase.gate_shell.followup as followup_module
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_artifact_paths import canonical_agent_artifact_path
from sase.core.artifact_file_facade import list_explicit_artifact_files
from sase.gate_shell.followup import launch_gate_followup_agent
from sase.gate_shell.followup_policy import GateFollowupPolicy

from tests.monitor._fixtures import make_starter_agent, write_project_file

_SETTLE_TIMEOUT = 2.0


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def _fake_result(**overrides: Any) -> AgentLaunchResult:
    defaults: dict[str, Any] = {
        "pid": 999999,
        "workspace_num": 3,
        "workspace_dir": "/tmp/whatever",
        "output_path": "/tmp/whatever.txt",
        "agent_name": "acme--gate--@",
    }
    defaults.update(overrides)
    return AgentLaunchResult(**defaults)


def _policy(
    *, fork: str = "family", output: tuple[str, ...] = ("results",)
) -> GateFollowupPolicy:
    return GateFollowupPolicy(
        branch_key="cleanup",
        prompt="Verify the cleanup landed.",
        output=output,
        fork=fork,
        model=None,
        status=None,
        accent=None,
    )


def _envelope() -> dict[str, Any]:
    return {
        "presentation": {"title": "Reclaim disk space"},
        "gate_timeout_seconds": 3600.0,
        "created_at_unix": 1_800_000_000.0,
        "branches": [["cleanup"]],
        "options": [
            {
                "id": "cleanup",
                "label": "Clean up",
                "command": {"argv": ["commands/cleanup"]},
            }
        ],
        "groups": [],
        "query": "cleanup",
        "primary_branch": ["cleanup"],
    }


def _response() -> dict[str, Any]:
    return {
        "selected_option_ids": ["cleanup"],
        "source": "cli",
        "option_results": [{"id": "cleanup", "result": {"status": "cleaned"}}],
        "responded_at_unix": 1_800_003_600.0,
    }


def _make_member(
    tmp_path: Path,
    *,
    project: str = "proj",
    workspace_policy: str = "inherit",
    settle_starter: bool = True,
    creator_pid: int | None = 4_242_424,
) -> tuple[str, dict[str, Any]]:
    write_project_file(project)
    creator_timestamp = "20260812120000"
    creator_dir = make_starter_agent(
        project,
        creator_timestamp,
        "acme",
        agent_family="acme",
        agent_family_role="root",
    )
    if settle_starter:
        (Path(creator_dir) / "done.json").write_text("{}", encoding="utf-8")

    member_dir = str(
        canonical_agent_artifact_path(project, "ace-run", "20260812120500")
    )
    Path(member_dir).mkdir(parents=True)
    meta: dict[str, Any] = {
        "name": "acme--gate",
        "agent_family": "acme",
        "agent_family_role": "gate",
        "parent_timestamp": creator_timestamp,
        "model": "gpt-5",
        "workspace_num": 3,
        "workspace_dir": str(tmp_path / "primary"),
        "gate_kind": "custom",
        "gate_id": "reclaim-1",
        "gate_workspace_policy": workspace_policy,
    }
    if creator_pid is not None:
        meta["gate_creator_claim_pid"] = creator_pid
    (Path(member_dir) / "agent_meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )
    return member_dir, meta


def test_fork_family_targets_the_agent_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member_dir, meta = _make_member(tmp_path)
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        member_dir,
        meta,
        project_name="proj",
        gate_state="answered",
        policy=_policy(fork="family"),
        envelope=_envelope(),
        response=_response(),
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert captured["prompt"].startswith("#fork:acme\n%model:gpt-5\n\n")


def test_fork_shell_targets_the_gate_shells_own_member_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member_dir, meta = _make_member(tmp_path)
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        member_dir,
        meta,
        project_name="proj",
        gate_state="answered",
        policy=_policy(fork="shell"),
        envelope=_envelope(),
        response=_response(),
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert captured["prompt"].startswith("#fork:acme--gate\n%model:gpt-5\n\n")


def test_fork_none_omits_the_fork_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member_dir, meta = _make_member(tmp_path)
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        member_dir,
        meta,
        project_name="proj",
        gate_state="answered",
        policy=_policy(fork="none"),
        envelope=_envelope(),
        response=_response(),
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert "#fork:" not in captured["prompt"]


def test_raw_prompt_omits_wrapper_and_inherited_model_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member_dir, meta = _make_member(tmp_path)
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        member_dir,
        meta,
        project_name="proj",
        gate_state="answered",
        policy=GateFollowupPolicy(
            branch_key="cleanup",
            prompt="Verify the cleanup landed.",
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
    assert captured["prompt"] == "Verify the cleanup landed."


def test_fork_prefix_is_dropped_when_the_creator_never_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member_dir, meta = _make_member(tmp_path, settle_starter=False)
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        member_dir,
        meta,
        project_name="proj",
        gate_state="answered",
        policy=_policy(fork="family"),
        envelope=_envelope(),
        response=_response(),
        settle_timeout_seconds=0.2,
    )

    assert result.launched is True
    assert "#fork:" not in captured["prompt"]


def test_inherit_workspace_transfers_from_the_creator_claim_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member_dir, meta = _make_member(
        tmp_path, workspace_policy="inherit", creator_pid=4_242_424
    )
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        member_dir,
        meta,
        project_name="proj",
        gate_state="answered",
        policy=_policy(),
        envelope=_envelope(),
        response=_response(),
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert captured["retry_transfer_from_pid"] == 4_242_424


def test_release_workspace_passes_no_transfer_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member_dir, meta = _make_member(
        tmp_path, workspace_policy="release", creator_pid=4_242_424
    )
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        member_dir,
        meta,
        project_name="proj",
        gate_state="answered",
        policy=_policy(),
        envelope=_envelope(),
        response=_response(),
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    assert captured["retry_transfer_from_pid"] is None


def test_spawn_failure_records_the_error_and_stashes_the_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member_dir, meta = _make_member(tmp_path)

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        member_dir,
        meta,
        project_name="proj",
        gate_state="answered",
        policy=_policy(),
        envelope=_envelope(),
        response=_response(),
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is False
    assert result.error is not None
    assert "boom" in result.error
    assert meta["gate_followup_error"] == result.error
    prompt_path = Path(meta["gate_followup_prompt_path"])
    assert prompt_path.exists()
    assert "Verify the cleanup landed." in prompt_path.read_text(encoding="utf-8")
    labels = {entry.label for entry in list_explicit_artifact_files(Path(member_dir))}
    assert "Unlaunched gate follow-up prompt" in labels


def test_no_lane_returns_not_launched(tmp_path: Path) -> None:
    member_dir, meta = _make_member(tmp_path)
    meta.pop("agent_family")

    result = launch_gate_followup_agent(
        member_dir,
        meta,
        project_name="proj",
        gate_state="answered",
        policy=_policy(),
        envelope=_envelope(),
        response=_response(),
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is False
