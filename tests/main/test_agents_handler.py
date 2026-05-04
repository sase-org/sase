"""Tests for the 'sase agents' handler (status pretty/JSON, --all, kill, show)."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.running import _KillResult, RunningAgentInfo
from sase.agents.cli_kill import handle_agents_kill
from sase.agents.cli_show import handle_agents_show
from sase.agents.cli_status import handle_agents_status
from sase.main.agents_handler import handle_agents_command


def _running_info(**overrides: Any) -> RunningAgentInfo:
    """Build a RunningAgentInfo with sensible defaults for tests."""
    defaults: dict[str, Any] = {
        "name": "brisk-otter",
        "project": "sase",
        "pid": 12345,
        "model": "claude-opus-4.7",
        "provider": "claude",
        "workspace_num": 3,
        "duration": "1h12m",
        "approve": False,
        "prompt": "Fix the bug where X breaks under Y",
        "status": "RUNNING",
        "started_at": datetime(2026, 4, 23, 12, 34, 56, tzinfo=UTC),
        "duration_seconds": 4321,
        "artifacts_dir": "/home/bryan/.sase/projects/sase/artifacts/ace-run/20260423123456",
    }
    defaults.update(overrides)
    return RunningAgentInfo(**defaults)


def _status_args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "all": False,
        "json": False,
        "project": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# === sase agents status (pretty) ===


def test_status_pretty_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """Pretty status with no agents prints a friendly empty panel."""
    with patch("sase.agents.cli_status.list_running_agents", return_value=[]):
        handle_agents_status(_status_args())
    out = capsys.readouterr().out
    assert "Running Agents (0)" in out
    assert "No running agents" in out


def test_status_pretty_populated(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pretty status includes agent name, project, duration, provider."""
    monkeypatch.setenv("COLUMNS", "200")
    agents = [
        _running_info(name="brisk-otter", project="sase", duration="1h12m"),
        _running_info(
            name="calm-fox",
            project="dotfiles",
            provider="gemini",
            workspace_num=1,
            duration="4m31s",
            prompt="Audit the config",
        ),
    ]
    with patch("sase.agents.cli_status.list_running_agents", return_value=agents):
        handle_agents_status(_status_args())
    out = capsys.readouterr().out
    assert "Running Agents (2)" in out
    assert "brisk-otter" in out
    assert "calm-fox" in out
    assert "1h12m" in out
    assert "gemini" in out


def test_status_pretty_home_workspace_num_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Home-project agents (workspace_num=None) render as '-'."""
    agents = [
        _running_info(name="eager-hawk", project="home", workspace_num=None),
    ]
    with patch("sase.agents.cli_status.list_running_agents", return_value=agents):
        handle_agents_status(_status_args())
    out = capsys.readouterr().out
    assert "eager-hawk" in out
    assert "home" in out


# === sase agents status --json ===


def test_status_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON output is a list with the documented keys and ISO timestamp."""
    agents = [_running_info()]
    with patch("sase.agents.cli_status.list_running_agents", return_value=agents):
        handle_agents_status(_status_args(json=True))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 1
    row = data[0]
    expected_keys = {
        "name",
        "project",
        "pid",
        "model",
        "provider",
        "workspace_num",
        "status",
        "duration_seconds",
        "started_at",
        "approve",
        "prompt_snippet",
        "artifacts_dir",
    }
    assert expected_keys.issubset(row.keys())
    assert row["name"] == "brisk-otter"
    assert row["duration_seconds"] == 4321
    assert row["started_at"] == "2026-04-23T12:34:56+00:00"
    assert row["status"] == "RUNNING"
    assert row["artifacts_dir"].endswith("20260423123456")


def test_status_json_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON output with no agents is an empty list (not null)."""
    with patch("sase.agents.cli_status.list_running_agents", return_value=[]):
        handle_agents_status(_status_args(json=True))
    out = capsys.readouterr().out
    assert json.loads(out) == []


def test_status_json_prompt_truncated_to_200(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """prompt_snippet is capped at 200 chars."""
    long_prompt = "x" * 500
    agents = [_running_info(prompt=long_prompt)]
    with patch("sase.agents.cli_status.list_running_agents", return_value=agents):
        handle_agents_status(_status_args(json=True))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data[0]["prompt_snippet"]) == 200


# === project filter ===


def test_status_project_filter(capsys: pytest.CaptureFixture[str]) -> None:
    """--project filters rows by exact project name."""
    agents = [
        _running_info(name="a", project="sase"),
        _running_info(name="b", project="dotfiles"),
    ]
    with patch("sase.agents.cli_status.list_running_agents", return_value=agents):
        handle_agents_status(_status_args(json=True, project="dotfiles"))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["name"] == "b"


# === --all mode ===


def test_status_all_uses_list_all_agents(capsys: pytest.CaptureFixture[str]) -> None:
    """-a/--all routes through list_all_agents (DONE/FAILED included)."""
    agents = [
        _running_info(name="live-one", status="RUNNING"),
        _running_info(name="finished-one", status="DONE"),
        _running_info(name="broken-one", status="FAILED"),
    ]
    with (
        patch(
            "sase.agents.cli_status.list_all_agents", return_value=agents
        ) as mock_all,
        patch("sase.agents.cli_status.list_running_agents") as mock_running,
    ):
        handle_agents_status(_status_args(all=True, json=True))
    mock_all.assert_called_once()
    mock_running.assert_not_called()
    data = json.loads(capsys.readouterr().out)
    assert {row["status"] for row in data} == {"RUNNING", "DONE", "FAILED"}


# === dispatch: bare `sase agents` → status ===


def test_dispatch_bare_defaults_to_status() -> None:
    """A bare `sase agents` (no subcommand) invokes the status handler."""
    args = argparse.Namespace(
        agents_subcommand=None, all=False, json=True, project=None
    )
    with (
        patch("sase.agents.cli_status.list_running_agents", return_value=[]),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)
    assert excinfo.value.code == 0


def test_dispatch_unknown_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown subcommand prints usage and exits 1."""
    args = argparse.Namespace(agents_subcommand="bogus")
    with pytest.raises(SystemExit) as excinfo:
        handle_agents_command(args)
    assert excinfo.value.code == 1
    assert "Usage: sase agents" in capsys.readouterr().out


def test_dispatch_archive_rebuild_index(capsys: pytest.CaptureFixture[str]) -> None:
    """Archive maintenance dispatches to the dismissed-bundle index rebuild."""
    args = argparse.Namespace(
        agents_subcommand="archive",
        archive_subcommand="rebuild-index",
    )
    with (
        patch(
            "sase.ace.dismissed_agents.rebuild_dismissed_bundle_index",
            return_value=(2, 1),
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)
    assert excinfo.value.code == 0
    assert (
        "Indexed 2 dismissed bundles; skipped 1 corrupt files."
        in capsys.readouterr().out
    )


def test_dispatch_archive_verify_exits_nonzero_when_stale(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Archive verify reports failures through its process exit code."""
    args = argparse.Namespace(
        agents_subcommand="archive",
        archive_subcommand="verify",
    )
    with (
        patch(
            "sase.ace.dismissed_agents.verify_dismissed_bundle_index",
            return_value={
                "ok": False,
                "indexed_rows": 1,
                "valid_bundles": 2,
                "corrupt_bundles": 0,
                "stale_rows": 0,
                "missing_rows": 1,
            },
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_command(args)
    assert excinfo.value.code == 1
    assert '"missing_rows": 1' in capsys.readouterr().out


# === sase agents kill ===


def test_kill_success(capsys: pytest.CaptureFixture[str]) -> None:
    """Successful kill prints message to stdout and exits 0."""
    args = argparse.Namespace(name="brisk-otter")
    with (
        patch(
            "sase.agents.cli_kill.kill_named_agent",
            return_value=_KillResult(True, "Killed agent 'brisk-otter' (PID 12345)"),
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_kill(args)
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "Killed agent 'brisk-otter'" in captured.out
    assert captured.err == ""


def test_kill_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    """Kill of missing agent writes to stderr and exits 2."""
    args = argparse.Namespace(name="ghost")
    with (
        patch(
            "sase.agents.cli_kill.kill_named_agent",
            return_value=_KillResult(False, "No agent found with name 'ghost'"),
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_kill(args)
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "No agent found" in captured.err
    assert captured.out == ""


# === sase agents show ===


def test_show_missing_agent_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    """show with unknown name exits 2 with stderr message."""
    args = argparse.Namespace(name="ghost")
    with (
        patch("sase.agents.cli_show.find_named_agent", return_value=None),
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_agents_show(args)
    assert excinfo.value.code == 2
    assert "No agent found" in capsys.readouterr().err


def test_show_renders_running_panel(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """show on a running agent renders a detail panel with prompt + tail hint."""
    from sase.agent.names import NamedAgent

    artifacts_dir = (
        tmp_path / "projects" / "sase" / "artifacts" / "ace-run" / "20260423120000"
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "model": "claude-opus-4.7",
                "llm_provider": "claude",
                "pid": 12345,
            }
        )
    )
    (artifacts_dir / "raw_xprompt.md").write_text("Fix the flaky test in foo_test.py")

    named = NamedAgent(
        name="brisk-otter",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )
    args = argparse.Namespace(name="brisk-otter")
    with patch("sase.agents.cli_show.find_named_agent", return_value=named):
        handle_agents_show(args)

    out = capsys.readouterr().out
    assert "brisk-otter" in out
    assert "RUNNING" in out
    assert "Fix the flaky test" in out
    assert "live_reply.md" in out
