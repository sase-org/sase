"""Tests for `sase agents status`."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from sase.agents.cli_status import handle_agents_status
from sase.daemon.client import LocalDaemonClient
from tests.main.agents_handler_helpers import (
    FakeDaemonTransport,
    agent_page,
    agent_summary,
    running_info,
    status_args,
)


def test_status_pretty_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """Pretty status with no agents prints a friendly empty panel."""
    with patch("sase.agents.cli_status.list_running_agents", return_value=[]):
        handle_agents_status(status_args())
    out = capsys.readouterr().out
    assert "Running Agents (0)" in out
    assert "No running agents" in out


def test_status_pretty_populated(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pretty status includes agent name, project, duration, provider."""
    monkeypatch.setenv("COLUMNS", "200")
    agents = [
        running_info(name="brisk-otter", project="sase", duration="1h12m"),
        running_info(
            name="calm-fox",
            project="dotfiles",
            provider="gemini",
            workspace_num=1,
            duration="4m31s",
            prompt="Audit the config",
        ),
    ]
    with patch("sase.agents.cli_status.list_running_agents", return_value=agents):
        handle_agents_status(status_args())
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
        running_info(name="eager-hawk", project="home", workspace_num=None),
    ]
    with patch("sase.agents.cli_status.list_running_agents", return_value=agents):
        handle_agents_status(status_args())
    out = capsys.readouterr().out
    assert "eager-hawk" in out
    assert "home" in out


def test_status_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON output is a list with the documented keys and ISO timestamp."""
    agents = [running_info()]
    with patch("sase.agents.cli_status.list_running_agents", return_value=agents):
        handle_agents_status(status_args(json=True))
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


def test_status_json_preserves_starting_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """JSON status output does not collapse STARTING into RUNNING."""
    agents = [running_info(status="STARTING", duration="?", duration_seconds=None)]
    with patch("sase.agents.cli_status.list_running_agents", return_value=agents):
        handle_agents_status(status_args(json=True))
    row = json.loads(capsys.readouterr().out)[0]
    assert row["status"] == "STARTING"
    assert row["duration_seconds"] is None


def test_status_json_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON output with no agents is an empty list (not null)."""
    with patch("sase.agents.cli_status.list_running_agents", return_value=[]):
        handle_agents_status(status_args(json=True))
    out = capsys.readouterr().out
    assert json.loads(out) == []


def test_status_json_prompt_truncated_to_200(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """prompt_snippet is capped at 200 chars."""
    long_prompt = "x" * 500
    agents = [running_info(prompt=long_prompt)]
    with patch("sase.agents.cli_status.list_running_agents", return_value=agents):
        handle_agents_status(status_args(json=True))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data[0]["prompt_snippet"]) == 200


def test_status_project_filter(capsys: pytest.CaptureFixture[str]) -> None:
    """--project filters rows by exact project name."""
    agents = [
        running_info(name="a", project="sase"),
        running_info(name="b", project="dotfiles"),
    ]
    with patch("sase.agents.cli_status.list_running_agents", return_value=agents):
        handle_agents_status(status_args(json=True, project="dotfiles"))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["name"] == "b"


def test_status_project_filter_uses_daemon_when_capable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Project-scoped status routes through daemon agent projections."""
    transport = FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={"agent_active": [agent_page([agent_summary()])]},
    )
    args = status_args(
        json=True,
        project="sase",
        _daemon_client=LocalDaemonClient(transport=transport),
    )

    with patch(
        "sase.agents.cli_status.list_running_agents",
        side_effect=AssertionError("direct scan should not run"),
    ):
        handle_agents_status(args)

    row = json.loads(capsys.readouterr().out)[0]
    assert row["name"] == "brisk-otter"
    assert row["project"] == "sase"
    assert row["provider"] == "claude"
    assert row["workspace_num"] == 3
    assert row["prompt_snippet"] == "Fix the bug where X breaks under Y"
    assert [request["type"] for request in transport.requests] == [
        "capabilities",
        "read",
    ]
    assert transport.requests[-1]["data"]["surface"] == "agent_active"


def test_status_all_uses_list_all_agents(capsys: pytest.CaptureFixture[str]) -> None:
    """-a/--all routes through list_all_agents (DONE/FAILED included)."""
    agents = [
        running_info(name="live-one", status="RUNNING"),
        running_info(name="launching-one", status="STARTING"),
        running_info(name="finished-one", status="DONE"),
        running_info(name="broken-one", status="FAILED"),
    ]
    with (
        patch(
            "sase.agents.cli_status.list_all_agents", return_value=agents
        ) as mock_all,
        patch("sase.agents.cli_status.list_running_agents") as mock_running,
    ):
        handle_agents_status(status_args(all=True, json=True))
    mock_all.assert_called_once()
    mock_running.assert_not_called()
    data = json.loads(capsys.readouterr().out)
    assert {row["status"] for row in data} == {
        "STARTING",
        "RUNNING",
        "DONE",
        "FAILED",
    }


def test_status_all_project_combines_daemon_active_and_recent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Daemon --all keeps running rows before recent terminal rows."""
    done_summary = agent_summary(
        agent_id="agent:sase:20260422100000",
        timestamp="20260422100000",
        status="failed",
        has_done_marker=True,
        has_running_marker=False,
        agent_name="broken-one",
        finished_at=1770000100.0,
    )
    transport = FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={
            "agent_active": [agent_page([agent_summary()])],
            "agent_recent": [agent_page([done_summary])],
        },
    )
    args = status_args(
        all=True,
        json=True,
        project="sase",
        _daemon_client=LocalDaemonClient(transport=transport),
    )

    with patch(
        "sase.agents.cli_status.list_all_agents",
        side_effect=AssertionError("direct scan should not run"),
    ):
        handle_agents_status(args)

    data = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in data] == ["brisk-otter", "broken-one"]
    assert [row["status"] for row in data] == ["RUNNING", "FAILED"]
    assert [request["data"]["surface"] for request in transport.requests[1:]] == [
        "agent_active",
        "agent_recent",
    ]
