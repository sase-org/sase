"""Tests for _apply_status_overrides tale plan action decisions."""

from datetime import datetime
from pathlib import Path

from sase.ace.tui.models._agent_status_diff import classify_diff_badges
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option


def _write_git_diff(path: Path, changed_path: str) -> None:
    path.write_text(
        f"""diff --git a/{changed_path} b/{changed_path}
--- a/{changed_path}
+++ b/{changed_path}
@@ -1 +1 @@
-old
+new
""",
        encoding="utf-8",
    )


def test_apply_status_overrides_active_code_child_with_tale_plan_action_is_working_tale() -> (
    None
):
    """A tale-approved root mirrors WORKING TALE while active .code works tale."""
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

    assert parent.status == "WORKING TALE"
    assert code_child.status == "WORKING TALE"


def test_apply_status_overrides_active_code_child_without_plan_action_is_working_plan() -> (
    None
):
    """Regression guard: a generic-approve parent mirrors WORKING PLAN."""
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

    assert parent.status == "WORKING PLAN"
    assert code_child.status == "WORKING PLAN"


def test_live_retrying_root_outranks_failed_coder_attempt() -> None:
    """A failed child stays visible without making its live retrying root terminal."""
    root_timestamp = "20260706115800"
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="retry-family",
        project_file="/tmp/test.sase",
        status="RETRYING",
        start_time=datetime(2026, 7, 6, 11, 58, 0),
        raw_suffix=root_timestamp,
        role_suffix="--plan",
        plan_action="tale",
        agent_family="retry-family",
        agent_family_role="root",
        plan_chain_root=True,
        runner_is_live=True,
        retry_status="retrying",
        retry_count=2,
        max_retries=3,
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="retry-family--code",
        project_file="/tmp/test.sase",
        status="FAILED",
        start_time=datetime(2026, 7, 6, 11, 59, 0),
        parent_timestamp=root_timestamp,
        role_suffix="--code",
        agent_family="retry-family",
        agent_family_role="code",
    )

    agents = [parent, coder]
    _apply_status_overrides(agents)
    _apply_status_overrides(agents)

    assert parent.status == "RETRYING"
    assert parent.retry_status == "retrying"
    assert coder.status == "FAILED"


def test_running_retry_with_active_coder_returns_to_working_tale() -> None:
    """Once the next attempt runs, semantic family work replaces RETRYING."""
    root_timestamp = "20260706115800"
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="retry-family",
        project_file="/tmp/test.sase",
        status="RETRYING",
        start_time=datetime(2026, 7, 6, 11, 58, 0),
        raw_suffix=root_timestamp,
        role_suffix="--plan",
        plan_action="tale",
        agent_family="retry-family",
        agent_family_role="root",
        plan_chain_root=True,
        runner_is_live=True,
        retry_status="running_retry",
        retry_count=2,
        max_retries=3,
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="retry-family--code",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 6, 12, 4, 0),
        parent_timestamp=root_timestamp,
        role_suffix="--code",
        agent_family="retry-family",
        agent_family_role="code",
    )

    _apply_status_overrides([parent, coder])

    assert parent.status == "WORKING TALE"
    assert coder.status == "WORKING TALE"
    assert parent.retry_status == "running_retry"


def test_apply_status_overrides_active_code_child_with_tale_child_action_is_working_tale() -> (
    None
):
    """A RUNNING .code child with plan_action=tale becomes WORKING TALE."""
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

    assert parent.status == "WORKING TALE"
    assert code_child.status == "WORKING TALE"


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

    assert parent.status == "WORKING TALE"
    assert code_child.status == "WORKING TALE"


def test_apply_status_overrides_active_code_keeps_planner_child_tale_approved() -> None:
    """The concrete planner child stays TALE APPROVED while code is active."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="a5n",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 11, 43, 3),
        raw_suffix="20260523114303",
        role_suffix="-plan",
        workflow="ace-run",
        agent_name="a5n",
        agent_family="a5n",
        agent_family_role="root",
        plan_chain_root=True,
        plan_action="tale",
    )
    planner_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="a5n-plan",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 11, 43, 3),
        parent_workflow="ace-run",
        parent_timestamp="20260523114303",
        step_type="agent",
        role_suffix="-plan",
        agent_name="a5n-plan",
        agent_family="a5n",
        agent_family_role="plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="a5n-code",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 23, 11, 46, 30),
        parent_timestamp="20260523114303",
        role_suffix="-code",
        agent_name="a5n-code",
        agent_family="a5n",
        agent_family_role="code",
    )

    _apply_status_overrides([parent, planner_child, code_child])

    assert planner_child.status == "TALE APPROVED"
    assert code_child.status == "WORKING TALE"
    assert parent.status == "WORKING TALE"


def test_apply_status_overrides_completed_code_keeps_planner_child_tale_approved() -> (
    None
):
    """The concrete planner child stays TALE APPROVED after code completes."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="a5n",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 11, 43, 3),
        raw_suffix="20260523114303",
        role_suffix="-plan",
        workflow="ace-run",
        agent_name="a5n",
        agent_family="a5n",
        agent_family_role="root",
        plan_chain_root=True,
        plan_action="tale",
    )
    planner_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="a5n-plan",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 11, 43, 3),
        parent_workflow="ace-run",
        parent_timestamp="20260523114303",
        step_type="agent",
        role_suffix="-plan",
        agent_name="a5n-plan",
        agent_family="a5n",
        agent_family_role="plan",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="a5n-code",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 11, 46, 30),
        parent_timestamp="20260523114303",
        role_suffix="-code",
        agent_name="a5n-code",
        agent_family="a5n",
        agent_family_role="code",
    )

    _apply_status_overrides([parent, planner_child, code_child])

    assert planner_child.status == "TALE APPROVED"
    assert code_child.status == "TALE DONE"
    assert parent.status == "TALE DONE"


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

    assert parent.status == "WORKING TALE"
    assert parent.model == "gpt-5.5"
    assert parent.llm_provider == "codex"
    assert parent.vcs_provider == "GitHub"
    assert parent.workspace_num == 13
    assert parent.workspace_dir == "/tmp/sase_13"

    left, _, _ = format_agent_option(parent, 0, is_selected=False)
    assert "🤖 a5n (WORKING TALE)" in left.plain


def test_apply_status_overrides_suppresses_sdd_only_diff_badge_for_working_tale_root(
    tmp_path: Path,
) -> None:
    """WORKING TALE roots do not show a pencil for plan/prompt-only diffs."""
    diff_path = tmp_path / "commit_diff.diff"
    _write_git_diff(diff_path, "sdd/plans/202606/change.md")
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="a5n",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 11, 43, 3),
        raw_suffix="20260523114303",
        role_suffix="-plan",
        diff_path=str(diff_path),
        agent_name="a5n",
        agent_family="a5n",
        agent_family_role="root",
        plan_chain_root=True,
        plan_action="tale",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="a5n-code",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 23, 11, 46, 30),
        parent_timestamp="20260523114303",
        role_suffix="-code",
    )

    _apply_status_overrides([parent, code_child], classify_diff_badges=False)

    assert parent.status == "WORKING TALE"
    # Persisted diff-badge classification is deferred off the loader pass
    # (see AgentDiffBadgeMixin); the field stays unset until that background
    # pass runs.
    assert parent.diff_has_real_edits is None

    classify_diff_badges([parent, code_child])

    assert parent.diff_has_real_edits is False
    left, suffix, _ = format_agent_option(parent, 0, is_selected=False)
    assert "✏️" not in left.plain
    assert "✏️" not in suffix.plain


def test_apply_status_overrides_shows_badge_after_coder_real_diff_propagates(
    tmp_path: Path,
) -> None:
    """A coder diff still wins over the planner's plan/prompt-only diff."""
    plan_diff = tmp_path / "commit_diff.diff"
    code_diff = tmp_path / "code.diff"
    _write_git_diff(plan_diff, "sdd/plans/202606/change.md")
    _write_git_diff(code_diff, "src/app.py")
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="a5n",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 11, 43, 3),
        raw_suffix="20260523114303",
        role_suffix="-plan",
        diff_path=str(plan_diff),
        agent_name="a5n",
        agent_family="a5n",
        agent_family_role="root",
        plan_chain_root=True,
        plan_action="tale",
    )
    code_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="a5n-code",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 23, 11, 46, 30),
        parent_timestamp="20260523114303",
        role_suffix="-code",
        diff_path=str(code_diff),
    )

    _apply_status_overrides([parent, code_child], classify_diff_badges=False)

    assert parent.status == "WORKING TALE"
    assert parent.diff_path == str(code_diff)
    # Persisted diff-badge classification is deferred off the loader pass
    # (see AgentDiffBadgeMixin); the field stays unset until that background
    # pass runs.
    assert parent.diff_has_real_edits is None

    classify_diff_badges([parent, code_child])

    assert parent.diff_has_real_edits is True
    left, suffix, _ = format_agent_option(parent, 0, is_selected=False)
    assert "✏️" not in left.plain
    assert "a5n (WORKING TALE)" in left.plain
    assert suffix.plain == "✏️"


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

    assert parent.status == "WORKING PLAN"
    assert parent.model == "root-model"
    assert parent.llm_provider == "claude"
    assert parent.vcs_provider == "Mercurial"
    assert parent.workspace_num == 7
    assert parent.workspace_dir == "/tmp/root"
