"""Tests for Agent bundle serialization (to_bundle_dict / from_bundle_dict)."""

import json
from datetime import datetime
from pathlib import Path

from sase.ace.tui.models.agent import (
    Agent,
    AgentType,
    AttemptRecord,
    LinkedRepoMetadata,
)


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
    assert "presented_agent_name" not in bundle
    restored = Agent.from_bundle_dict(bundle)

    assert restored.agent_type == AgentType.RUNNING
    assert restored.cl_name == "my_feature"
    assert restored.project_file == "/tmp/test.sase"
    assert restored.status == "DONE"
    assert restored.start_time == datetime(2025, 6, 15, 10, 30, 0)
    assert restored.workspace_num == 3
    assert restored.raw_suffix == "20250615103000"
    assert restored.identity == agent.identity


def test_bundle_round_trip_preserves_agent_tribe() -> None:
    """Dismissed bundles preserve the agent tribe for revive restoration."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        raw_suffix="20250615103000",
        tribe="backend",
    )

    bundle = agent.to_bundle_dict()
    restored = Agent.from_bundle_dict(bundle)

    assert bundle["tribe"] == "backend"
    assert "tag" not in bundle
    assert restored.tribe == "backend"


def test_bundle_loads_legacy_tag_as_tribe() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        raw_suffix="20250615103000",
    )
    bundle = agent.to_bundle_dict()
    bundle.pop("tribe")
    bundle["tag"] = "legacy"

    restored = Agent.from_bundle_dict(bundle)

    assert restored.tribe == "legacy"


def test_bundle_round_trip_preserves_plan_association() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        plan_path="/tmp/plan.md",
        epic_bead_id="sase-1",
        phase_bead_id="sase-1.2",
    )

    restored = Agent.from_bundle_dict(agent.to_bundle_dict())

    assert restored.plan_path == "/tmp/plan.md"
    assert restored.epic_bead_id == "sase-1"
    assert restored.phase_bead_id == "sase-1.2"


def test_bundle_round_trip_linked_repos() -> None:
    """Linked repo metadata is stored as JSON-native dicts and restored."""
    linked_repos = (
        LinkedRepoMetadata(
            name="sase-core",
            workspace_dir="/tmp/sase-core_12",
        ),
        LinkedRepoMetadata(
            name="sase-nvim",
            workspace_dir="/tmp/sase-nvim",
        ),
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        raw_suffix="20250615103000",
        linked_repos=linked_repos,
    )

    bundle = agent.to_bundle_dict()

    assert bundle["linked_repos"] == [
        {
            "name": "sase-core",
            "workspace_dir": "/tmp/sase-core_12",
        },
        {
            "name": "sase-nvim",
            "workspace_dir": "/tmp/sase-nvim",
        },
    ]
    json.dumps(bundle)
    restored = Agent.from_bundle_dict(bundle)
    assert restored.linked_repos == linked_repos


def test_bundle_round_trip_empty_linked_repos() -> None:
    """The default linked repo value remains an empty tuple after loading."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        raw_suffix="20250615103000",
    )

    bundle = agent.to_bundle_dict()
    restored = Agent.from_bundle_dict(bundle)

    assert bundle["linked_repos"] == []
    assert restored.linked_repos == ()


def test_bundle_skips_retry_chain_siblings() -> None:
    """Retry-chain sibling relationships are load-time only."""
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="FAILED",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        raw_suffix="20250615103000",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature_retry",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 45, 0),
        raw_suffix="20250615104500",
    )
    parent.retry_chain_siblings.append(child)

    bundle = parent.to_bundle_dict()

    assert "retry_chain_siblings" not in bundle
    json.dumps(bundle)
    restored = Agent.from_bundle_dict(bundle)
    assert restored.retry_chain_siblings == []


def test_bundle_skips_wait_display_source() -> None:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="parent",
        project_file="/tmp/test.sase",
        status="WAITING",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="child",
        project_file="/tmp/test.sase",
        status="WAITING",
        start_time=datetime(2025, 6, 15, 10, 5, 0),
    )
    parent.wait_display_source = child

    bundle = parent.to_bundle_dict()

    assert "wait_display_source" not in bundle
    json.dumps(bundle)
    restored = Agent.from_bundle_dict(bundle)
    assert restored.wait_display_source is None


def test_bundle_dict_is_json_serializable_for_populated_agent() -> None:
    """Guard against future bundle fields leaking non-JSON-native values."""
    feedback_time = datetime(2025, 6, 15, 10, 6, 0)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        run_start_time=datetime(2025, 6, 15, 10, 31, 0),
        wait_start_time=datetime(2025, 6, 15, 10, 29, 0),
        stop_time=datetime(2025, 6, 15, 11, 0, 0),
        workspace_num=12,
        raw_suffix="20250615103000",
        response_path="/tmp/response.md",
        extra_files=["/tmp/plan.md"],
        step_output={"ok": True, "count": 2},
        pdf_status={"path": "/tmp/report.pdf", "done": True},
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir="/tmp/sase-core_12",
            ),
        ),
        waiting_for=["agent-a"],
        tribe="backend",
        output_variables={"report": "/tmp/report.md"},
        plan_times=[datetime(2025, 6, 15, 10, 5, 0)],
        code_time=datetime(2025, 6, 15, 10, 10, 0),
        feedback_times=[feedback_time],
        feedback_plan_paths={feedback_time: "/tmp/rejected-plan.md"},
        questions_times=[datetime(2025, 6, 15, 10, 7, 0)],
        retry_times=[datetime(2025, 6, 15, 10, 8, 0)],
        retry_count=1,
    )
    agent.followup_agents.append(
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="child",
            project_file="/tmp/test.sase",
            status="DONE",
            start_time=datetime(2025, 6, 15, 10, 40, 0),
        )
    )
    agent.runtime_children.append(agent.followup_agents[0])
    agent.retry_chain_siblings.append(agent.followup_agents[0])

    json.dumps(agent.to_bundle_dict())


def test_bundle_serialization_keeps_agent_state_without_artifact_text(
    tmp_path: Path,
) -> None:
    """Dismissed bundles serialize Agent state without embedding artifact text."""
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

    assert bundle["raw_suffix"] == "20250615103000"
    assert bundle["cl_name"] == "my_feature"
    assert bundle["response_path"] == str(response_path)
    serialized = json.dumps(bundle)
    assert "sk-test1234567890abcdef" not in serialized
    assert "Bearer abcdefghijklmnopqrstuvwxyz" not in serialized
    assert "api_key=abcdef1234567890" not in serialized
    assert "ghp_abcdefghijklmnopqrstuvwx123456" not in serialized


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
