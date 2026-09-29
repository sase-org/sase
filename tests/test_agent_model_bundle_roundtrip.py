"""Bundle round-trip tests: core fields, linked repos, and load-time skips."""

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


def test_bundle_hydrates_projected_agent_and_skips_projection_fields(
    monkeypatch,
) -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        raw_suffix="20250615103000",
        step_output={"meta_keep": "projected"},
        record_shape="list",
        index_record_dir="/tmp/artifacts/20250615103000",
    )

    def hydrate(projected: Agent) -> bool:
        projected.record_shape = "full"
        projected.step_output = {
            "_raw": "full text",
            "meta_keep": "loaded",
        }
        return True

    monkeypatch.setattr(
        "sase.ace.tui.models._projected_record.hydrate_projected_agent",
        hydrate,
    )

    bundle = agent.to_bundle_dict()

    assert bundle["step_output"] == {
        "_raw": "full text",
        "meta_keep": "loaded",
    }
    assert "record_shape" not in bundle
    assert "index_record_dir" not in bundle
    assert "prompt_step_file_name" not in bundle


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
