"""Tests for _apply_status_overrides tale plan action decisions."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option


def test_apply_status_overrides_active_code_child_with_tale_plan_action_is_tale_approved() -> (
    None
):
    """A DONE plan parent with plan_action=tale and an active .code child becomes TALE APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action="tale",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "TALE APPROVED"
    assert code_child.status == "TALE APPROVED"


def test_apply_status_overrides_active_code_child_without_plan_action_is_plan_approved() -> (
    None
):
    """Regression guard: a generic-approve parent (no plan_action) stays PLAN APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action=None,
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN APPROVED"
    assert code_child.status == "PLAN APPROVED"


def test_apply_status_overrides_active_code_child_with_tale_child_action_is_tale_approved() -> (
    None
):
    """A RUNNING .code child with plan_action=tale becomes TALE APPROVED."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".code",
        plan_action="tale",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "TALE APPROVED"
    assert code_child.status == "TALE APPROVED"


def test_apply_status_overrides_active_code_child_with_parent_status_tale_approved() -> (
    None
):
    """In-session-mask path: parent.status starts as TALE APPROVED, no plan_action."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="TALE APPROVED",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "TALE APPROVED"
    assert code_child.status == "TALE APPROVED"


def test_apply_status_overrides_done_with_tale_plan_action_yields_tale_done() -> None:
    """A DONE .plan parent with plan_action=tale and a completed .code child becomes TALE DONE."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action="tale",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "TALE DONE"
    assert code_child.status == "TALE DONE"


def test_apply_status_overrides_done_tale_with_completed_epic_followup_still_yields_epic_created() -> (
    None
):
    """An .epic follow-up wins over the tale-vs-plan branch when it was the newest to complete."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action="tale",
    )
    epic_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".epic",
    )
    agents = [parent, epic_child]
    _apply_status_overrides(agents)

    assert parent.status == "EPIC CREATED"
    assert epic_child.status == "EPIC CREATED"


def test_apply_status_overrides_done_without_tale_plan_action_still_yields_plan_done() -> (
    None
):
    """Regression guard: a generic-approve parent (no plan_action) still becomes PLAN DONE."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 0, 0),
        raw_suffix="20260511090000",
        role_suffix=".plan",
        plan_action=None,
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 11, 9, 10, 0),
        parent_timestamp="20260511090000",
        role_suffix=".code",
    )
    agents = [parent, code_child]
    _apply_status_overrides(agents)

    assert parent.status == "PLAN DONE"
    assert code_child.status == "PLAN DONE"


def test_apply_status_overrides_active_tale_code_child_backfills_root_badge_metadata() -> (
    None
):
    """A root plan row without provider metadata inherits it from active code."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="a5n",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 11, 43, 3),
        workflow="ace-run",
        raw_suffix="20260523114303",
        role_suffix="-plan",
        appears_as_agent=True,
        agent_name="a5n",
        agent_family="a5n",
        agent_family_role="root",
        plan_chain_root=True,
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="a5n-code",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 23, 11, 46, 30),
        raw_suffix="20260523114630",
        parent_timestamp="20260523114303",
        role_suffix="-code",
        agent_name="a5n-code",
        agent_family="a5n",
        agent_family_role="code",
        plan_action="tale",
        model="gpt-5.5",
        llm_provider="codex",
        vcs_provider="GitHub",
        workspace_num=13,
        workspace_dir="/tmp/sase_13",
    )
    agents = [parent, code_child]

    _apply_status_overrides(agents)

    assert parent.status == "TALE APPROVED"
    assert parent.model == "gpt-5.5"
    assert parent.llm_provider == "codex"
    assert parent.vcs_provider == "GitHub"
    assert parent.workspace_num == 13
    assert parent.workspace_dir == "/tmp/sase_13"

    left, _, _ = format_agent_option(parent, 0, is_selected=False)
    assert "🤖 a5n (TALE APPROVED)" in left.plain


def test_apply_status_overrides_child_metadata_does_not_overwrite_root_metadata() -> (
    None
):
    """Mirroring status fills only missing root metadata."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="mixed",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 11, 43, 3),
        raw_suffix="20260523114303",
        role_suffix="-plan",
        agent_name="mixed",
        agent_family="mixed",
        agent_family_role="root",
        plan_chain_root=True,
        model="root-model",
        llm_provider="claude",
        vcs_provider="Mercurial",
        workspace_num=7,
        workspace_dir="/tmp/root",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="mixed-code",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 23, 11, 46, 30),
        parent_timestamp="20260523114303",
        role_suffix="-code",
        model="gpt-5.5",
        llm_provider="codex",
        vcs_provider="GitHub",
        workspace_num=13,
        workspace_dir="/tmp/sase_13",
    )

    _apply_status_overrides([parent, code_child])

    assert parent.status == "PLAN APPROVED"
    assert parent.model == "root-model"
    assert parent.llm_provider == "claude"
    assert parent.vcs_provider == "Mercurial"
    assert parent.workspace_num == 7
    assert parent.workspace_dir == "/tmp/root"
