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


# --- Bundle Serialization Tests ---


def test_bundle_round_trip_basic() -> None:
    """Test to_bundle_dict / from_bundle_dict round-trip with basic fields."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        workspace_num=3,
        raw_suffix="20250615103000",
    )
    bundle = agent.to_bundle_dict()
    restored = Agent.from_bundle_dict(bundle)

    assert restored.agent_type == AgentType.RUNNING
    assert restored.cl_name == "my_feature"
    assert restored.project_file == "/tmp/test.gp"
    assert restored.status == "DONE"
    assert restored.start_time == datetime(2025, 6, 15, 10, 30, 0)
    assert restored.workspace_num == 3
    assert restored.raw_suffix == "20250615103000"
    assert restored.identity == agent.identity


def test_bundle_round_trip_datetime_serialization() -> None:
    """Test that datetime is serialized as ISO string and restored."""
    start = datetime(2025, 12, 25, 14, 30, 45)
    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=start,
        workflow="gh",
    )
    bundle = agent.to_bundle_dict()

    # Verify datetime is serialized as ISO string
    assert bundle["start_time"] == "2025-12-25T14:30:45"

    # Verify round-trip preserves the datetime
    restored = Agent.from_bundle_dict(bundle)
    assert restored.start_time == start


def test_bundle_round_trip_none_start_time() -> None:
    """Test round-trip when start_time is None."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
    )
    bundle = agent.to_bundle_dict()
    restored = Agent.from_bundle_dict(bundle)
    assert restored.start_time is None


def test_bundle_round_trip_workflow_child() -> None:
    """Test round-trip for a workflow child step."""
    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
        parent_workflow="gh",
        parent_timestamp="20250615103000",
        step_name="push",
        step_type="agent",
        step_index=2,
        total_steps=5,
    )
    bundle = agent.to_bundle_dict()
    restored = Agent.from_bundle_dict(bundle)

    assert restored.parent_workflow == "gh"
    assert restored.parent_timestamp == "20250615103000"
    assert restored.step_name == "push"
    assert restored.step_type == "agent"
    assert restored.step_index == 2
    assert restored.total_steps == 5
    assert restored.is_workflow_child


def test_bundle_round_trip_agent_type_serialized_as_string() -> None:
    """Test that AgentType is serialized as its string value."""
    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
    )
    bundle = agent.to_bundle_dict()
    assert bundle["agent_type"] == "workflow"

    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_type == AgentType.WORKFLOW


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


def test_bundle_round_trip_plan_and_code_time() -> None:
    """Test that plan_times and code_time survive bundle round-trip."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        plan_times=[datetime(2025, 6, 15, 10, 5, 0)],
        code_time=datetime(2025, 6, 15, 10, 10, 0),
    )
    bundle = agent.to_bundle_dict()
    assert bundle["plan_times"] == ["2025-06-15T10:05:00"]
    assert bundle["code_time"] == "2025-06-15T10:10:00"

    restored = Agent.from_bundle_dict(bundle)
    assert restored.plan_times == [datetime(2025, 6, 15, 10, 5, 0)]
    assert restored.code_time == datetime(2025, 6, 15, 10, 10, 0)


def test_bundle_backward_compat_plan_time_to_plan_times() -> None:
    """Test that old bundles with plan_time are migrated to plan_times."""
    bundle = {
        "agent_type": "run",
        "cl_name": "test",
        "project_file": "/tmp/test.gp",
        "status": "DONE",
        "start_time": "2025-06-15T10:00:00",
        "plan_time": "2025-06-15T10:05:00",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.plan_times == [datetime(2025, 6, 15, 10, 5, 0)]


def test_bundle_round_trip_feedback_and_questions_times() -> None:
    """Test that feedback_times and questions_times survive bundle round-trip."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        feedback_times=[datetime(2025, 6, 15, 10, 6, 0)],
        questions_times=[datetime(2025, 6, 15, 10, 7, 0)],
    )
    bundle = agent.to_bundle_dict()
    assert bundle["feedback_times"] == ["2025-06-15T10:06:00"]
    assert bundle["questions_times"] == ["2025-06-15T10:07:00"]

    restored = Agent.from_bundle_dict(bundle)
    assert restored.feedback_times == [datetime(2025, 6, 15, 10, 6, 0)]
    assert restored.questions_times == [datetime(2025, 6, 15, 10, 7, 0)]


def test_bundle_backward_compat_feedback_time_to_feedback_times() -> None:
    """Test that old bundles with feedback_time/questions_time are migrated."""
    bundle = {
        "agent_type": "run",
        "cl_name": "test",
        "project_file": "/tmp/test.gp",
        "status": "DONE",
        "start_time": "2025-06-15T10:00:00",
        "feedback_time": "2025-06-15T10:06:00",
        "questions_time": "2025-06-15T10:07:00",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.feedback_times == [datetime(2025, 6, 15, 10, 6, 0)]
    assert restored.questions_times == [datetime(2025, 6, 15, 10, 7, 0)]


def test_bundle_round_trip_list_fields() -> None:
    """Test that list fields (extra_files, waiting_for) survive round-trip."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
        extra_files=["/tmp/plan.md", "/tmp/diff.txt"],
        waiting_for=["agent-1", "agent-2"],
    )
    bundle = agent.to_bundle_dict()
    restored = Agent.from_bundle_dict(bundle)

    assert restored.extra_files == ["/tmp/plan.md", "/tmp/diff.txt"]
    assert restored.waiting_for == ["agent-1", "agent-2"]


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


# --- Old-bundle dismissed-name synthesis (sase-10 phase 5) ---


def test_old_bundle_synthesizes_prefixed_agent_name_from_stop_time() -> None:
    """Bundles missing ``agent_name`` get a prefixed name from stop_time."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "feature_x",
        "project_file": "/tmp/test.gp",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 9, 0, 0).isoformat(),
        "stop_time": datetime(2026, 4, 28, 10, 30, 0).isoformat(),
        "raw_suffix": "20260428090000",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "260428.feature_x"


def test_old_bundle_synthesis_falls_back_to_raw_suffix_date() -> None:
    """Without stop_time/start_time, raw_suffix supplies the date and base."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "unknown",
        "project_file": "/tmp/test.gp",
        "status": "DONE",
        "start_time": None,
        "raw_suffix": "20260501123045",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "260501.20260501123045"


def test_old_bundle_synthesis_skips_already_prefixed_name() -> None:
    """Bundles that already carry a prefixed name are left alone."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "foo",
        "project_file": "/tmp/test.gp",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 9, 0, 0).isoformat(),
        "raw_suffix": "20260428090000",
        "agent_name": "260428.foo",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "260428.foo"


def test_old_bundle_synthesis_strips_legacy_unprefixed_name() -> None:
    """A legacy ``agent_name`` without a prefix is upgraded to the prefixed form."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "x",
        "project_file": "/tmp/test.gp",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 9, 0, 0).isoformat(),
        "raw_suffix": "20260428090000",
        "agent_name": "foo",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "260428.foo"


def test_old_bundle_synthesis_skips_workflow_children() -> None:
    """Workflow children inherit identity from their parent — leave them alone."""
    bundle = {
        "agent_type": AgentType.WORKFLOW.value,
        "cl_name": "feature",
        "project_file": "/tmp/test.gp",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 9, 0, 0).isoformat(),
        "parent_timestamp": "20260428090000",
        "raw_suffix": "20260428090000",
        "step_index": 1,
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name is None
