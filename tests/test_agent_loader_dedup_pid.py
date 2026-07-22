"""Tests for PID-based safety net dedup and PID reuse handling."""

from datetime import datetime
from unittest.mock import patch

import pytest

from sase.ace.agent_tribes import REVIEW_AGENT_TRIBE
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from sase.ace.tui.models.agent_runner_slots import (
    RunnerCapacitySnapshot,
    refresh_runner_slot_context,
)
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    WaitingMarkerWire,
)
from sase.core.runner_slots import running_root_agent_count
from tests._agent_loader_helpers import _empty_artifact_snapshot
from tests._workspace_provider_helpers import patch_spy_metadata


@pytest.fixture(autouse=True)
def _register_spy_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_spy_metadata(monkeypatch)


def test_pid_dedup_safety_net() -> None:
    """Test that the PID-based safety net catches duplicate PIDs.

    Even if earlier dedup passes miss a duplicate, the final PID-based
    dedup should remove the less-specific agent entirely.
    """
    # WORKFLOW agent (should be preferred)
    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="some-workflow",
        raw_suffix="20260310173745",
        pid=12345,
    )

    # RUNNING agent with same PID (should be removed by safety net)
    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="some-other-workflow",
        raw_suffix=None,
        workspace_num=100,
        pid=12345,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[running_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[workflow_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    # Only the WORKFLOW agent should remain (preferred over RUNNING)
    assert len(result) == 1
    assert result[0].agent_type == AgentType.WORKFLOW
    # workspace_num should be merged from the removed RUNNING agent
    assert result[0].workspace_num == 100


def test_pid_dedup_merges_running_workflow_rows_for_same_artifact() -> None:
    """Same-suffix RUNNING and WORKFLOW projections remain one artifact row."""
    root_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="root",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="root-workflow",
        raw_suffix="20260310170000",
        pid=12345,
    )
    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="some-workflow",
        raw_suffix="20260310173745",
        pid=12345,
    )
    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="some-other-workflow",
        raw_suffix="20260310173745",
        workspace_num=100,
        pid=12345,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[root_agent, running_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[workflow_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    assert result == [root_agent, workflow_agent]
    assert workflow_agent.workspace_num == 100


def test_live_family_root_survives_shared_pid_for_runner_slot_context() -> None:
    """A terminal serial phase cannot erase its live root's occupied slot."""
    root_timestamp = "20260721155935"
    child_timestamp = "20260721160507"
    waiter_timestamp = "20260721161000"
    runner_pid = 1729466
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="hc.f0.f0--0",
        project_file="/tmp/project/project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 21, 15, 59, 35),
        run_start_time=datetime(2026, 7, 21, 15, 59, 36),
        workflow="ace(run)",
        raw_suffix=root_timestamp,
        pid=runner_pid,
        runner_is_live=True,
        artifacts_dir=f"/tmp/project/artifacts/ace-run/{root_timestamp}",
        agent_name="hc.f0.f0--0",
        agent_family="hc.f0.f0",
        agent_family_role="root",
    )
    child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="hc.f0.f0--1",
        project_file="/tmp/project/project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 21, 16, 5, 7),
        run_start_time=datetime(2026, 7, 21, 16, 5, 8),
        stop_time=datetime(2026, 7, 21, 16, 8),
        workflow="ace-run",
        raw_suffix=child_timestamp,
        pid=runner_pid,
        artifacts_dir=f"/tmp/project/artifacts/ace-run/{child_timestamp}",
        parent_timestamp=root_timestamp,
        agent_name="hc.f0.f0--1",
        agent_family="hc.f0.f0",
        agent_family_role="code",
        role_suffix=".code",
    )
    waiter = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="queued",
        project_file="/tmp/project/project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 21, 16, 10),
        workflow="ace(run)",
        raw_suffix=waiter_timestamp,
        pid=1729999,
        artifacts_dir=f"/tmp/project/artifacts/ace-run/{waiter_timestamp}",
        wait_runners=0,
        wait_runners_explicit=False,
        slot_requested_at="2026-07-21T16:10:00-04:00",
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[root, waiter],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[child],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    assert any(agent is root for agent in result)
    assert any(agent is child for agent in result)
    assert root.runner_is_live is True
    assert child.runner_is_live is False
    assert root.followup_agents == [child]
    assert root.runtime_children == [child]

    capacity = refresh_runner_slot_context(result, effective_limit=1)

    assert capacity == RunnerCapacitySnapshot(1, 1, 1)
    assert waiter.runner_slots_in_use == 1
    assert waiter.runner_slot_queue_position is None
    assert waiter.runner_slot_queue_size == 0

    admission_records = [
        AgentArtifactRecordWire(
            project_name="project",
            project_dir="/tmp/project",
            project_file="/tmp/project/project.sase",
            workflow_dir_name="ace-run",
            artifact_dir=root.artifacts_dir or "",
            timestamp=root_timestamp,
            agent_meta=AgentMetaWire(
                name=root.agent_name,
                pid=runner_pid,
                run_started_at="2026-07-21T15:59:36-04:00",
            ),
        ),
        AgentArtifactRecordWire(
            project_name="project",
            project_dir="/tmp/project",
            project_file="/tmp/project/project.sase",
            workflow_dir_name="ace-run",
            artifact_dir=child.artifacts_dir or "",
            timestamp=child_timestamp,
            agent_meta=AgentMetaWire(
                name=child.agent_name,
                pid=runner_pid,
                parent_timestamp=root_timestamp,
                run_started_at="2026-07-21T16:05:08-04:00",
            ),
            has_done_marker=True,
        ),
        AgentArtifactRecordWire(
            project_name="project",
            project_dir="/tmp/project",
            project_file="/tmp/project/project.sase",
            workflow_dir_name="ace-run",
            artifact_dir=waiter.artifacts_dir or "",
            timestamp=waiter_timestamp,
            agent_meta=AgentMetaWire(name="queued", pid=waiter.pid),
            waiting=WaitingMarkerWire(
                wait_runners=0,
                slot_requested_at=waiter.slot_requested_at,
            ),
        ),
    ]
    admission_count = running_root_agent_count(admission_records, lambda _record: True)
    assert capacity.slots_in_use == admission_count == 1


def test_pid_dedup_safety_net_works_on_review_agents() -> None:
    """Test that PID safety net deduplicates review-tribe agents.

    When a ChangeSpec fix-hook and VCS workspace share a PID, the safety
    net should still remove one to prevent duplicate process rows.
    """
    # Review-tribe fix-hook agent (from ChangeSpec)
    fix_hook_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        raw_suffix="fix_hook-99999-260310_175213",
        pid=99999,
        tribe=REVIEW_AGENT_TRIBE,
    )

    # VCS workspace agent with same PID
    # (pretend VCS hiding didn't remove it — this tests safety net)
    vcs_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="spy-my_feature",
        raw_suffix=None,
        workspace_num=100,
        pid=99999,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[fix_hook_agent, vcs_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    # Only one agent with PID 99999 should remain
    pid_agents = [a for a in result if a.pid == 99999]
    assert len(pid_agents) == 1
    # The non-VCS agent should be kept (VCS is removed)
    assert pid_agents[0].workflow == "fix-hook"
    assert pid_agents[0].tribe == REVIEW_AGENT_TRIBE


def test_pid_dedup_preserves_followup_workflow_agents() -> None:
    """Test that follow-up WORKFLOW agents sharing a PID are not deduplicated.

    When an agent runner handles plan approval, both the plan phase and code
    phase write workflow_state.json to separate artifact directories. Both
    share the same PID (the runner process). The PID safety net must keep
    both since they represent different work phases, not duplicates.
    """
    # Plan phase WORKFLOW (older timestamp)
    plan_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 3, 15, 21, 32, 15),
        workflow="sase",
        raw_suffix="20260315213215",
        pid=1780415,
        role_suffix=".plan",
    )

    # Code phase WORKFLOW (newer timestamp, same PID)
    code_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 3, 15, 21, 45, 30),
        workflow="sase",
        raw_suffix="20260315214530",
        pid=1780415,
        role_suffix=".code",
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[plan_agent, code_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=False,
        ),
    ):
        result = load_all_agents()

    # Both should survive — they are different phases, not duplicates. The plan
    # root also gains its logical planner child for family display.
    assert len(result) == 3
    suffixes = {a.raw_suffix for a in result}
    assert "20260315213215" in suffixes
    assert "20260315214530" in suffixes


def test_pid_reuse_keeps_both_running_agents_with_different_suffix() -> None:
    """Two RUNNING agents with same PID but different raw_suffix are kept.

    OS PID recycling can assign a new agent the same PID as a stale entry.
    When both have distinct raw_suffix values, they are separate agents.
    """
    agent_a = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix="20260330120000",
        pid=55555,
    )

    agent_b = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="user-run",
        raw_suffix="20260330120500",
        pid=55555,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[agent_a, agent_b],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    assert len(result) == 2
    suffixes = {a.raw_suffix for a in result}
    assert "20260330120000" in suffixes
    assert "20260330120500" in suffixes


def test_pid_reuse_merges_running_agents_with_same_suffix() -> None:
    """Two RUNNING agents with same PID and same raw_suffix are merged (true duplicate)."""
    agent_a = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix="20260330120000",
        pid=55555,
    )

    agent_b = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix="20260330120000",
        workspace_num=100,
        pid=55555,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[agent_a, agent_b],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    assert len(result) == 1
    assert result[0].raw_suffix == "20260330120000"
    assert result[0].workspace_num == 100  # merged from agent_b


def test_pid_reuse_merges_running_agents_with_missing_suffix() -> None:
    """Two RUNNING agents with same PID, one missing raw_suffix, are merged (legacy fallback)."""
    agent_a = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix="20260330120000",
        pid=55555,
    )

    agent_b = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix=None,
        workspace_num=100,
        pid=55555,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[agent_a, agent_b],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    assert len(result) == 1
    assert result[0].workspace_num == 100  # merged from agent_b
