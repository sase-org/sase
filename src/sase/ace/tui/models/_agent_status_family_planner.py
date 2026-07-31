"""Planner-child metadata synchronization and materialization helpers."""

from sase.plan_chain import (
    agent_family_phase_name,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
)

from ._agent_status_family_core import (
    agent_family_name,
    child_launch_time,
    is_natively_recognized_plan_root,
    is_plan_chain_family_member,
    is_main_workflow_agent_step,
    is_root_plan_workflow,
    root_child_suffix,
)
from ._agent_status_family_policy import (
    answered_asker_freeze_time,
    planner_child_status,
)
from .agent import Agent, AgentType


def sync_planner_child_from_parent(
    parent: Agent,
    child: Agent,
    all_agents: list[Agent] | None = None,
    children_by_parent: dict[str, list[Agent]] | None = None,
) -> None:
    """Copy root planner metadata onto a concrete or synthetic planner child."""
    child.status = planner_child_status(
        parent,
        all_agents,
        children_by_parent,
        logical_child=child,
    )
    freeze_time = answered_asker_freeze_time(
        parent, child.status, all_agents, children_by_parent
    )
    if freeze_time is not None:
        child.stop_time = freeze_time
    if not child.plan_times:
        child.plan_times = list(parent.plan_times)
    if not child.feedback_times:
        child.feedback_times = list(parent.feedback_times)
    if not child.feedback_plan_paths:
        child.feedback_plan_paths = dict(parent.feedback_plan_paths)
    child.questions_times = list(parent.questions_times)
    child.question_request_path = parent.question_request_path
    child.question_response_path = parent.question_response_path
    child.question_session_id = parent.question_session_id
    if parent.response_path and not child.response_path:
        child.response_path = parent.response_path
    if parent.diff_path and not child.diff_path:
        child.diff_path = parent.diff_path
    if parent.extra_files and not child.extra_files:
        child.extra_files = list(parent.extra_files)
    copy_missing_plan_metadata(child, parent)


def copy_missing_plan_metadata(target: Agent, source: Agent) -> None:
    """Backfill associated-plan state without replacing child-owned values."""
    if target.archived_plan_path is None:
        target.archived_plan_path = source.archived_plan_path
    if target.sdd_plan_path is None:
        target.sdd_plan_path = source.sdd_plan_path
    if target.epic_plan_ref is None:
        target.epic_plan_ref = source.epic_plan_ref
    if target.plan_committed is None:
        target.plan_committed = source.plan_committed
    if target.plan_action is None:
        target.plan_action = source.plan_action
    if target.plan_path is None:
        target.plan_path = source.plan_path
    if target.epic_bead_id is None:
        target.epic_bead_id = source.epic_bead_id
    if target.phase_bead_id is None:
        target.phase_bead_id = source.phase_bead_id


def pull_plan_metadata_from_family_members(
    children_by_parent: dict[str, list[Agent]],
    parent_by_suffix: dict[str, Agent],
) -> None:
    """Backfill a derived plan-family root's flavor from its planner member.

    Native plan-chain roots keep their pre-existing metadata untouched. Their
    artifact directory is the planner's own, so pulling member metadata onto
    them is unnecessary and can alter established question-first behavior.
    ``plan_times`` is deliberately not propagated because borrowed timestamps
    would change the logical planner child's status.
    """
    for parent_timestamp, children in children_by_parent.items():
        parent = parent_by_suffix.get(parent_timestamp)
        if (
            parent is None
            or not is_root_plan_workflow(parent)
            or is_natively_recognized_plan_root(parent)
        ):
            continue
        members = sorted(
            (child for child in children if is_plan_chain_family_member(child)),
            key=child_launch_time,
            reverse=True,
        )
        for member in members:
            copy_missing_plan_metadata(parent, member)


def copy_missing_display_metadata(parent: Agent, child: Agent) -> None:
    """Backfill root display/runtime metadata from a mirrored child."""
    if parent.model is None and child.model is not None:
        parent.model = child.model
    if parent.llm_provider is None and child.llm_provider is not None:
        parent.llm_provider = child.llm_provider
    if parent.vcs_provider is None and child.vcs_provider is not None:
        parent.vcs_provider = child.vcs_provider
    if parent.workspace_num is None and child.workspace_num is not None:
        parent.workspace_num = child.workspace_num
    if parent.workspace_dir is None and child.workspace_dir is not None:
        parent.workspace_dir = child.workspace_dir
    copy_missing_plan_metadata(parent, child)


def ensure_synthetic_planner_children(
    agents: list[Agent],
    all_agents: list[Agent],
    parent_by_suffix: dict[str, Agent],
) -> None:
    """Add a logical root child when no concrete main agent step exists."""
    for parent in list(parent_by_suffix.values()):
        if not is_root_plan_workflow(parent) or not parent.raw_suffix:
            continue
        child_suffix = root_child_suffix(parent)
        has_existing_child = any(
            agent.parent_timestamp == parent.raw_suffix
            and canonical_plan_chain_suffix(agent.role_suffix) == child_suffix
            and (is_main_workflow_agent_step(agent) or agent.is_family_member_child)
            for agent in all_agents
        )
        if has_existing_child:
            continue
        family = agent_family_name(parent) or parent.agent_name or parent.display_name
        planner_name = agent_family_phase_name(family, child_suffix)
        child_role = agent_family_role_for_suffix(child_suffix)
        child_status = planner_child_status(parent, all_agents)
        freeze_time = answered_asker_freeze_time(parent, child_status, all_agents)
        planner = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=planner_name,
            project_file=parent.project_file,
            status=child_status,
            start_time=parent.run_start_time or parent.start_time,
            run_start_time=parent.run_start_time,
            stop_time=freeze_time or parent.stop_time,
            workflow=parent.workflow,
            parent_timestamp=parent.raw_suffix,
            role_suffix=child_suffix,
            artifacts_dir=parent.artifacts_dir,
            response_path=parent.response_path,
            diff_path=parent.diff_path,
            extra_files=list(parent.extra_files),
            plan_path=parent.plan_path,
            archived_plan_path=parent.archived_plan_path,
            sdd_plan_path=parent.sdd_plan_path,
            epic_plan_ref=parent.epic_plan_ref,
            plan_committed=parent.plan_committed,
            step_output=dict(parent.step_output) if parent.step_output else None,
            agent_name=planner_name,
            agent_family=family,
            agent_family_role=child_role,
            model=parent.model,
            llm_provider=parent.llm_provider,
            vcs_provider=parent.vcs_provider,
            workspace_num=parent.workspace_num,
            workspace_dir=parent.workspace_dir,
            plan_action=parent.plan_action,
            epic_bead_id=parent.epic_bead_id,
            phase_bead_id=parent.phase_bead_id,
        )
        planner.plan_times = list(parent.plan_times)
        planner.feedback_times = list(parent.feedback_times)
        planner.feedback_plan_paths = dict(parent.feedback_plan_paths)
        planner.questions_times = list(parent.questions_times)
        planner.question_request_path = parent.question_request_path
        planner.question_response_path = parent.question_response_path
        planner.question_session_id = parent.question_session_id
        planner.is_synthetic_planner = True
        agents.append(planner)
        all_agents.append(planner)
