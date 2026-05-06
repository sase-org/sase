"""Tests for the read-only mobile agent bridge."""

from __future__ import annotations

import argparse
import io
import json
from datetime import UTC, datetime
from pathlib import Path

from sase.agent.running import RunningAgentInfo
from sase.integrations import mobile_agents
from sase.integrations.mobile_agents import (
    _launch_mobile_text_agents,
    _list_mobile_agents,
    _mobile_agent_resume_options,
    handle_mobile_agent_bridge,
)
from sase.agent.launcher import AgentLaunchResult


def _agent(
    tmp_path: Path,
    *,
    name: str | None = "alpha",
    status: str = "RUNNING",
    project: str = "sase",
) -> RunningAgentInfo:
    artifacts_dir = tmp_path / (name or "unnamed")
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "retry_of_timestamp": "20260506140000",
                "retry_attempt": 1,
                "parent_agent_name": "parent",
            }
        ),
        encoding="utf-8",
    )
    return RunningAgentInfo(
        name=name,
        project=project,
        pid=1234,
        model="gpt-5.5",
        provider="codex",
        workspace_num=100,
        duration="1m",
        approve=False,
        prompt="Line one\nLine two",
        status=status,
        started_at=datetime(2026, 5, 6, 14, 30, tzinfo=UTC),
        duration_seconds=60,
        artifacts_dir=str(artifacts_dir),
    )


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


def test_launch_mobile_text_agents_normalizes_prompt_and_returns_slots(
    monkeypatch,
) -> None:
    captured: list[str] = []

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        captured.append(prompt)
        return [
            AgentLaunchResult(
                pid=111,
                workspace_num=0,
                workspace_dir="/tmp/ws1",
                output_path="/tmp/out1",
                project_name="home",
                timestamp="260506_143000",
            ),
            AgentLaunchResult(
                pid=222,
                workspace_num=0,
                workspace_dir="/tmp/ws2",
                output_path="/tmp/out2",
                project_name="home",
                timestamp="260506_143001",
            ),
        ]

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fake_launch)
    monkeypatch.setattr(
        "sase.xprompt._parsing._LAUNCH_XPROMPT_AT_REF_RE",
        None,
    )
    monkeypatch.setattr(
        "sase.workspace_provider.get_workflow_names",
        lambda: {"gh", "cd"},
    )

    payload = _launch_mobile_text_agents(
        {
            "schema_version": 1,
            "prompt": "#gh@sase Fix it",
            "name": "mobile.demo",
            "provider": "codex",
            "model": "gpt-5.5",
        }
    )

    assert captured == ["%name:mobile.demo\n%model:codex/gpt-5.5\n#gh:sase Fix it"]
    assert payload["primary"] == payload["slots"][0]
    assert [slot["status"] for slot in payload["slots"]] == ["launched", "launched"]
    assert payload["slots"][0]["artifact_dir"].endswith(
        "/.sase/projects/home/artifacts/ace-run/20260506143000"
    )


def test_launch_mobile_text_agents_reports_validation_errors() -> None:
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="launch-text"),
        stdin=io.StringIO('{"schema_version":1,"prompt":"   "}'),
        stderr=stderr,
    )

    assert code == 2
    assert "prompt must be a non-empty string" in stderr.getvalue()


def test_launch_mobile_text_dry_run_does_not_spawn(monkeypatch) -> None:
    def fail_launch(_prompt: str) -> list[AgentLaunchResult]:
        raise AssertionError("dry run should not launch")

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fail_launch)

    payload = _launch_mobile_text_agents(
        {"schema_version": 1, "prompt": "%name:dry\nDo work", "dry_run": True}
    )

    assert payload["primary"] == {
        "slot_id": "0",
        "name": "dry",
        "status": "dry_run",
        "artifact_dir": None,
        "message": "launch request validated",
    }
