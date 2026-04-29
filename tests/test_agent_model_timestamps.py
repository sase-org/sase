"""Tests for Agent.timestamps_display."""

import json
from datetime import datetime
from pathlib import Path

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models._loaders._done_loaders import (
    load_done_agents_from_snapshot,
)
from sase.core.agent_scan_facade import scan_agent_artifacts_python


def test_timestamps_display_with_plan_and_code() -> None:
    """Test timestamps_display includes PLAN and CODE lines when set."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        run_start_time=datetime(2025, 6, 15, 10, 0, 5),
        plan_times=[datetime(2025, 6, 15, 10, 5, 0)],
        code_time=datetime(2025, 6, 15, 10, 10, 0),
        stop_time=datetime(2025, 6, 15, 10, 20, 0),
    )
    display = agent.timestamps_display
    lines = display.split("\n")
    # Strip indent from continuation lines
    tags = [line.strip().split(" | ")[0].strip() for line in lines]
    assert tags == ["WAIT", "BEGIN", "PLAN", "CODE", "END"]


def test_timestamps_display_full_with_feedback_and_questions() -> None:
    """Test timestamps_display includes FBACK and QUEST in correct order."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        run_start_time=datetime(2025, 6, 15, 10, 0, 5),
        plan_times=[datetime(2025, 6, 15, 10, 5, 0)],
        feedback_times=[datetime(2025, 6, 15, 10, 6, 0)],
        questions_times=[datetime(2025, 6, 15, 10, 7, 0)],
        code_time=datetime(2025, 6, 15, 10, 10, 0),
        stop_time=datetime(2025, 6, 15, 10, 20, 0),
    )
    display = agent.timestamps_display
    lines = display.split("\n")
    tags = [line.strip().split(" | ")[0].strip() for line in lines]
    assert tags == ["WAIT", "BEGIN", "PLAN", "FBACK", "QUEST", "CODE", "END"]


def test_timestamps_display_feedback_only() -> None:
    """Test timestamps_display shows FBACK without QUEST."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        plan_times=[datetime(2025, 6, 15, 10, 5, 0)],
        feedback_times=[datetime(2025, 6, 15, 10, 6, 0)],
        stop_time=datetime(2025, 6, 15, 10, 20, 0),
    )
    display = agent.timestamps_display
    lines = display.split("\n")
    tags = [line.strip().split(" | ")[0].strip() for line in lines]
    assert tags == ["BEGIN", "PLAN", "FBACK", "END"]


def test_timestamps_display_questions_only() -> None:
    """Test timestamps_display shows QUEST without FBACK."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        questions_times=[datetime(2025, 6, 15, 10, 7, 0)],
        stop_time=datetime(2025, 6, 15, 10, 20, 0),
    )
    display = agent.timestamps_display
    lines = display.split("\n")
    tags = [line.strip().split(" | ")[0].strip() for line in lines]
    assert tags == ["BEGIN", "QUEST", "END"]


def test_timestamps_display_plan_only() -> None:
    """Test timestamps_display shows PLAN without CODE when code_time is None."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        plan_times=[datetime(2025, 6, 15, 10, 5, 0)],
        stop_time=datetime(2025, 6, 15, 10, 20, 0),
    )
    display = agent.timestamps_display
    lines = display.split("\n")
    tags = [line.strip().split(" | ")[0].strip() for line in lines]
    assert tags == ["BEGIN", "PLAN", "END"]


def test_timestamps_display_multiple_plans() -> None:
    """Test timestamps_display shows one PLAN per proposal (feedback rounds)."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        plan_times=[
            datetime(2025, 6, 15, 10, 5, 0),
            datetime(2025, 6, 15, 10, 8, 0),
        ],
        feedback_times=[datetime(2025, 6, 15, 10, 6, 0)],
        code_time=datetime(2025, 6, 15, 10, 10, 0),
        stop_time=datetime(2025, 6, 15, 10, 20, 0),
    )
    display = agent.timestamps_display
    lines = display.split("\n")
    tags = [line.strip().split(" | ")[0].strip() for line in lines]
    # Chronological: PLAN(10:05) → FBACK(10:06) → PLAN(10:08) → CODE(10:10)
    assert tags == ["BEGIN", "PLAN", "FBACK", "PLAN", "CODE", "END"]


def test_timestamps_display_no_plan_or_code() -> None:
    """Test timestamps_display unchanged when plan_times is empty and code_time is None."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        stop_time=datetime(2025, 6, 15, 10, 20, 0),
    )
    display = agent.timestamps_display
    lines = display.split("\n")
    tags = [line.strip().split(" | ")[0].strip() for line in lines]
    assert tags == ["BEGIN", "END"]


def test_timestamps_display_wait_tag_for_waiting_status() -> None:
    """WAITING agents show WAIT timestamp, not BEGIN."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.gp",
        status="WAITING",
        start_time=datetime(2026, 4, 10, 22, 0, 0),
        wait_duration=600.0,
    )
    display = agent.timestamps_display
    assert "WAIT" in display
    assert "BEGIN" not in display


def test_snapshot_agent_timestamps_display_includes_scalar_plan(
    tmp_path: Path,
) -> None:
    artifact_dir = (
        tmp_path / "projects" / "myproj" / "artifacts" / "ace-run" / "20260427110000"
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"plan_submitted_at": "2026-04-27T11:05:00Z"}),
        encoding="utf-8",
    )
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "outcome": "completed",
                "cl_name": "feature_plan",
                "project_file": "/tmp/myproj.gp",
            }
        ),
        encoding="utf-8",
    )

    snapshot = scan_agent_artifacts_python(tmp_path / "projects")
    agents = load_done_agents_from_snapshot(snapshot, {}, {})

    assert len(agents) == 1
    tags = [
        line.strip().split(" | ")[0].strip()
        for line in agents[0].timestamps_display.split("\n")
    ]
    assert tags == ["BEGIN", "PLAN"]
