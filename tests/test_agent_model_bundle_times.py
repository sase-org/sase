"""Bundle serialization tests for time fields, agent types, and list fields."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType


def test_bundle_round_trip_datetime_serialization() -> None:
    """Test that datetime is serialized as ISO string and restored."""
    start = datetime(2025, 12, 25, 14, 30, 45)
    agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.sase",
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
        project_file="/tmp/test.sase",
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
        project_file="/tmp/test.sase",
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
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=None,
    )
    bundle = agent.to_bundle_dict()
    assert bundle["agent_type"] == "workflow"

    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_type == AgentType.WORKFLOW


def test_bundle_round_trip_plan_and_code_time() -> None:
    """Test that plan_times and code_time survive bundle round-trip."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        plan_times=[datetime(2025, 6, 15, 10, 5, 0)],
        code_time=datetime(2025, 6, 15, 10, 10, 0),
        epic_time=datetime(2025, 6, 15, 10, 15, 0),
    )
    bundle = agent.to_bundle_dict()
    assert bundle["plan_times"] == ["2025-06-15T10:05:00"]
    assert bundle["code_time"] == "2025-06-15T10:10:00"
    assert bundle["epic_time"] == "2025-06-15T10:15:00"

    restored = Agent.from_bundle_dict(bundle)
    assert restored.plan_times == [datetime(2025, 6, 15, 10, 5, 0)]
    assert restored.code_time == datetime(2025, 6, 15, 10, 10, 0)
    assert restored.epic_time == datetime(2025, 6, 15, 10, 15, 0)


def test_bundle_backward_compat_plan_time_to_plan_times() -> None:
    """Test that old bundles with plan_time are migrated to plan_times."""
    bundle = {
        "agent_type": "run",
        "cl_name": "test",
        "project_file": "/tmp/test.sase",
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
        project_file="/tmp/test.sase",
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


def test_bundle_round_trip_feedback_plan_paths() -> None:
    """feedback_plan_paths survives bundle serialization with ISO keys."""
    feedback_time = datetime(2025, 6, 15, 10, 6, 0)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        feedback_times=[feedback_time],
        feedback_plan_paths={feedback_time: "/tmp/rejected-plan.md"},
    )

    bundle = agent.to_bundle_dict()
    assert bundle["feedback_plan_paths"] == {
        "2025-06-15T10:06:00": "/tmp/rejected-plan.md"
    }

    restored = Agent.from_bundle_dict(bundle)
    assert restored.feedback_plan_paths == {feedback_time: "/tmp/rejected-plan.md"}


def test_bundle_backward_compat_missing_feedback_plan_paths() -> None:
    """Older bundles without feedback_plan_paths still load with an empty map."""
    bundle = {
        "agent_type": "run",
        "cl_name": "test",
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": "2025-06-15T10:00:00",
        "feedback_times": ["2025-06-15T10:06:00"],
    }

    restored = Agent.from_bundle_dict(bundle)

    assert restored.feedback_times == [datetime(2025, 6, 15, 10, 6, 0)]
    assert restored.feedback_plan_paths == {}


def test_bundle_backward_compat_feedback_time_to_feedback_times() -> None:
    """Test that old bundles with feedback_time/questions_time are migrated."""
    bundle = {
        "agent_type": "run",
        "cl_name": "test",
        "project_file": "/tmp/test.sase",
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
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=None,
        extra_files=["/tmp/plan.md", "/tmp/diff.txt"],
        waiting_for=["agent-1", "agent-2"],
    )
    bundle = agent.to_bundle_dict()
    restored = Agent.from_bundle_dict(bundle)

    assert restored.extra_files == ["/tmp/plan.md", "/tmp/diff.txt"]
    assert restored.waiting_for == ["agent-1", "agent-2"]
