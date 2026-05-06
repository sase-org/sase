"""Tests for killing and retrying mobile agents."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from sase.agent.launcher import AgentLaunchResult
from sase.agent.running import _KillResult
from sase.integrations import mobile_agents
from sase.integrations.mobile_agents import (
    _kill_mobile_agent,
    _retry_mobile_agent,
    handle_mobile_agent_bridge,
)
from tests._mobile_agents_fixtures import _agent


def test_kill_mobile_agent_returns_result_and_persists_context(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    agent = _agent(tmp_path, name="alpha")
    monkeypatch.setattr(mobile_agents, "list_all_agents", lambda: [agent])
    monkeypatch.setattr(
        mobile_agents,
        "kill_named_agent",
        lambda name, *, exact_name: _KillResult(
            True,
            f"Killed agent '{name}' (PID 1234)",
            status="killed",
            pid=1234,
            changed=True,
            artifacts_dir=agent.artifacts_dir,
            project="sase",
            timestamp="20260506143000",
        ),
    )

    payload = _kill_mobile_agent(
        {
            "schema_version": 1,
            "name": "alpha",
            "reason": "mobile",
            "device_id": "device_123",
        }
    )

    assert payload == {
        "schema_version": 1,
        "name": "alpha",
        "status": "killed",
        "pid": 1234,
        "changed": True,
        "message": "Killed agent 'alpha' (PID 1234)",
    }
    context_path = tmp_path / "mobile_gateway" / "agent_kill_contexts" / "alpha.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    assert context["agent_name"] == "alpha"
    assert context["artifact_dir"] == agent.artifacts_dir
    assert context["project"] == "sase"
    assert context["raw_prompt"] == "Line one\nLine two"
    assert context["killed_pid"] == 1234
    assert context["device_id"] == "device_123"


@pytest.mark.parametrize(
    ("result", "expected_code", "expected_message"),
    [
        (
            _KillResult(
                False,
                "No agent found with name 'missing'",
                reason="not_found",
            ),
            4,
            "No agent found",
        ),
        (
            _KillResult(
                False,
                "Agent 'done' already completed",
                reason="already_completed",
            ),
            5,
            "already completed",
        ),
        (
            _KillResult(
                False,
                "Could not find PID for agent 'stale'",
                reason="missing_pid",
            ),
            5,
            "Could not find PID",
        ),
        (
            _KillResult(
                False,
                "Permission denied killing agent 'alpha' (PID 1234)",
                reason="permission_denied",
            ),
            6,
            "Permission denied",
        ),
    ],
)
def test_kill_mobile_agent_maps_lifecycle_errors(
    monkeypatch,
    result: _KillResult,
    expected_code: int,
    expected_message: str,
) -> None:
    monkeypatch.setattr(mobile_agents, "kill_named_agent", lambda *_a, **_k: result)
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="kill-agent"),
        stdin=io.StringIO('{"schema_version":1,"name":"alpha"}'),
        stderr=stderr,
    )

    assert code == expected_code
    assert expected_message in stderr.getvalue()


def test_retry_mobile_agent_prefers_artifact_prompt_and_allocates_name(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(mobile_agents, "list_all_agents", lambda: [])
    artifact_dir = tmp_path / "projects" / "sase" / "artifacts" / "ace-run" / "ts1"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "raw_xprompt.md").write_text(
        "%name:alpha\nDo work", encoding="utf-8"
    )
    store = tmp_path / "mobile_gateway" / "agent_launch_contexts.jsonl"
    store.parent.mkdir(parents=True)
    store.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agent_name": "alpha",
                "artifact_dir": str(artifact_dir),
                "artifacts_timestamp": "ts1",
                "project": "sase",
                "prompt_snapshot": "fallback prompt",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    captured: list[str] = []

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        captured.append(prompt)
        return [
            AgentLaunchResult(
                pid=333,
                workspace_num=0,
                workspace_dir="/tmp/ws",
                output_path="/tmp/out",
                project_name="sase",
                timestamp="260506_150000",
            )
        ]

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fake_launch)
    monkeypatch.setattr(mobile_agents, "allocate_retry_name", lambda _name: "alpha.1")

    payload = _retry_mobile_agent(
        {"schema_version": 1, "name": "alpha", "request_id": "req-retry-1"}
    )

    assert captured == ["%name:alpha.1\nDo work"]
    assert payload["source_agent"] == "alpha"
    assert payload["launch"]["primary"]["name"] == "alpha.1"
    contexts = store.read_text(encoding="utf-8")
    assert '"agent_name": "alpha.1"' in contexts
    assert '"source_agent_name": "alpha"' in contexts
    assert '"request_id": "req-retry-1"' in contexts


def test_retry_mobile_agent_falls_back_to_mobile_kill_context(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(mobile_agents, "list_all_agents", lambda: [])
    context_dir = tmp_path / "mobile_gateway" / "agent_kill_contexts"
    context_dir.mkdir(parents=True)
    (context_dir / "killed.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agent_name": "killed",
                "raw_prompt": "Do killed work",
            }
        ),
        encoding="utf-8",
    )
    captured: list[str] = []
    monkeypatch.setattr(mobile_agents, "allocate_retry_name", lambda _name: "killed.1")
    monkeypatch.setattr(
        mobile_agents,
        "launch_agents_from_cwd",
        lambda prompt: (
            captured.append(prompt)
            or [
                AgentLaunchResult(
                    pid=334,
                    workspace_num=0,
                    workspace_dir="/tmp/ws",
                    output_path="/tmp/out",
                    project_name="sase",
                    timestamp="260506_150001",
                )
            ]
        ),
    )

    payload = _retry_mobile_agent({"schema_version": 1, "name": "killed"})

    assert captured == ["%name:killed.1\nDo killed work"]
    assert payload["source_agent"] == "killed"


def test_retry_mobile_agent_missing_context_returns_not_found(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(mobile_agents, "list_all_agents", lambda: [])
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="retry-agent"),
        stdin=io.StringIO('{"schema_version":1,"name":"missing"}'),
        stderr=stderr,
    )

    assert code == 4
    assert "No retry context found" in stderr.getvalue()
