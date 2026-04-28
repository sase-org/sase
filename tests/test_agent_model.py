"""Tests for the Agent model and AgentType enum."""

from datetime import datetime, timedelta

from sase.ace.tui.models.agent import (
    Agent,
    AgentType,
    format_compact_duration,
    format_wait_until,
)

# --- Agent Model Tests ---


def test_agent_display_type_running() -> None:
    """Test Agent.display_type for RUNNING type."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workspace_num=1,
        workflow="crs",
    )
    assert agent.display_type == "agent"


def test_agent_display_label() -> None:
    """Test Agent.display_label property."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
    )
    assert agent.display_label == "[agent] my_feature"


def test_agent_start_time_short_with_time() -> None:
    """Test Agent.start_time_short with a valid time."""
    start = datetime(2025, 1, 10, 14, 30, 45)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=start,
    )
    assert agent.start_time_short == "14:30"


def test_agent_start_time_short_without_time() -> None:
    """Test Agent.start_time_short when time is None."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
    )
    assert agent.start_time_short == "?"


def test_agent_duration_display_without_time() -> None:
    """Test Agent.duration_display when time is None."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
    )
    assert agent.duration_display == "?"


def test_agent_duration_display_seconds() -> None:
    """Test Agent.duration_display for seconds only."""
    start = datetime.now() - timedelta(seconds=45)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=start,
    )
    # Should be approximately 45s
    assert "s" in agent.duration_display
    assert "m" not in agent.duration_display


def test_agent_duration_display_minutes() -> None:
    """Test Agent.duration_display for minutes."""
    start = datetime.now() - timedelta(minutes=5, seconds=30)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=start,
    )
    # Should be approximately 5m30s
    assert "m" in agent.duration_display
    assert "h" not in agent.duration_display


def test_agent_duration_display_hours() -> None:
    """Test Agent.duration_display for hours."""
    start = datetime.now() - timedelta(hours=2, minutes=15)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=start,
    )
    # Should be approximately 2h15m
    assert "h" in agent.duration_display


# --- AgentType Enum Tests ---


def test_agent_type_values() -> None:
    """Test AgentType enum values."""
    assert AgentType.RUNNING.value == "run"
    assert AgentType.WORKFLOW.value == "workflow"


def test_agent_optional_fields() -> None:
    """Test Agent with all optional fields."""
    start = datetime.now()
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=start,
        workspace_num=5,
        workflow="crs",
        hook_command="bb_test",
        commit_entry_id="1",
        mentor_profile="profile1",
        mentor_name="mentor1",
        reviewer="critique",
        pid=12345,
        raw_suffix="fix_hook-12345-251230_151429",
    )
    assert agent.workspace_num == 5
    assert agent.workflow == "crs"
    assert agent.hook_command == "bb_test"
    assert agent.commit_entry_id == "1"
    assert agent.mentor_profile == "profile1"
    assert agent.mentor_name == "mentor1"
    assert agent.reviewer == "critique"
    assert agent.pid == 12345
    assert agent.raw_suffix == "fix_hook-12345-251230_151429"


# --- Hidden Step and Appears As Agent Tests ---


def test_agent_is_hidden_step_default() -> None:
    """Test Agent.is_hidden_step defaults to False."""
    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
    )
    assert agent.is_hidden_step is False


def test_agent_is_hidden_step_true() -> None:
    """Test Agent.is_hidden_step can be set to True."""
    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
        is_hidden_step=True,
    )
    assert agent.is_hidden_step is True


def test_agent_appears_as_agent_default() -> None:
    """Test Agent.appears_as_agent defaults to False."""
    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
    )
    assert agent.appears_as_agent is False


def test_agent_appears_as_agent_true() -> None:
    """Test Agent.appears_as_agent can be set to True."""
    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        appears_as_agent=True,
    )
    assert agent.appears_as_agent is True


# --- Anonymous Workflow Display Type Tests ---


def test_agent_get_display_type_named_workflow_collapsed_shows_agent() -> None:
    """Test named workflow shows [agent] when collapsed, [workflow_name] when expanded."""
    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="gh",
        appears_as_agent=True,
        is_anonymous=False,
    )
    assert agent.get_display_type(is_expanded=False) == "agent"
    assert agent.get_display_type(is_expanded=True) == "gh"


# --- format_compact_duration Tests ---


def test_format_compact_duration_seconds_only() -> None:
    assert format_compact_duration(45) == "45s"
    assert format_compact_duration(0) == "0s"
    assert format_compact_duration(1) == "1s"
    assert format_compact_duration(59) == "59s"


def test_format_compact_duration_minutes() -> None:
    assert format_compact_duration(60) == "1m"
    assert format_compact_duration(90) == "1m30s"
    assert format_compact_duration(300) == "5m"
    assert format_compact_duration(605) == "10m05s"


def test_format_compact_duration_hours() -> None:
    assert format_compact_duration(3600) == "1h"
    assert format_compact_duration(3660) == "1h01m"
    assert format_compact_duration(5400) == "1h30m"
    assert format_compact_duration(7200) == "2h"


def test_format_compact_duration_negative_clamps_to_zero() -> None:
    assert format_compact_duration(-5) == "0s"


def test_format_compact_duration_fractional() -> None:
    """Fractional seconds are truncated to int."""
    assert format_compact_duration(90.7) == "1m30s"


# --- wait_duration field Tests ---


def test_wait_duration_bundle_roundtrip() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.gp",
        status="WAITING",
        start_time=datetime.now(),
        wait_duration=300.0,
    )
    bundle = agent.to_bundle_dict()
    assert bundle["wait_duration"] == 300.0

    restored = Agent.from_bundle_dict(bundle)
    assert restored.wait_duration == 300.0


def test_wait_duration_none_by_default() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
    )
    assert agent.wait_duration is None


def test_wait_until_bundle_roundtrip() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.gp",
        status="WAITING",
        start_time=datetime.now(),
        wait_until="2026-04-11T14:30:00",
    )
    bundle = agent.to_bundle_dict()
    assert bundle["wait_until"] == "2026-04-11T14:30:00"

    restored = Agent.from_bundle_dict(bundle)
    assert restored.wait_until == "2026-04-11T14:30:00"


def test_wait_until_none_by_default() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
    )
    assert agent.wait_until is None


# --- format_wait_until Tests ---


def test_format_wait_until_same_day() -> None:
    """Same-day target shows only time."""
    today = datetime.now().replace(hour=14, minute=30, second=0, microsecond=0)
    result = format_wait_until(today.isoformat())
    assert result == "14:30"


def test_format_wait_until_different_day() -> None:
    """Different-day target shows month, day, and time."""
    tomorrow = (datetime.now() + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    result = format_wait_until(tomorrow.isoformat())
    expected = tomorrow.strftime("%b %-d %H:%M")
    assert result == expected
