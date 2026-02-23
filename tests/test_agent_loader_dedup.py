"""Tests for agent deduplication logic in load_all_agents."""

from unittest.mock import MagicMock, patch

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_loader import load_all_agents


def test_load_all_agents_dedup_preserves_workspace_num() -> None:
    """Test that workspace_num from RUNNING entry is preserved after dedup.

    When deduplicating by timestamp, the workspace_num from the RUNNING entry
    should be copied to the matched ChangeSpec entry.
    """
    from sase.ace.changespec import ChangeSpec, HookEntry, HookStatusLine

    # Create RUNNING entry with axe PID 11111 and workspace_num=5
    mock_claim = MagicMock()
    mock_claim.workspace_num = 5
    mock_claim.workflow = "axe(fix-hook)-251230_151429"  # Timestamp here
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = 11111  # Axe process PID
    mock_claim.artifacts_timestamp = "20251230151429"

    # Create HOOKS entry with different subprocess PID 22222, no workspace_num
    mock_status_line = HookStatusLine(
        commit_entry_num="1",
        timestamp="251230_151429",
        status="RUNNING",
        suffix="fix_hook-22222-251230_151429",  # Different PID, same timestamp
        suffix_type="running_agent",
    )

    mock_hook = HookEntry(command="bb_test", status_lines=[mock_status_line])

    mock_cs = ChangeSpec(
        name="my_feature",
        description="Test",
        parent=None,
        cl="12345",
        status="Ready",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
        hooks=[mock_hook],
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.gp"],
        ),
        patch(
            "sase.ace.tui.models._loaders._artifact_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[mock_cs],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
        patch("sase.ace.tui.models.agent_loader.load_done_agents", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents",
            return_value=[],
        ),
        patch("sase.ace.tui.models.agent_loader.load_workflow_agents", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps",
            return_value=([], {}),
        ),
    ):
        agents = load_all_agents()
        assert len(agents) == 1
        # Should have FIX_HOOK type with workspace_num copied from RUNNING entry
        assert agents[0].agent_type == AgentType.FIX_HOOK
        assert agents[0].workspace_num == 5


def test_workflow_dedup_propagates_failed_status() -> None:
    """Test that dedup propagates FAILED status from workflow_state.json."""
    from sase.ace.tui.models.agent import Agent, AgentType

    # Simulate RUNNING field entry (status=RUNNING, no PID)
    running_field_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="deploy",
        raw_suffix="20260101120000",
        workspace_num=5,
    )

    # Simulate workflow_state.json entry (status=FAILED, with PID)
    workflow_state_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.gp",
        status="FAILED",
        start_time=None,
        workflow="deploy",
        raw_suffix="20260101120000",
        pid=121415,
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
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[running_field_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents",
            return_value=[workflow_state_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps",
            return_value=([], {}),
        ),
    ):
        result = load_all_agents()

    # Should be deduplicated to one agent
    assert len(result) == 1
    # Status should be FAILED (propagated from workflow_state.json)
    assert result[0].status == "FAILED"
    # Workspace num should be preserved from RUNNING field entry
    assert result[0].workspace_num == 5
    # PID should be propagated from workflow_state.json
    assert result[0].pid == 121415


def test_running_workflow_dedup_ace_run() -> None:
    """Test RUNNING↔WORKFLOW dedup for ace(run) agents.

    When sase run creates both a done.json (RUNNING agent) and a
    workflow_state.json (WORKFLOW agent) in the same artifacts directory,
    the two should be deduplicated into a single WORKFLOW agent with
    metadata merged from the RUNNING agent.
    """
    from sase.ace.tui.models.agent import Agent, AgentType

    # RUNNING agent from done.json (has cl_name, workspace_num, response_path, etc.)
    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
        workflow="ace(run)",
        raw_suffix="20260219120000",
        workspace_num=3,
        response_path="/tmp/response.txt",
        diff_path="/tmp/diff.patch",
        model="gemini-2.5-pro",
        vcs_provider="GitHub",
    )

    # WORKFLOW agent from workflow_state.json (has appears_as_agent, but unknown cl_name)
    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="unknown",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
        workflow="tmp_ace_run_1234",
        raw_suffix="20260219120000",
        appears_as_agent=True,
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
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents",
            return_value=[running_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents",
            return_value=[workflow_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps",
            return_value=([], {}),
        ),
    ):
        result = load_all_agents()

    # Should be deduplicated to one agent
    assert len(result) == 1
    # Should be the WORKFLOW agent (preferred — has step info / appears_as_agent)
    assert result[0].agent_type == AgentType.WORKFLOW
    assert result[0].appears_as_agent is True
    # Metadata should be merged from the RUNNING agent
    assert result[0].cl_name == "my_feature"
    assert result[0].workspace_num == 3
    assert result[0].response_path == "/tmp/response.txt"
    assert result[0].diff_path == "/tmp/diff.patch"
    assert result[0].model == "gemini-2.5-pro"
    assert result[0].vcs_provider == "GitHub"
    # PID should come from the WORKFLOW agent
    assert result[0].pid == 55555
