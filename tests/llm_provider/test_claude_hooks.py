"""Tests for SASE Claude tool-call hook registration during agent launch."""

from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._claude_hooks import (
    SASE_HOOK_COMMAND,
    SASE_HOOK_EVENTS,
    SASE_HOOK_SENTINEL,
    SASE_HOOK_SENTINEL_VALUE,
    claude_hooks_session,
    resolve_workspace_dir,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "ws"


@pytest.fixture
def artifacts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    art = tmp_path / "artifacts"
    art.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(art))
    return art


def _settings_path(workspace: Path) -> Path:
    return workspace / ".claude" / "settings.local.json"


def _read_settings(workspace: Path) -> dict:
    return json.loads(_settings_path(workspace).read_text(encoding="utf-8"))


def _sase_command(entry: dict) -> dict | None:
    for cmd in entry.get("hooks", []):
        if cmd.get(SASE_HOOK_SENTINEL) == SASE_HOOK_SENTINEL_VALUE:
            return cmd
    return None


def test_session_enables_pre_and_post_hooks(workspace: Path) -> None:
    workspace.mkdir()
    with claude_hooks_session(workspace) as enabled:
        assert enabled is True
        data = _read_settings(workspace)
        for event in SASE_HOOK_EVENTS:
            bucket = data["hooks"][event]
            assert any(_sase_command(e) for e in bucket)
            cmd = _sase_command(bucket[-1])
            assert cmd is not None
            assert cmd["command"] == SASE_HOOK_COMMAND
            assert cmd["type"] == "command"


def test_session_creates_dot_claude_dir_when_missing(workspace: Path) -> None:
    workspace.mkdir()
    assert not (workspace / ".claude").exists()
    with claude_hooks_session(workspace):
        assert _settings_path(workspace).exists()


def test_session_preserves_existing_hooks(workspace: Path) -> None:
    workspace.mkdir()
    claude_dir = workspace / ".claude"
    claude_dir.mkdir()
    user_entry = {
        "matcher": "Bash",
        "hooks": [
            {"type": "command", "command": "user_bash_hook"},
        ],
    }
    initial = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {
            "PreToolUse": [user_entry],
            "Notification": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "ping"}]}
            ],
        },
    }
    _settings_path(workspace).write_text(
        json.dumps(initial, indent=2), encoding="utf-8"
    )

    with claude_hooks_session(workspace):
        data = _read_settings(workspace)
        # User permissions preserved
        assert data["permissions"] == {"allow": ["Bash(ls:*)"]}
        # User PreToolUse entry preserved alongside the SASE one
        assert user_entry in data["hooks"]["PreToolUse"]
        assert any(_sase_command(e) for e in data["hooks"]["PreToolUse"])
        # PostToolUse newly created with a SASE entry
        assert any(_sase_command(e) for e in data["hooks"]["PostToolUse"])
        # Unrelated hook event left untouched
        assert data["hooks"]["Notification"] == initial["hooks"]["Notification"]


def test_session_cleanup_removes_only_sase_entries(workspace: Path) -> None:
    workspace.mkdir()
    claude_dir = workspace / ".claude"
    claude_dir.mkdir()
    user_entry = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "user_bash_hook"}],
    }
    initial = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {"PreToolUse": [user_entry]},
    }
    _settings_path(workspace).write_text(
        json.dumps(initial, indent=2), encoding="utf-8"
    )

    with claude_hooks_session(workspace):
        pass

    data = _read_settings(workspace)
    assert data["permissions"] == {"allow": ["Bash(ls:*)"]}
    assert data["hooks"] == {"PreToolUse": [user_entry]}


def test_session_cleanup_removes_file_when_only_sase_entries(
    workspace: Path,
) -> None:
    workspace.mkdir()
    with claude_hooks_session(workspace):
        assert _settings_path(workspace).exists()
    assert not _settings_path(workspace).exists()
    # .claude dir should also be removed when we created it
    assert not (workspace / ".claude").exists()


def test_session_cleanup_after_exception(workspace: Path) -> None:
    workspace.mkdir()
    with pytest.raises(RuntimeError), claude_hooks_session(workspace):
        raise RuntimeError("simulated kill")
    assert not _settings_path(workspace).exists()


def test_session_cleanup_keeps_preexisting_empty_file(workspace: Path) -> None:
    workspace.mkdir()
    (workspace / ".claude").mkdir()
    _settings_path(workspace).write_text("{}", encoding="utf-8")

    with claude_hooks_session(workspace):
        pass

    # File should remain since it pre-existed
    assert _settings_path(workspace).exists()
    assert _read_settings(workspace) == {}


def test_session_disabled_when_workspace_none() -> None:
    with claude_hooks_session(None) as enabled:
        assert enabled is False


def test_session_disabled_when_explicit_disabled(workspace: Path) -> None:
    workspace.mkdir()
    with claude_hooks_session(workspace, enabled=False) as enabled:
        assert enabled is False
    assert not _settings_path(workspace).exists()


def test_session_skips_when_existing_settings_malformed(
    workspace: Path, artifacts_dir: Path
) -> None:
    workspace.mkdir()
    (workspace / ".claude").mkdir()
    malformed = "{not valid json"
    _settings_path(workspace).write_text(malformed, encoding="utf-8")

    with claude_hooks_session(workspace) as enabled:
        assert enabled is False
        assert _settings_path(workspace).read_text(encoding="utf-8") == malformed

    # Diagnostic was written
    diag = artifacts_dir / "tool_calls_writer_errors.jsonl"
    assert diag.exists()
    rows = [json.loads(line) for line in diag.read_text().splitlines() if line.strip()]
    assert any(
        r.get("reason") == "claude_hooks_skipped"
        and r.get("mode") == "settings_file_malformed"
        for r in rows
    )


def test_home_mode_diagnostic_emitted(
    monkeypatch: pytest.MonkeyPatch, artifacts_dir: Path
) -> None:
    for name in (
        "SASE_GIT_WORKSPACE_DIR",
        "SASE_CD_WORKSPACE_DIR",
        "SASE_ACTIVE_PROJECT_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    assert resolve_workspace_dir() is None

    with claude_hooks_session(resolve_workspace_dir()) as enabled:
        assert enabled is False

    diag = artifacts_dir / "tool_calls_writer_errors.jsonl"
    assert diag.exists()
    rows = [json.loads(line) for line in diag.read_text().splitlines() if line.strip()]
    assert any(
        r.get("reason") == "claude_hooks_skipped"
        and r.get("mode") == "home_mode_or_no_workspace"
        for r in rows
    )


def test_resolve_workspace_dir_prefers_git_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", "/ws/git")
    monkeypatch.setenv("SASE_CD_WORKSPACE_DIR", "/ws/cd")
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", "/ws/active")
    assert resolve_workspace_dir() == "/ws/git"


def test_resolve_workspace_dir_falls_back_to_cd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_GIT_WORKSPACE_DIR", raising=False)
    monkeypatch.setenv("SASE_CD_WORKSPACE_DIR", "/ws/cd")
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", "/ws/active")
    assert resolve_workspace_dir() == "/ws/cd"


def test_resolve_workspace_dir_falls_back_to_active_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_GIT_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("SASE_CD_WORKSPACE_DIR", raising=False)
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", "/ws/active")
    assert resolve_workspace_dir() == "/ws/active"


def test_concurrent_sessions_in_separate_workspaces(tmp_path: Path) -> None:
    ws1 = tmp_path / "ws1"
    ws2 = tmp_path / "ws2"
    ws1.mkdir()
    ws2.mkdir()

    with claude_hooks_session(ws1):
        with claude_hooks_session(ws2):
            for ws in (ws1, ws2):
                data = _read_settings(ws)
                for event in SASE_HOOK_EVENTS:
                    assert any(_sase_command(e) for e in data["hooks"][event])

    assert not _settings_path(ws1).exists()
    assert not _settings_path(ws2).exists()


def test_cleanup_preserves_non_sase_hook_in_same_matcher(workspace: Path) -> None:
    """If user adds a non-SASE command to a SASE matcher entry, keep it on cleanup."""
    workspace.mkdir()
    (workspace / ".claude").mkdir()

    with claude_hooks_session(workspace):
        # Simulate user (or another process) appending a non-SASE command to
        # the same matcher entry SASE just wrote.
        data = _read_settings(workspace)
        data["hooks"]["PreToolUse"][0]["hooks"].append(
            {"type": "command", "command": "user_added"}
        )
        _settings_path(workspace).write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    final = _read_settings(workspace)
    pre = final["hooks"]["PreToolUse"]
    assert len(pre) == 1
    inner = pre[0]["hooks"]
    assert {"type": "command", "command": "user_added"} in inner
    assert not any(
        cmd.get(SASE_HOOK_SENTINEL) == SASE_HOOK_SENTINEL_VALUE for cmd in inner
    )


def test_failed_session_does_not_corrupt_existing_file(workspace: Path) -> None:
    """Even if the with-body raises, prior settings must be restored."""
    workspace.mkdir()
    (workspace / ".claude").mkdir()
    initial = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "user_hook"}]}
            ]
        }
    }
    _settings_path(workspace).write_text(
        json.dumps(initial, indent=2), encoding="utf-8"
    )

    with pytest.raises(ValueError):
        with claude_hooks_session(workspace):
            raise ValueError("kill mid-run")

    data = _read_settings(workspace)
    assert data == initial


def test_artifacts_dir_unset_means_diagnostic_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No SASE_ARTIFACTS_DIR → diagnostic call is a no-op, no exceptions."""
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    with claude_hooks_session(None) as enabled:
        assert enabled is False
    # The diagnostic call returns silently when there's no artifacts dir.
    # Nothing else to verify — this test exists to lock in the no-throw contract.


def test_subprocess_environment_keeps_sase_env(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hook collector runs as a subprocess and inherits SASE env vars.

    This test pins the contract that hook entries do not strip the
    ``SASE_ARTIFACTS_DIR`` / ``SASE_AGENT_TIMESTAMP`` env from the inherited
    environment. The Claude CLI inherits its environment from the SASE-launched
    Claude provider process, and hook commands inherit from the CLI.
    """
    workspace.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", "/tmp/artifacts-x")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260514_010101")
    with claude_hooks_session(workspace):
        data = _read_settings(workspace)
        for event in SASE_HOOK_EVENTS:
            cmd = _sase_command(data["hooks"][event][0])
            assert cmd is not None
            # The recorded command must not embed env values — the collector
            # reads env at runtime from its inherited environment.
            assert "SASE_ARTIFACTS_DIR" not in cmd["command"]
            assert os.environ["SASE_ARTIFACTS_DIR"] == "/tmp/artifacts-x"


def test_claude_provider_invoke_registers_and_cleans_up_hooks(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provider.invoke() must install hooks for the duration of the run."""
    from unittest.mock import MagicMock, patch

    from sase.llm_provider.claude import ClaudeCodeProvider

    workspace.mkdir()
    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", str(workspace))
    monkeypatch.delenv("SASE_CD_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)

    settings_path = _settings_path(workspace)
    observed_during_invoke: dict[str, dict] = {}

    def fake_stream(*_args, **_kwargs):
        # Settings file should be populated with SASE hooks WHILE the Claude
        # subprocess is running.
        observed_during_invoke["data"] = json.loads(
            settings_path.read_text(encoding="utf-8")
        )
        return (
            "response",
            "",
            0,
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        )

    with (
        patch("sase.llm_provider.claude.subprocess.Popen", return_value=MagicMock()),
        patch(
            "sase.llm_provider.claude.stream_and_parse_json_output",
            side_effect=fake_stream,
        ),
        patch("sase.llm_provider.claude.gemini_timer"),
    ):
        provider = ClaudeCodeProvider()
        provider.invoke("hi", model_tier="small", suppress_output=True)

    # During the subprocess call, the SASE hook entries should have been live.
    assert "data" in observed_during_invoke
    for event in SASE_HOOK_EVENTS:
        bucket = observed_during_invoke["data"]["hooks"][event]
        assert any(_sase_command(e) for e in bucket)
    # After invoke returns, cleanup removes the SASE-only file.
    assert not settings_path.exists()


def test_claude_provider_invoke_skips_hooks_in_home_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Home-mode launches must not touch any settings file."""
    from unittest.mock import MagicMock, patch

    from sase.llm_provider.claude import ClaudeCodeProvider

    for name in (
        "SASE_GIT_WORKSPACE_DIR",
        "SASE_CD_WORKSPACE_DIR",
        "SASE_ACTIVE_PROJECT_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    # If hook registration tried to read/write anywhere under cwd, it would
    # touch ".claude/settings.local.json" — pre-create cwd so we can verify
    # it stayed untouched.
    monkeypatch.chdir(tmp_path)

    def fake_stream(*_args, **_kwargs):
        return (
            "response",
            "",
            0,
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        )

    with (
        patch("sase.llm_provider.claude.subprocess.Popen", return_value=MagicMock()),
        patch(
            "sase.llm_provider.claude.stream_and_parse_json_output",
            side_effect=fake_stream,
        ),
        patch("sase.llm_provider.claude.gemini_timer"),
    ):
        provider = ClaudeCodeProvider()
        provider.invoke("hi", model_tier="small", suppress_output=True)

    assert not (tmp_path / ".claude").exists()

    # And a diagnostic was emitted explaining why hooks were skipped.
    diag = tmp_path / "tool_calls_writer_errors.jsonl"
    assert diag.exists()
    rows = [json.loads(line) for line in diag.read_text().splitlines() if line.strip()]
    assert any(
        r.get("reason") == "claude_hooks_skipped"
        and r.get("mode") == "home_mode_or_no_workspace"
        for r in rows
    )


def test_simulated_claude_provider_run_writes_hook_first_records(
    workspace: Path, artifacts_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provider-installed hooks plus collector output produce readable entries."""
    from sase.ace.tui.models.agent import Agent, AgentType
    from sase.ace.tui.tools import read_tool_calls_for_agent
    from sase.llm_provider.claude import ClaudeCodeProvider
    from sase.scripts.sase_claude_tool_hook import main as collector_main

    workspace.mkdir()
    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", str(workspace))
    monkeypatch.delenv("SASE_CD_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260515_010101")

    def run_collector(payload: dict) -> None:
        with patch("sys.stdin", io.StringIO(json.dumps(payload))):
            assert collector_main([]) == 0

    def fake_stream(*_args, **_kwargs):
        data = _read_settings(workspace)
        for event in SASE_HOOK_EVENTS:
            bucket = data["hooks"][event]
            assert any(_sase_command(entry) for entry in bucket)

        base_payload = {
            "session_id": "session-sim",
            "transcript_path": str(workspace / ".claude" / "transcript.jsonl"),
            "cwd": str(workspace),
            "tool_name": "Bash",
            "tool_input": {"command": "printf hi"},
            "tool_use_id": "toolu_simulated",
        }
        run_collector({"hook_event_name": "PreToolUse", **base_payload})
        run_collector(
            {
                "hook_event_name": "PostToolUse",
                **base_payload,
                "tool_response": {"exit_code": 0, "stdout": "hi", "success": True},
                "duration_ms": 12,
            }
        )
        return (
            "response",
            "",
            0,
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        )

    with (
        patch("sase.llm_provider.claude.subprocess.Popen", return_value=MagicMock()),
        patch(
            "sase.llm_provider.claude.stream_and_parse_json_output",
            side_effect=fake_stream,
        ),
        patch("sase.llm_provider.claude.gemini_timer"),
    ):
        provider = ClaudeCodeProvider()
        provider.invoke("hi", model_tier="small", suppress_output=True)

    assert not _settings_path(workspace).exists()
    raw_rows = [
        json.loads(line)
        for line in (artifacts_dir / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert [row["source"] for row in raw_rows] == ["hook", "hook"]
    assert [row["hook_event"] for row in raw_rows] == ["PreToolUse", "PostToolUse"]

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file=str(workspace / "proj.sase"),
        status="DONE",
        start_time=datetime(2026, 5, 15, 1, 1, 1),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
    )
    entries = read_tool_calls_for_agent(agent)

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source == "hook"
    assert entry.tool_use_id == "toolu_simulated"
    assert entry.status == "success"
    assert entry.duration_ms == 12
    assert entry.compact_target == "printf hi"
