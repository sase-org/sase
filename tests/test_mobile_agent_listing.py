"""Tests for mobile agent listing payloads."""

from __future__ import annotations

from pathlib import Path

from sase import project_display_names as pdn
from sase.integrations import mobile_agents
from sase.integrations import _mobile_agent_deps as mobile_agent_deps
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


def test_list_mobile_agents_pushes_project_to_shared_listing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    _known_project(tmp_path, "sase")
    calls: list[str | None] = []

    def fake_list_running_agents(
        *,
        project: str | None = None,
    ):
        calls.append(project)
        return [_agent(tmp_path, project=project or "other")]

    monkeypatch.setattr(
        mobile_agent_deps,
        "_real_list_running_agents",
        fake_list_running_agents,
    )

    payload = _list_mobile_agents({"schema_version": 1, "project": "sase"})

    assert calls == ["sase"]
    assert payload["total_count"] == 1
    assert payload["agents"][0]["project"] == "sase"


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
    monitor.agent_family = "alpha"
    monitor.agent_family_role = "monitor"
    monitor.role_suffix = "--mon"
    monitor.monitor_id = "m123"
    monitor.monitor_state = "running"
    monitor.monitor_label = "just check"
    monitor.monitor_command = "just check-full"
    monitor.monitor_start_status = "TESTING"
    monitor.monitor_stop_status = "TESTED"
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
        "start_status": "TESTING",
        "stop_status": "TESTED",
        "accent": "#6FC4FF",
    }
    assert agent["actions"]["can_kill"] is True


def test_list_mobile_agents_monitor_starter_is_not_monitor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    starter = _agent(tmp_path, name="alpha--0", status="DONE")
    starter.agent_family = "alpha"
    starter.agent_family_role = "root"
    starter.role_suffix = "--0"
    starter.monitor_id = "m123"
    monkeypatch.setattr(
        mobile_agents,
        "list_running_agents",
        lambda: [starter],
    )

    payload = _list_mobile_agents({"schema_version": 1})
    agent = payload["agents"][0]

    assert agent["is_monitor"] is False
    assert agent["monitor"]["id"] == "m123"
