"""Tests for agent deduplication logic in load_all_agents."""

from unittest.mock import MagicMock, patch

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_loader import load_all_agents


def test_load_all_agents_deduplicates_by_timestamp() -> None:
    """Test that agents with same timestamp from different sources are deduplicated.

    This is the real-world scenario: axe process (RUNNING) has a different PID than
    the subprocess (ChangeSpec), but they share the same timestamp.
    """
    from sase.ace.changespec import ChangeSpec, HookEntry, HookStatusLine

    # Create RUNNING entry with axe process PID 11111 and timestamp in workflow
    mock_claim = MagicMock()
    mock_claim.workspace_num = 100
    mock_claim.workflow = "axe(fix-hook)-251230_151429"  # Timestamp here
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = 11111  # Axe process PID
    mock_claim.artifacts_timestamp = "20251230151429"

    # Create HOOKS entry with different subprocess PID 22222 but same timestamp
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
        status="Drafted",
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
            return_value=[],
        ),
    ):
        agents = load_all_agents()
        # Should have only one agent (deduplicated by timestamp)
        assert len(agents) == 1
        # Should prefer FIX_HOOK (more specific) over RUNNING
        assert agents[0].agent_type == AgentType.FIX_HOOK
        assert agents[0].pid == 22222  # Subprocess PID


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
        status="Drafted",
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
            return_value=[],
        ),
    ):
        agents = load_all_agents()
        assert len(agents) == 1
        # Should have FIX_HOOK type with workspace_num copied from RUNNING entry
        assert agents[0].agent_type == AgentType.FIX_HOOK
        assert agents[0].workspace_num == 5


def test_load_all_agents_dedup_mentor_by_timestamp() -> None:
    """Test deduplication of mentor agents by timestamp."""
    from sase.ace.changespec import ChangeSpec, MentorEntry, MentorStatusLine

    # Create RUNNING entry with axe(mentor) workflow and timestamp
    mock_claim = MagicMock()
    mock_claim.workspace_num = 3
    mock_claim.workflow = "axe(mentor)-complete-260112_134051"  # Timestamp here
    mock_claim.cl_name = "foobar_boom"
    mock_claim.pid = 1527683  # Axe process PID
    mock_claim.artifacts_timestamp = "20260112134051"

    # Create MENTORS entry with different subprocess PID but same timestamp
    mock_status_line = MentorStatusLine(
        timestamp="251231_120000",
        profile_name="profile1",
        mentor_name="mentor1",
        status="RUNNING",
        suffix="mentor_complete-1855023-260112_134051",  # Different PID, same timestamp
        suffix_type="running_agent",
    )

    mock_mentor = MentorEntry(
        entry_id="1", profiles=["profile1"], status_lines=[mock_status_line]
    )

    mock_cs = ChangeSpec(
        name="foobar_boom",
        description="Test",
        parent=None,
        cl="12345",
        status="Drafted",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
        mentors=[mock_mentor],
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
            return_value=[],
        ),
    ):
        agents = load_all_agents()
        # Should have only one agent (deduplicated by timestamp)
        assert len(agents) == 1
        # Should prefer MENTOR (more specific) over RUNNING
        assert agents[0].agent_type == AgentType.MENTOR
        assert agents[0].pid == 1855023  # Subprocess PID
        assert agents[0].workspace_num == 3  # Copied from RUNNING entry


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
            return_value=[],
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


def test_running_vs_workflow_dedup_by_pid() -> None:
    """Test that RUNNING and WORKFLOW (appears_as_agent) with same PID are deduped.

    When ace(run) launches an embedded workflow, the same PID is discovered
    from both the RUNNING field (project file) and workflow_state.json.
    The RUNNING agent should be kept with workspace_num merged from WORKFLOW.
    """
    from sase.ace.tui.models.agent import Agent, AgentType

    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="ace(run)",
        raw_suffix="20260217120000",
        pid=54321,
    )

    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="hg-bug",
        raw_suffix="20260217120001",
        pid=54321,
        appears_as_agent=True,
        workspace_num=102,
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
            return_value=[running_agent],
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
            return_value=[workflow_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    assert len(result) == 1
    assert result[0].agent_type == AgentType.RUNNING
    assert result[0].pid == 54321
    assert result[0].workspace_num == 102


def test_running_vs_workflow_dedup_copies_done_status() -> None:
    """Test that DONE status from WORKFLOW agent is propagated to RUNNING agent."""
    from sase.ace.tui.models.agent import Agent, AgentType

    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="ace(run)",
        raw_suffix="20260217130000",
        pid=99999,
        workspace_num=5,
    )

    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=None,
        workflow="hg-bug",
        raw_suffix="20260217130001",
        pid=99999,
        appears_as_agent=True,
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
            return_value=[running_agent],
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
            return_value=[workflow_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    assert len(result) == 1
    assert result[0].agent_type == AgentType.RUNNING
    assert result[0].status == "DONE"
    assert result[0].workspace_num == 5


def test_running_vs_workflow_no_dedup_without_appears_as_agent() -> None:
    """Test that WORKFLOW agents without appears_as_agent are NOT deduped with RUNNING.

    Only workflows that look like agents (appears_as_agent=True) should be
    considered for cross-type dedup. Real multi-step workflows should remain separate.
    """
    from sase.ace.tui.models.agent import Agent, AgentType

    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="ace(run)",
        raw_suffix="20260217140000",
        pid=77777,
    )

    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="deploy-pipeline",
        raw_suffix="20260217140001",
        pid=77777,
        appears_as_agent=False,  # Real multi-step workflow, not agent-like
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
            return_value=[running_agent],
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
            return_value=[workflow_agent],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
    ):
        result = load_all_agents()

    # Both agents should remain (no dedup for non-appears_as_agent workflows)
    assert len(result) == 2
    types = {a.agent_type for a in result}
    assert AgentType.RUNNING in types
    assert AgentType.WORKFLOW in types
