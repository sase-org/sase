"""Tests scrubbing ambient identity/provenance state during agent launch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.chop_agents import (
    ENV_CHOP_LUMBERJACK,
    ENV_CHOP_NAME,
    ENV_CHOP_PROMPT_HASH,
    ENV_CHOP_RUN_ID,
    get_chop_agent_records,
)
from sase.detach_scope import _DetachScopeCommand
from sase.running_field import ClaimResult
from sase.xprompt.used_xprompts import SASE_LAUNCH_SWARM_XPROMPTS

from tests._axe_chop_agents_helpers import _spawn_agent_for_env_test

pytest_plugins = ["tests.axe_chop_agents_fixtures"]


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_requires_complete_owner_before_process_creation(
    mock_spawn: MagicMock,
    _mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: (_ for _ in ()).throw(RuntimeError("run `sase config init`")),
    )

    with pytest.raises(RuntimeError, match="sase config init"):
        _spawn_agent_for_env_test(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            mock_spawn=mock_spawn,
        )

    mock_spawn.assert_not_called()


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
    assert "SASE_AGENT_NAME" not in env
    assert "SASE_AGENT_AUTO_APPROVE" not in env
    assert "SASE_AGENT_ROOT_TIMESTAMP" not in env


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_scrubs_ambient_chop_context_without_recording(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nested launches neither inherit nor register ambient chop identity."""
    monkeypatch.setenv(ENV_CHOP_LUMBERJACK, "hooks")
    monkeypatch.setenv(ENV_CHOP_NAME, "split")
    monkeypatch.setenv(ENV_CHOP_RUN_ID, "run-1")
    monkeypatch.setenv(ENV_CHOP_PROMPT_HASH, "prompt-hash")
    monkeypatch.setenv("SASE_JOB_ROUTINE", "hooks")
    monkeypatch.setenv("SASE_JOB_NAME", "split")
    monkeypatch.setenv("SASE_JOB_RUN_ID", "run-1")
    monkeypatch.setenv("SASE_CHOP_RESULT_FILE", "/tmp/ambient-result.json")
    monkeypatch.setenv("SASE_JOB_RESULT_FILE", "/tmp/ambient-result.json")

    _spawn_agent_for_env_test(
        tmp_path=tmp_path, monkeypatch=monkeypatch, mock_spawn=mock_spawn
    )

    env = mock_spawn.call_args.kwargs["env"]
    chop_keys = sorted(
        key for key in env if key.startswith(("SASE_CHOP_", "SASE_JOB_"))
    )
    assert not chop_keys, chop_keys
    assert get_chop_agent_records("hooks", chop_name="split") == []


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_scrubs_proc_operation_context(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nested agent launches do not inherit the caller's proc ownership."""
    for key in (
        "SASE_PROC_REQUEST_PATH",
        "SASE_PROC_RESULT_PATH",
        "SASE_PROC_OPERATION",
        "SASE_PROC_ID",
        "SASE_PROC_LOG_PATH",
        "SASE_PROC_SESSION_ID",
    ):
        monkeypatch.setenv(key, f"/tmp/stale-{key}")

    _spawn_agent_for_env_test(
        tmp_path=tmp_path, monkeypatch=monkeypatch, mock_spawn=mock_spawn
    )

    env = mock_spawn.call_args.kwargs["env"]
    proc_keys = sorted(key for key in env if key.startswith("SASE_PROC_"))
    assert proc_keys == []


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
def test_spawn_agent_subprocess_scopes_swarm_provenance_to_explicit_launch(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nested launch drops ambient provenance but keeps an explicit chain."""
    monkeypatch.setenv(SASE_LAUNCH_SWARM_XPROMPTS, '["parent_swarm"]')
    inherited_case = tmp_path / "inherited"
    inherited_case.mkdir()

    _spawn_agent_for_env_test(
        tmp_path=inherited_case,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
    )
    assert SASE_LAUNCH_SWARM_XPROMPTS not in mock_spawn.call_args.kwargs["env"]

    explicit_case = tmp_path / "explicit"
    explicit_case.mkdir()
    _spawn_agent_for_env_test(
        tmp_path=explicit_case,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
        extra_env={SASE_LAUNCH_SWARM_XPROMPTS: '["child_swarm"]'},
    )
    assert (
        mock_spawn.call_args.kwargs["env"][SASE_LAUNCH_SWARM_XPROMPTS]
        == '["child_swarm"]'
    )


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_wraps_prepared_argv_with_detach_scope(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_detach_scope(argv: list[str], **_kwargs: object) -> _DetachScopeCommand:
        return _DetachScopeCommand(["scope", *argv], start_new_session=True)

    monkeypatch.setattr("sase.agent.launch_spawn.detach_scope", fake_detach_scope)

    _spawn_agent_for_env_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
    )

    prepared = mock_spawn.call_args.args[0]
    assert prepared.argv[0] == "scope"
