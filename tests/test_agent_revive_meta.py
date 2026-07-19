"""Tests for ``_restore_agent_meta`` and on-disk meta merging."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import find_named_agent
from sase.ace.tui.actions.agents._revive import AgentRevivalMixin
from sase.ace.tui.models.agent import Agent, AgentType

from tests._agent_revive_helpers import RealArtifactReviveApp, make_agent, patch_home


def test_restore_agent_meta_writes_loader_relevant_fields(tmp_path: Path) -> None:
    run_start = datetime(2024, 1, 1, 12, 5, 0)
    stop_time = datetime(2024, 1, 1, 12, 35, 0)
    plan_times = [
        datetime(2024, 1, 1, 12, 10, 0),
        datetime(2024, 1, 1, 12, 20, 0),
    ]
    feedback_times = [datetime(2024, 1, 1, 12, 22, 0)]
    questions_times = [datetime(2024, 1, 1, 12, 25, 0)]
    retry_times = [
        datetime(2024, 1, 1, 12, 27, 0),
        datetime(2024, 1, 1, 12, 29, 0),
    ]
    epic_time = datetime(2024, 1, 1, 12, 30, 0)
    agent = make_agent(
        status="PLAN COMMITTED",
        model="claude-opus",
        llm_provider="claude",
        vcs_provider="GitHub",
        agent_name="@d.1",
        waiting_for=["@f"],
        approve=True,
        hidden=True,
        role_suffix=".plan",
        parent_timestamp="20240101120000",
        workspace_num=7,
        response_path="~/.sase/chat/foo.md",
        run_start_time=run_start,
        stop_time=stop_time,
        plan_times=plan_times,
        feedback_times=feedback_times,
        questions_times=questions_times,
        question_request_path="/tmp/question_request.json",
        question_response_path="/tmp/question_response.json",
        question_session_id="session-1",
        retry_times=retry_times,
        epic_time=epic_time,
        tag="backend",
    )

    AgentRevivalMixin._restore_agent_meta(agent, tmp_path)
    data = json.loads((tmp_path / "agent_meta.json").read_text())

    assert data["model"] == "claude-opus"
    assert data["llm_provider"] == "claude"
    assert data["vcs_provider"] == "GitHub"
    assert data["name"] == "@d.1"
    assert data["tribe"] == "backend"
    assert "tag" not in data
    assert data["wait_for"] == ["@f"]
    assert data["approve"] is True
    assert data["hidden"] is True
    assert data["role_suffix"] == ".plan"
    assert data["parent_timestamp"] == "20240101120000"
    assert data["workspace_num"] == 7
    assert data["chat_path"] == "~/.sase/chat/foo.md"
    assert data["run_started_at"] == run_start.isoformat()
    assert data["stopped_at"] == stop_time.isoformat()
    assert data["plan_submitted_at"] == [t.isoformat() for t in plan_times]
    assert data["epic_started_at"] == epic_time.isoformat()
    assert data["feedback_submitted_at"] == feedback_times[0].isoformat()
    assert data["questions_submitted_at"] == questions_times[0].isoformat()
    assert data["question_request_path"] == "/tmp/question_request.json"
    assert data["question_response_path"] == "/tmp/question_response.json"
    assert data["question_session_id"] == "session-1"
    assert data["retry_started_at"] == [t.isoformat() for t in retry_times]
    assert data["plan"] is True
    assert data["plan_approved"] is True
    assert data["plan_action"] == "commit"


def test_restore_agent_meta_working_plan_statuses_restore_plan_markers(
    tmp_path: Path,
) -> None:
    tale_dir = tmp_path / "tale"
    tale_dir.mkdir()
    tale_agent = make_agent(
        status="WORKING TALE",
        role_suffix=".code",
        parent_timestamp="20240101120000",
    )

    AgentRevivalMixin._restore_agent_meta(tale_agent, tale_dir)
    data = json.loads((tale_dir / "agent_meta.json").read_text())

    assert data["plan"] is True
    assert data["plan_approved"] is True
    assert data["plan_action"] == "tale"

    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    plan_agent = make_agent(
        status="WORKING PLAN",
        role_suffix=".code",
        parent_timestamp="20240101120000",
    )

    AgentRevivalMixin._restore_agent_meta(plan_agent, plan_dir)
    data = json.loads((plan_dir / "agent_meta.json").read_text())

    assert data["plan"] is True
    assert data["plan_approved"] is True
    assert "plan_action" not in data


def test_restore_agent_meta_merges_existing_metadata(tmp_path: Path) -> None:
    agent = make_agent(
        agent_type=AgentType.RUNNING,
        raw_suffix="20260504224829",
        agent_name="abb_3",
        model="claude-sonnet",
        workspace_dir="/tmp/workspace",
    )
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"legacy_field": "preserve", "model": "old-model"})
    )

    AgentRevivalMixin._restore_agent_meta(agent, tmp_path)
    data = json.loads((tmp_path / "agent_meta.json").read_text())

    assert data["legacy_field"] == "preserve"
    assert data["model"] == "claude-sonnet"
    assert data["name"] == "abb_3"
    assert data["workspace_dir"] == "/tmp/workspace"


def test_restore_agent_meta_preserves_bundle_unprefixed_name(tmp_path: Path) -> None:
    """Revive restoration must not write a synthesized dismissal prefix."""
    agent = Agent.from_bundle_dict(
        {
            "agent_type": AgentType.RUNNING.value,
            "cl_name": "feature_by",
            "project_file": "/tmp/projects/proj/proj.sase",
            "status": "PLAN DONE",
            "start_time": datetime(2026, 5, 9, 12, 41, 56).isoformat(),
            "stop_time": datetime(2026, 5, 9, 13, 6, 29).isoformat(),
            "raw_suffix": "20260509124156",
            "agent_name": "by.plan",
            "role_suffix": ".plan",
        }
    )

    AgentRevivalMixin._restore_agent_meta(agent, tmp_path)
    data = json.loads((tmp_path / "agent_meta.json").read_text())

    assert agent.agent_name == "by.plan"
    assert data["name"] == "by.plan"


def test_revive_existing_meta_without_name_preserves_stored_lookup(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / ".sase" / "projects" / "proj" / "proj.sase"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("")
    artifact_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260504224829"
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(json.dumps({"model": "old-model"}))

    app = RealArtifactReviveApp()
    agent = make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature_a",
        project_file=str(project_file),
        raw_suffix="20260504224829",
        agent_name="260504.abb_3",
        workflow="ace-run",
        artifacts_dir=str(artifact_dir),
    )
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with (
        patch_home(tmp_path),
        patch.dict(os.environ, {"HOME": str(tmp_path)}),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
    ):
        app._do_revive_agent(agent)
        resolved = find_named_agent("260504.abb_3")

    data = json.loads((artifact_dir / "agent_meta.json").read_text())
    assert data["model"] == "old-model"
    assert data["name"] == "260504.abb_3"
    assert resolved is not None
    assert resolved.is_done
    assert resolved.artifacts_dir == str(artifact_dir)
