"""Tests for generic mobile agent bridge handler behavior."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from sase.integrations import mobile_agents
from sase.integrations.mobile_agents import handle_mobile_agent_bridge
from tests._mobile_agents_fixtures import _agent


def test_bridge_handler_writes_compact_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mobile_agents,
        "list_running_agents",
        lambda: [_agent(tmp_path)],
    )
    stdout = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="list-agents"),
        stdin=io.StringIO('{"schema_version":1}'),
        stdout=stdout,
    )

    assert code == 0
    assert json.loads(stdout.getvalue())["agents"][0]["name"] == "alpha"


def test_bridge_handler_rejects_malformed_json() -> None:
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="list-agents"),
        stdin=io.StringIO("{"),
        stderr=stderr,
    )

    assert code == 2
    assert "invalid JSON request" in stderr.getvalue()
