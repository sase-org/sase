"""Tests for launching mobile text agents."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from sase.agent.launcher import AgentLaunchResult
from sase.integrations import mobile_agents
from sase.integrations.mobile_agents import (
    _launch_mobile_text_agents,
    handle_mobile_agent_bridge,
)
from tests._mobile_agents_fixtures import _known_project


def test_mobile_name_guard_recognizes_id_with_only_tribe_keyword() -> None:
    assert mobile_agents._prompt_has_name_directive("%id(tribe=review)\nDo work")


def test_launch_mobile_text_agents_normalizes_prompt_and_returns_slots(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

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
            "request_id": "req-text-1",
            "name": "mobile.demo",
            "provider": "codex",
            "model": "gpt-5.6-sol",
        }
    )

    assert captured == ["%id:mobile.demo\n%model:codex/gpt-5.6-sol\n#gh:sase Fix it"]
    assert payload["primary"] == payload["slots"][0]
    assert payload["primary"]["name"] == "mobile.demo"
    assert [slot["status"] for slot in payload["slots"]] == ["launched", "launched"]
    assert payload["slots"][0]["artifact_dir"].endswith(
        "/projects/home/artifacts/ace-run/202605/06/20260506143000"
    )
    contexts = (tmp_path / "mobile_gateway" / "agent_launch_contexts.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"agent_name": "mobile.demo"' in contexts
    assert '"request_id": "req-text-1"' in contexts


def test_launch_mobile_text_agents_persists_known_project_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    workspace = _known_project(tmp_path, "sase")
    captured_cwds: list[str] = []

    def fake_launch(_prompt: str) -> list[AgentLaunchResult]:
        captured_cwds.append(str(Path.cwd()))
        return [
            AgentLaunchResult(
                pid=111,
                workspace_num=0,
                workspace_dir=str(workspace),
                output_path="/tmp/out",
                project_name="sase",
                timestamp="260506_143000",
            )
        ]

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fake_launch)

    _launch_mobile_text_agents(
        {
            "schema_version": 1,
            "prompt": "Do work",
            "name": "mobile.project",
            "project": "sase",
            "device_id": "device/one",
        }
    )

    assert captured_cwds == [str(workspace)]
    rows = [
        json.loads(line)
        for line in (tmp_path / "mobile_gateway" / "agent_launch_contexts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert rows[-1]["project"] == "sase"
    assert rows[-1]["project_context"]["context_id"] == "project:sase"
    assert rows[-1]["project_context"]["project_file"].endswith(
        "/projects/sase/sase.sase"
    )
    device_context = json.loads(
        (
            tmp_path / "mobile_gateway" / "device_project_contexts" / "device-one.json"
        ).read_text(encoding="utf-8")
    )
    assert device_context["project_context"]["context_id"] == "project:sase"


def test_launch_mobile_text_agents_rejects_path_project_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    with pytest.raises(Exception, match="not a path"):
        _launch_mobile_text_agents(
            {
                "schema_version": 1,
                "prompt": "Do work",
                "project": "../sase",
            }
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


def test_launch_mobile_text_agents_rejects_reserved_family_separator_name() -> None:
    with pytest.raises(Exception, match="cannot contain '--'"):
        _launch_mobile_text_agents(
            {
                "schema_version": 1,
                "prompt": "Do work",
                "name": "mobile--demo",
            }
        )


def test_launch_mobile_text_dry_run_validates_prompt_name() -> None:
    with pytest.raises(Exception, match="cannot contain '--'"):
        _launch_mobile_text_agents(
            {
                "schema_version": 1,
                "prompt": "%id:dry--run\nDo work",
                "dry_run": True,
            }
        )


def test_launch_mobile_text_dry_run_does_not_spawn(monkeypatch) -> None:
    def fail_launch(_prompt: str) -> list[AgentLaunchResult]:
        raise AssertionError("dry run should not launch")

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fail_launch)

    payload = _launch_mobile_text_agents(
        {"schema_version": 1, "prompt": "%id:dry\nDo work", "dry_run": True}
    )

    assert payload["primary"] == {
        "slot_id": "0",
        "name": "dry",
        "status": "dry_run",
        "artifact_dir": None,
        "message": "launch request validated",
    }


def test_launch_mobile_text_dry_run_returns_concrete_indexed_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        "sase.agent.names._registry.get_reserved_agent_names",
        lambda: {"build-1"},
    )

    payload = _launch_mobile_text_agents(
        {"schema_version": 1, "prompt": "%id:build-@\nDo work", "dry_run": True}
    )

    assert payload["primary"]["name"] == "build-0"
