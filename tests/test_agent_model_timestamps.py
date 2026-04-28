"""Tests for Agent.timestamps_display."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType


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
