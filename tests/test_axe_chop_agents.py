"""Tests for durable chop-launched agent tracking."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launcher import spawn_agent_subprocess
from sase.axe.chop_agents import (
    ENV_CHOP_LUMBERJACK,
    ENV_CHOP_NAME,
    ENV_CHOP_PROMPT_HASH,
    ENV_CHOP_RUN_ID,
    agent_meta_from_chop_env,
    build_chop_launch_env,
    get_chop_agent_records,
)
from sase.linked_repos import LinkedRepoResolution
from sase.running_field import ClaimResult


def _spawn_agent_for_env_test(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_spawn: MagicMock,
    extra_env: dict[str, str] | None = None,
) -> None:
    output_path = tmp_path / "proj_ace-run-260101_120000.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    mock_spawn.side_effect = _fake_spawn_success
    monkeypatch.setattr("sase.core.paths.get_sase_tmpdir", lambda: str(tmp_dir))
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))

    spawn_agent_subprocess(
        cl_name="proj",
        project_file="/tmp/projects/proj/proj.sase",
        workspace_dir=str(workspace_dir),
        workspace_num=3,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
        extra_env=extra_env,
    )


def _fake_spawn_success(
    _prepared: object,
    *,
    env: dict[str, str],
    claim_callback: Callable[[int], bool] | None = None,
) -> int:
    if claim_callback is not None:
        assert callable(claim_callback)
        assert claim_callback(4321) is True
    assert env["SASE_AGENT"] == "1"
    return 4321


def test_build_chop_launch_env() -> None:
    """Both scheduled and one-shot paths can build matching chop env vars."""
    env = build_chop_launch_env(
        lumberjack_name="recurring",
        chop_name="my_agent",
        prompt="Review the repository.",
    )

    assert env[ENV_CHOP_LUMBERJACK] == "recurring"
    assert env[ENV_CHOP_NAME] == "my_agent"
    assert env[ENV_CHOP_RUN_ID]
    assert (
        env[ENV_CHOP_PROMPT_HASH]
        == hashlib.sha256(b"Review the repository.").hexdigest()
    )
    assert "SASE_AGENT_AUTO_DISMISS" not in env


def test_build_chop_launch_env_unique_run_ids() -> None:
    """Each invocation produces a fresh run id."""
    env_a = build_chop_launch_env(lumberjack_name="lj", chop_name="c", prompt="prompt")
    env_b = build_chop_launch_env(lumberjack_name="lj", chop_name="c", prompt="prompt")
    assert env_a[ENV_CHOP_RUN_ID] != env_b[ENV_CHOP_RUN_ID]


def test_agent_meta_from_chop_env() -> None:
    """Chop env vars are represented in agent_meta.json fields."""
    meta = agent_meta_from_chop_env(
        {
            ENV_CHOP_LUMBERJACK: "hooks",
            ENV_CHOP_NAME: "split",
            ENV_CHOP_RUN_ID: "run-1",
        }
    )

    assert meta == {
        "chop_lumberjack": "hooks",
        "chop_name": "split",
        "chop_run_id": "run-1",
    }


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_removes_inherited_sase_codex_home(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detached agents do not inherit a parent SASE Codex shadow home."""
    inherited_shadow = tmp_path / ".cache" / "sase" / "codex_home" / "123-deadbeef"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(inherited_shadow))

    _spawn_agent_for_env_test(
        tmp_path=tmp_path, monkeypatch=monkeypatch, mock_spawn=mock_spawn
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert "CODEX_HOME" not in env


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_preserves_custom_codex_home(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detached agents keep user-managed custom CODEX_HOME values."""
    custom_home = tmp_path / "custom-codex"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(custom_home))

    _spawn_agent_for_env_test(
        tmp_path=tmp_path, monkeypatch=monkeypatch, mock_spawn=mock_spawn
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env["CODEX_HOME"] == str(custom_home)


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_extra_env_codex_home_wins(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit caller CODEX_HOME overrides are applied after sanitization."""
    inherited_shadow = tmp_path / ".cache" / "sase" / "codex_home" / "123-deadbeef"
    explicit_shadow = tmp_path / ".cache" / "sase" / "codex_home" / "explicit"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(inherited_shadow))

    _spawn_agent_for_env_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
        extra_env={"CODEX_HOME": str(explicit_shadow)},
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env["CODEX_HOME"] == str(explicit_shadow)


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_replaces_ambient_agent_identity_with_launch_env(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "poisoned")
    monkeypatch.setenv("SASE_AGENT_NAME", "stale-worker")
    monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", "stale-worker")
    monkeypatch.setenv("SASE_AGENT_AUTO_APPROVE", "1")
    monkeypatch.setenv("SASE_AGENT_CHAT_PATH", "/tmp/stale-chat.jsonl")
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "20260701010101")
    monkeypatch.setenv("SASE_CHOP_NAME", "workflow_checks")

    _spawn_agent_for_env_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
        extra_env={
            "SASE_AGENT_PLANNED_NAME": "current-worker",
            "SASE_AGENT_CHAT_PATH": "/tmp/current-chat.jsonl",
            "SASE_AGENT_RETRY_HANDOFF": "current-handoff",
        },
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env["SASE_AGENT"] == "1"
    assert env["SASE_AGENT_PLANNED_NAME"] == "current-worker"
    assert env["SASE_AGENT_CHAT_PATH"] == "/tmp/current-chat.jsonl"
    assert env["SASE_AGENT_RETRY_HANDOFF"] == "current-handoff"
    assert env["SASE_CHOP_NAME"] == "workflow_checks"
    assert "SASE_AGENT_NAME" not in env
    assert "SASE_AGENT_AUTO_APPROVE" not in env
    assert "SASE_AGENT_ROOT_TIMESTAMP" not in env


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_scopes_model_alias_override_env(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = "SASE_MODEL_ALIAS_OVERRIDES"
    monkeypatch.setenv(key, '{"coder": "sonnet"}')
    inherited_case = tmp_path / "inherited"
    inherited_case.mkdir()

    _spawn_agent_for_env_test(
        tmp_path=inherited_case,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
    )
    assert key not in mock_spawn.call_args.kwargs["env"]

    explicit_case = tmp_path / "explicit"
    explicit_case.mkdir()
    _spawn_agent_for_env_test(
        tmp_path=explicit_case,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
        extra_env={key: '{"coder": "opus"}'},
    )
    assert mock_spawn.call_args.kwargs["env"][key] == '{"coder": "opus"}'


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_records_chop_launch_and_detaches(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Launcher records every agent spawned under SASE_CHOP_* env vars."""
    output_path = tmp_path / "proj_ace-run-260101_120000.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr(
        "sase.axe.state.JACK_STATE_DIR", sase_home / "axe" / "lumberjacks"
    )
    mock_spawn.side_effect = _fake_spawn_success
    monkeypatch.setenv(ENV_CHOP_LUMBERJACK, "hooks")
    monkeypatch.setenv(ENV_CHOP_NAME, "split")
    monkeypatch.setenv(ENV_CHOP_RUN_ID, "run-1")
    monkeypatch.setattr("sase.core.paths.get_sase_tmpdir", lambda: str(tmp_dir))
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))
    monkeypatch.setattr(
        "sase.linked_repos.resolve_linked_repos_for_project",
        lambda **_: LinkedRepoResolution(()),
    )

    result = spawn_agent_subprocess(
        cl_name="proj",
        project_file="/tmp/projects/proj/proj.sase",
        workspace_dir=str(workspace_dir),
        workspace_num=3,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
    )

    assert result.pid == 4321
    assert result.artifacts_dir == str(
        sase_home
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "202601"
        / "01"
        / "20260101120000"
    )
    prepared = mock_spawn.call_args.args[0]
    assert prepared.argv[2:9] == [
        "proj",
        "/tmp/projects/proj/proj.sase",
        str(workspace_dir),
        str(output_path),
        "3",
        "ace(run)-260101_120000",
        prepared.argv[8],
    ]
    assert Path(prepared.argv[8]).read_text() == "do work"
    assert Path(prepared.argv[8]).parent == tmp_dir
    assert mock_spawn.call_args.kwargs["claim_callback"] is not None
    records = get_chop_agent_records("hooks", chop_name="split")
    assert len(records) == 1
    assert records[0].pid == 4321
    assert records[0].project_name == "proj"
    assert records[0].workflow_name == "ace(run)-260101_120000"


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_ignores_post_spawn_chop_record_failure(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chop-registry write failure after spawn does not fail the launch."""
    output_path = tmp_path / "proj_ace-run-260101_120000.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    mock_spawn.side_effect = _fake_spawn_success
    monkeypatch.setenv(ENV_CHOP_LUMBERJACK, "hooks")
    monkeypatch.setenv(ENV_CHOP_NAME, "split")
    monkeypatch.setenv(ENV_CHOP_RUN_ID, "run-1")
    monkeypatch.setattr("sase.core.paths.get_sase_tmpdir", lambda: str(tmp_dir))
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))
    monkeypatch.setattr(
        "sase.linked_repos.resolve_linked_repos_for_project",
        lambda **_: LinkedRepoResolution(()),
    )

    with patch(
        "sase.axe.chop_agents.record_chop_agent_launch_from_env",
        side_effect=OSError("registry busy"),
    ) as record:
        result = spawn_agent_subprocess(
            cl_name="proj",
            project_file="/tmp/projects/proj/proj.sase",
            workspace_dir=str(workspace_dir),
            workspace_num=3,
            workflow_name="ace(run)-260101_120000",
            prompt="do work",
            timestamp="260101_120000",
            project_name="proj",
        )

    assert result.pid == 4321
    record.assert_called_once()


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_prepares_vcs_and_local_xprompt_env(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rust preparation preserves launch env for VCS and local xprompts."""
    output_path = tmp_path / "out.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    xprompts_file = tmp_path / "xprompts.json"
    xprompts_file.write_text("{}")
    mock_spawn.side_effect = _fake_spawn_success
    monkeypatch.setattr("sase.core.paths.get_sase_tmpdir", lambda: str(tmp_dir))
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))
    monkeypatch.setattr(
        "sase.workspace_provider.get_pre_allocated_env_prefix",
        lambda _workflow_type: "GH",
    )

    spawn_agent_subprocess(
        cl_name="feature/test",
        project_file="/tmp/projects/proj/proj.sase",
        workspace_dir=str(workspace_dir),
        workspace_num=8,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
        vcs_ref=("gh", "feature/test"),
        deferred_workspace=True,
        local_xprompts_file=str(xprompts_file),
        extra_env={"SASE_REPEAT_NAME": "task.1"},
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env["SASE_AGENT"] == "1"
    assert env["SASE_AGENT_VCS_WORKFLOW_TYPE"] == "gh"
    assert env["SASE_AGENT_DEFERRED_WORKSPACE"] == "1"
    assert env["GH_PRE_ALLOCATED"] == "1"
    assert env["GH_WORKSPACE_NUM"] == "8"
    assert env["GH_WORKSPACE_DIR"] == str(workspace_dir)
    assert env["SASE_AGENT_LOCAL_XPROMPTS"] == str(xprompts_file)
    assert env["SASE_REPEAT_NAME"] == "task.1"
    mock_claim.assert_called_once()
    assert mock_claim.call_args.args[1] == 0


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_does_not_record_without_chop_env(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal launches are not added to a chop registry."""
    output_path = tmp_path / "out.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr(
        "sase.axe.state.JACK_STATE_DIR", sase_home / "axe" / "lumberjacks"
    )
    mock_spawn.side_effect = _fake_spawn_success
    monkeypatch.setattr("sase.core.paths.get_sase_tmpdir", lambda: str(tmp_dir))
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))

    spawn_agent_subprocess(
        cl_name="proj",
        project_file="/tmp/projects/proj/proj.sase",
        workspace_dir=str(workspace_dir),
        workspace_num=3,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
    )

    assert get_chop_agent_records("hooks", chop_name="split") == []
