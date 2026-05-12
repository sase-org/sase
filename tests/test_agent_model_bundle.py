"""Tests for Agent bundle serialization (to_bundle_dict / from_bundle_dict)."""

import json
from datetime import datetime
from pathlib import Path

from sase.ace.archive_search_text import (
    ARCHIVE_BUNDLE_SCHEMA_VERSION,
    ARCHIVE_REVISION,
    ARCHIVE_SEARCH_SCRUBBER_VERSION,
)
from sase.ace.tui.models.agent import Agent, AgentType, AttemptRecord


def test_bundle_round_trip_basic() -> None:
    """Test to_bundle_dict / from_bundle_dict round-trip with basic fields."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        workspace_num=3,
        raw_suffix="20250615103000",
    )
    bundle = agent.to_bundle_dict()
    restored = Agent.from_bundle_dict(bundle)

    assert restored.agent_type == AgentType.RUNNING
    assert restored.cl_name == "my_feature"
    assert restored.project_file == "/tmp/test.sase"
    assert restored.status == "DONE"
    assert restored.start_time == datetime(2025, 6, 15, 10, 30, 0)
    assert restored.workspace_num == 3
    assert restored.raw_suffix == "20250615103000"
    assert restored.identity == agent.identity


def test_bundle_includes_archive_schema_metadata() -> None:
    """New bundles carry archive schema and revision metadata."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        raw_suffix="20250615103000",
    )

    bundle = agent.to_bundle_dict()

    assert bundle["bundle_schema_version"] == ARCHIVE_BUNDLE_SCHEMA_VERSION
    assert bundle["archive_revision"] == ARCHIVE_REVISION
    assert bundle["archive_search_scrubber_version"] == ARCHIVE_SEARCH_SCRUBBER_VERSION


def test_bundle_search_projection_collects_and_scrubs_files(tmp_path: Path) -> None:
    """Archive search text is bounded and redacts obvious secrets."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    chat_path = tmp_path / "chat.md"
    response_path = tmp_path / "response.md"
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    attempt_reply = attempt_dir / "live_reply.md"
    timestamps = attempt_dir / "live_reply_timestamps.jsonl"
    (artifacts_dir / "raw_xprompt.md").write_text("Prompt sk-test1234567890abcdef")
    (artifacts_dir / "live_reply.md").write_text("Live reply")
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"chat_path": str(chat_path)})
    )
    chat_path.write_text("Chat Bearer abcdefghijklmnopqrstuvwxyz")
    response_path.write_text("Response api_key=abcdef1234567890")
    attempt_reply.write_text("Attempt reply ghp_abcdefghijklmnopqrstuvwx123456")
    timestamps.write_text("")
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        raw_suffix="20250615103000",
        artifacts_dir=str(artifacts_dir),
        response_path=str(response_path),
        attempt_history=[
            AttemptRecord(
                attempt_number=1,
                status="failed",
                start_epoch=0,
                end_epoch=1,
                model=None,
                used_fallback=False,
                error_snippet="",
                error_full="",
                live_reply_path=str(attempt_reply),
                timestamps_path=str(timestamps),
            )
        ],
    )

    bundle = agent.to_bundle_dict()
    search_text = bundle["archive_search_text"]

    assert "Prompt" in search_text
    assert "Live reply" in search_text
    assert "Chat Bearer [REDACTED]" in search_text
    assert "Response api_key=[REDACTED]" in search_text
    assert "Attempt reply [REDACTED]" in search_text
    assert "sk-test1234567890abcdef" not in search_text
    assert len(search_text) <= 128 * 1024


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


# --- Old-bundle dismissed-name synthesis (sase-10 phase 5) ---


def test_old_bundle_synthesizes_prefixed_agent_name_from_stop_time() -> None:
    """Bundles missing ``agent_name`` get a prefixed name from stop_time."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "feature_x",
        "project_file": "/tmp/test.sase",
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
        "project_file": "/tmp/test.sase",
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
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 9, 0, 0).isoformat(),
        "raw_suffix": "20260428090000",
        "agent_name": "260428.foo",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "260428.foo"


def test_bundle_preserves_stored_unprefixed_name() -> None:
    """A stored ``agent_name`` without a prefix is permanent and preserved."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "x",
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 9, 0, 0).isoformat(),
        "raw_suffix": "20260428090000",
        "agent_name": "foo",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "foo"


def test_bundle_preserves_plan_chain_stored_name() -> None:
    """Plan-chain names such as ``by.plan`` are not dismissal-prefixed."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "feature_by",
        "project_file": "/tmp/test.sase",
        "status": "PLAN DONE",
        "start_time": datetime(2026, 5, 9, 12, 41, 56).isoformat(),
        "stop_time": datetime(2026, 5, 9, 13, 6, 29).isoformat(),
        "raw_suffix": "20260509124156",
        "agent_name": "by.plan",
        "role_suffix": ".plan",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "by.plan"


def test_bundle_round_trips_tale_done_status() -> None:
    """A revived tale workflow with ``TALE DONE`` survives bundle round-tripping."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "feature_by",
        "project_file": "/tmp/test.sase",
        "status": "TALE DONE",
        "start_time": datetime(2026, 5, 11, 12, 0, 0).isoformat(),
        "stop_time": datetime(2026, 5, 11, 13, 0, 0).isoformat(),
        "raw_suffix": "20260511120000",
        "agent_name": "by.plan",
        "role_suffix": ".plan",
        "plan_action": "tale",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.status == "TALE DONE"
    assert restored.plan_action == "tale"
    assert restored.agent_name == "by.plan"


def test_old_bundle_synthesis_skips_workflow_children() -> None:
    """Workflow children inherit identity from their parent — leave them alone."""
    bundle = {
        "agent_type": AgentType.WORKFLOW.value,
        "cl_name": "feature",
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 9, 0, 0).isoformat(),
        "parent_timestamp": "20260428090000",
        "raw_suffix": "20260428090000",
        "step_index": 1,
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name is None
