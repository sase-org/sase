"""Tests for mobile agent listing and bridge dispatch."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from sase.integrations import mobile_agents
from sase.integrations.mobile_agents import (
    _list_mobile_agents,
    _mobile_agent_resume_options,
    handle_mobile_agent_bridge,
)
from tests._mobile_agents_fixtures import _agent, _known_project


def test_list_mobile_agents_projects_running_agent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mobile_agents,
        "list_running_agents",
        lambda: [_agent(tmp_path)],
    )

    payload = _list_mobile_agents({"schema_version": 1})

    assert payload["schema_version"] == 1
    assert payload["total_count"] == 1
    agent = payload["agents"][0]
    assert agent["name"] == "alpha"
    assert agent["status"] == "running"
    assert agent["pid"] == 1234
    assert agent["workspace_number"] == 100
    assert agent["prompt_snippet"] == "Line one Line two"
    assert agent["has_artifact_dir"] is True
    assert agent["actions"] == {
        "can_resume": True,
        "can_wait": True,
        "can_kill": True,
        "can_retry": True,
    }
    assert agent["retry_lineage"]["retry_of_timestamp"] == "20260506140000"
    assert agent["retry_lineage"]["retry_attempt"] == 1


def test_list_mobile_agents_filters_and_limits(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    _known_project(tmp_path, "sase")
    monkeypatch.setattr(
        mobile_agents,
        "list_all_agents",
        lambda: [
            _agent(tmp_path, name="alpha", status="DONE", project="sase"),
            _agent(tmp_path, name="bravo", status="RUNNING", project="other"),
        ],
    )

    payload = _list_mobile_agents(
        {
            "include_recent": True,
            "status": "done",
            "project": "sase",
            "limit": 1,
        }
    )

    assert payload["total_count"] == 1
    assert [agent["name"] for agent in payload["agents"]] == ["alpha"]


def test_resume_options_use_native_resume_and_wait_syntax(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        mobile_agents,
        "list_all_agents",
        lambda: [_agent(tmp_path, name="alpha"), _agent(tmp_path, name="has space")],
    )

    payload = _mobile_agent_resume_options()

    assert payload["options"][0] == {
        "id": "alpha:resume",
        "agent_name": "alpha",
        "kind": "resume",
        "label": "Resume alpha",
        "prompt_text": "#resume:alpha\n",
        "direct_launch_supported": True,
    }
    assert payload["options"][1]["prompt_text"] == "%wait:alpha\n"
    assert payload["options"][2]["prompt_text"] == "#resume:`has space`\n"
    assert payload["options"][3]["prompt_text"] == "%wait:`has space`\n"


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
