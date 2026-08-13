"""Tests for mobile agent listing payloads."""

from __future__ import annotations

from pathlib import Path

from sase import project_display_names as pdn
from sase.integrations import mobile_agents
from sase.integrations.mobile_agents import _list_mobile_agents
from tests._mobile_agents_fixtures import _agent, _known_project
from tests._project_display_case import ProjectDisplayCase


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


def test_list_mobile_agents_humanizes_display_subtitle_project(
    monkeypatch,
    tmp_path: Path,
    project_display_case: ProjectDisplayCase,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    project_display_case.write_project_layout(tmp_path / "projects")
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)
    monkeypatch.setattr(
        mobile_agents,
        "list_running_agents",
        lambda: [
            _agent(
                tmp_path,
                project=project_display_case.project_key,
            )
        ],
    )

    payload = _list_mobile_agents({"schema_version": 1})
    agent = payload["agents"][0]

    assert agent["project"] == project_display_case.project_key
    assert agent["display"]["subtitle"] == (
        f"{project_display_case.project_label} - codex - gpt-5.6-sol"
    )
    assert project_display_case.project_key not in agent["display"]["subtitle"]


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


def test_list_mobile_agents_projects_starting_agent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        mobile_agents,
        "list_running_agents",
        lambda: [
            _agent(
                tmp_path,
                name="launching",
                status="STARTING",
            )
        ],
    )

    payload = _list_mobile_agents({"schema_version": 1})
    agent = payload["agents"][0]

    assert agent["status"] == "starting"
    assert agent["display"]["status_label"] == "Starting"
    assert agent["actions"]["can_kill"] is True


def test_list_mobile_agents_projects_monitor_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monitor = _agent(tmp_path, name="alpha--mon", status="MONITORING")
    monitor.monitor_id = "m123"
    monitor.monitor_state = "running"
    monitor.monitor_label = "just check"
    monitor.monitor_command = "just check-full"
    monkeypatch.setattr(
        mobile_agents,
        "list_running_agents",
        lambda: [monitor],
    )

    payload = _list_mobile_agents({"schema_version": 1})
    agent = payload["agents"][0]

    assert agent["is_monitor"] is True
    assert agent["monitor"] == {
        "id": "m123",
        "state": "running",
        "label": "just check",
        "command": "just check-full",
        "exit_code": None,
    }
    assert agent["actions"]["can_kill"] is True
