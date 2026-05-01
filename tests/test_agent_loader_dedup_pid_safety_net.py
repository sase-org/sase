"""Tests for PID-based safety net deduplication."""

from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from tests._agent_loader_helpers import _empty_artifact_snapshot


def test_pid_dedup_safety_net() -> None:
    """Test that the PID-based safety net catches duplicate PIDs.

    Even if earlier dedup passes miss a duplicate, the final PID-based
    dedup should remove the less-specific agent entirely.
    """
    # WORKFLOW agent (should be preferred)
    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
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
        project_file="/tmp/test.gp",
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


def test_pid_dedup_safety_net_works_on_hidden_agents() -> None:
    """Test that PID safety net also deduplicates hidden agents.

    When two hidden agents share a PID (e.g., a hidden ChangeSpec fix-hook
    and a hidden VCS workspace), the safety net should still remove one
    to prevent duplicate PIDs even when hidden agents are toggled visible.
    """
    # Hidden fix-hook agent (from ChangeSpec)
    fix_hook_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        raw_suffix="fix_hook-99999-260310_175213",
        pid=99999,
        hidden=True,
    )

    # Hidden VCS workspace agent with same PID
    # (pretend VCS hiding didn't remove it — this tests safety net)
    vcs_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="hg-my_feature",
        raw_suffix=None,
        workspace_num=100,
        pid=99999,
        hidden=True,
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


def test_pid_dedup_preserves_followup_workflow_agents() -> None:
    """Test that follow-up WORKFLOW agents sharing a PID are not deduplicated.

    When an agent runner handles plan approval, both the plan phase and code
    phase write workflow_state.json to separate artifact directories. Both
    share the same PID (the runner process). The PID safety net must keep
    both since they represent different work phases, not duplicates.
    """
    from datetime import datetime

    # Plan phase WORKFLOW (older timestamp)
    plan_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.gp",
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
        project_file="/tmp/test.gp",
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

    # Both should survive — they are different phases, not duplicates
    assert len(result) == 2
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
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix="20260330120000",
        pid=55555,
    )

    agent_b = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
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
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix="20260330120000",
        pid=55555,
    )

    agent_b = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
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
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix="20260330120000",
        pid=55555,
    )

    agent_b = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
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
