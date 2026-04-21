"""Tests for the load_all_agents function."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides, load_all_agents


def test_load_all_agents_with_running_claims() -> None:
    """Test load_all_agents with RUNNING field claims."""
    mock_claim = MagicMock()
    mock_claim.workspace_num = 1
    mock_claim.workflow = "crs"
    mock_claim.cl_name = "my_feature"

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.gp"],
        ),
        patch(
            "sase.ace.tui.models._loaders._artifact_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch("sase.ace.tui.models.agent_loader.find_all_changespecs", return_value=[]),
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
        assert agents[0].agent_type == AgentType.RUNNING
        assert agents[0].cl_name == "my_feature"
        assert agents[0].workspace_num == 1
        assert agents[0].workflow == "crs"


def test_load_all_agents_with_summarize_agents() -> None:
    """Test load_all_agents identifies summarize agents correctly."""
    from sase.ace.changespec import ChangeSpec, HookEntry, HookStatusLine

    mock_status_line = HookStatusLine(
        commit_entry_num="1",
        timestamp="251230_151429",
        status="RUNNING",
        suffix="summarize_hook-12345-251230_151429",
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
            return_value=[],
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
        assert agents[0].agent_type == AgentType.RUNNING
        assert agents[0].workflow == "summarize-hook"


def test_load_all_agents_with_mentor_agents() -> None:
    """Test load_all_agents with mentor agents from ChangeSpec."""
    from sase.ace.changespec import ChangeSpec, MentorEntry, MentorStatusLine

    mock_status_line = MentorStatusLine(
        timestamp="251231_120000",
        profile_name="profile1",
        mentor_name="mentor1",
        status="RUNNING",
        suffix="mentor_complete-12345-251230_151429",
        suffix_type="running_agent",
    )

    mock_mentor = MentorEntry(
        entry_id="1", profiles=["profile1"], status_lines=[mock_status_line]
    )

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
        mentors=[mock_mentor],
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
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
        assert agents[0].agent_type == AgentType.RUNNING
        assert agents[0].workflow == "mentor"
        assert agents[0].mentor_profile == "profile1"
        assert agents[0].mentor_name == "mentor1"


def test_load_all_agents_with_crs_agents() -> None:
    """Test load_all_agents with CRS agents from ChangeSpec."""
    from sase.ace.changespec import ChangeSpec, CommentEntry

    mock_comment = CommentEntry(
        reviewer="critique",
        file_path="~/.sase/comments/test.json",
        suffix="crs-251230_151429",
        suffix_type="running_agent",
    )

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
        comments=[mock_comment],
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.find_all_changespecs",
            return_value=[mock_cs],
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
        assert agents[0].agent_type == AgentType.RUNNING
        assert agents[0].workflow == "crs"
        assert agents[0].reviewer == "critique"


def test_load_all_agents_filters_hook_processes() -> None:
    """Test that RUNNING entries with axe(hooks) workflow are filtered out."""
    # Mock a RUNNING claim with axe(hooks)-1 workflow (hook process, not agent)
    mock_claim = MagicMock()
    mock_claim.workspace_num = 100
    mock_claim.workflow = "axe(hooks)-1"
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = 12345
    mock_claim.artifacts_timestamp = None

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.gp"],
        ),
        patch(
            "sase.ace.tui.models._loaders._artifact_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch("sase.ace.tui.models.agent_loader.find_all_changespecs", return_value=[]),
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
        # Hook process should be filtered out
        assert len(agents) == 0


def test_load_all_agents_includes_axe_fix_hook() -> None:
    """Test that RUNNING entries with axe(fix-hook) workflow are included."""
    # Mock a RUNNING claim with axe(fix-hook)-timestamp workflow
    mock_claim = MagicMock()
    mock_claim.workspace_num = 100
    mock_claim.workflow = "axe(fix-hook)-251230_151429"
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = None  # No PID to skip process check
    mock_claim.artifacts_timestamp = "20251230151429"

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.gp"],
        ),
        patch(
            "sase.ace.tui.models._loaders._artifact_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch("sase.ace.tui.models.agent_loader.find_all_changespecs", return_value=[]),
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
        # Agent workflow should be included
        assert len(agents) == 1
        assert agents[0].agent_type == AgentType.RUNNING
        assert agents[0].workflow == "axe(fix-hook)-251230_151429"


def test_workflow_waiting_hitl_dead_pid_marked_as_failed() -> None:
    """Test that a WAITING INPUT workflow with dead PID is marked as FAILED."""
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        sase_projects = Path(tmpdir) / ".sase" / "projects" / "myproject"
        sase_artifacts = (
            sase_projects / "artifacts" / "workflow-deploy" / "20260101120000"
        )
        sase_artifacts.mkdir(parents=True)
        (sase_projects / "myproject.gp").touch()

        state = {
            "workflow_name": "deploy",
            "status": "waiting_hitl",
            "pid": 99999,
            "context": {"cl_name": "test_cl"},
            "steps": [],
        }
        (sase_artifacts / "workflow_state.json").write_text(json.dumps(state))

        with (
            patch(
                "sase.ace.tui.models._loaders._workflow_loaders.Path.home",
                return_value=Path(tmpdir),
            ),
            patch(
                "sase.ace.tui.models._loaders._workflow_loaders.is_process_running",
                return_value=False,
            ),
        ):
            from sase.ace.tui.models._loaders import load_workflow_states

            entries = load_workflow_states()

        assert len(entries) == 1
        assert entries[0].status == "FAILED"


def test_apply_status_overrides_propagates_code_time() -> None:
    """_apply_status_overrides sets parent.code_time from .code child."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        raw_suffix="20250615100000",
        role_suffix=".plan",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 10, 0),
        run_start_time=datetime(2025, 6, 15, 10, 10, 5),
        parent_timestamp="20250615100000",
        role_suffix=".code",
    )
    agents = [parent, child]
    _apply_status_overrides(agents)

    assert parent.code_time == datetime(2025, 6, 15, 10, 10, 5)


def test_apply_status_overrides_code_time_falls_back_to_start_time() -> None:
    """code_time uses start_time when run_start_time is None."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        raw_suffix="20250615100000",
        role_suffix=".plan",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 10, 0),
        parent_timestamp="20250615100000",
        role_suffix=".code",
    )
    agents = [parent, child]
    _apply_status_overrides(agents)

    assert parent.code_time == datetime(2025, 6, 15, 10, 10, 0)


def test_apply_status_overrides_done_with_active_feedback_becomes_running() -> None:
    """A DONE .plan parent with an active feedback child is marked RUNNING."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 17, 16, 33, 26),
        raw_suffix="20260417163326",
        role_suffix=".plan",
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 17, 16, 45, 16),
        parent_timestamp="20260417163326",
        role_suffix=".2",
    )
    agents = [parent, feedback_child]
    _apply_status_overrides(agents)

    assert parent.status == "RUNNING"


def test_apply_status_overrides_done_with_completed_feedback_becomes_planning() -> None:
    """A DONE .plan parent with only completed feedback falls through to PLANNING."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 17, 16, 33, 26),
        raw_suffix="20260417163326",
        role_suffix=".plan",
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 17, 16, 45, 16),
        parent_timestamp="20260417163326",
        role_suffix=".2",
    )
    agents = [parent, feedback_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLANNING"


def test_apply_status_overrides_done_with_active_code_followup_becomes_plan_approved() -> (
    None
):
    """A DONE .plan parent with a completed feedback child + active .code child is PLAN APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 17, 16, 33, 26),
        raw_suffix="20260417163326",
        role_suffix=".plan",
    )
    feedback_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 17, 16, 45, 16),
        parent_timestamp="20260417163326",
        role_suffix=".2",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 17, 16, 50, 0),
        parent_timestamp="20260417163326",
        role_suffix=".code",
    )
    agents = [parent, feedback_child, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN APPROVED"


def test_apply_status_overrides_done_with_unanswered_question_becomes_question() -> (
    None
):
    """A DONE agent with questions_times and no .q follow-up becomes QUESTION."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 21, 16, 4, 27),
        raw_suffix="20260421160427",
        questions_times=[datetime(2026, 4, 21, 16, 17, 4)],
    )
    agents = [agent]
    _apply_status_overrides(agents)

    assert agent.status == "QUESTION"


def test_apply_status_overrides_done_with_answered_question_stays_done() -> None:
    """A DONE agent with a .q follow-up stays DONE (question was answered)."""
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 21, 16, 4, 27),
        raw_suffix="20260421160427",
        questions_times=[datetime(2026, 4, 21, 16, 17, 4)],
    )
    q_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 21, 16, 20, 0),
        parent_timestamp="20260421160427",
        role_suffix=".q",
    )
    agents = [parent, q_child]
    _apply_status_overrides(agents)

    assert parent.status == "DONE"


def test_apply_status_overrides_done_without_questions_stays_done() -> None:
    """A DONE agent with empty questions_times stays DONE."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2026, 4, 21, 16, 4, 27),
        raw_suffix="20260421160427",
    )
    agents = [agent]
    _apply_status_overrides(agents)

    assert agent.status == "DONE"
