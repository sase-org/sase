"""Tests for `sase agents kill` and `sase agents show`."""

from __future__ import annotations

import argparse
import json
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.running import _KillResult
from sase.agents.cli_kill import handle_agents_kill
from sase.agents.cli_show import handle_agents_show
from sase.daemon.client import LocalDaemonClient
from tests.main.agents_handler_helpers import (
    FakeDaemonTransport,
    agent_detail,
    agent_page,
    agent_summary,
)


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


def test_show_handle_uses_daemon_detail_without_name_scan(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An agent:<project>:<timestamp> handle can render from daemon detail."""
    summary = agent_summary()
    transport = FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={
            "agent_detail": [
                agent_detail(summary, prompt="Investigate daemon-backed reads")
            ]
        },
    )
    args = argparse.Namespace(
        name="agent:sase:20260423123456",
        project=None,
        no_daemon=False,
        _daemon_client=LocalDaemonClient(transport=transport),
    )

    with patch(
        "sase.agents.cli_show.find_named_agent",
        side_effect=AssertionError("direct name scan should not run"),
    ):
        handle_agents_show(args)

    out = capsys.readouterr().out
    assert "brisk-otter" in out
    assert "RUNNING" in out
    assert "Investigate daemon-backed reads" in out
    assert [request["type"] for request in transport.requests] == [
        "capabilities",
        "read",
    ]


def test_show_project_name_uses_daemon_search_then_detail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Project-scoped name lookup resolves through daemon search."""
    summary = agent_summary()
    transport = FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={
            "agent_search": [agent_page([summary])],
            "agent_detail": [agent_detail(summary, prompt="Search-resolved prompt")],
        },
    )
    args = argparse.Namespace(
        name="brisk-otter",
        project="sase",
        no_daemon=False,
        _daemon_client=LocalDaemonClient(transport=transport),
    )

    with patch(
        "sase.agents.cli_show.find_named_agent",
        side_effect=AssertionError("direct name scan should not run"),
    ):
        handle_agents_show(args)

    out = capsys.readouterr().out
    assert "Search-resolved prompt" in out
    assert [request["data"]["surface"] for request in transport.requests[1:]] == [
        "agent_search",
        "agent_detail",
    ]
