"""Agent-family status helpers for TUI status overrides."""

from datetime import datetime

from sase.plan_chain import (
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_base,
    agent_family_phase_name,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
)

from ._agent_status_roles import agent_family_role, is_coder_agent
from .agent import Agent, AgentType


APPROVED_PLAN_ACTIONS = frozenset({"approve", "tale", "epic", "legend", "commit"})


def append_unique_timestamps(target: list[datetime], source: list[datetime]) -> None:
    """Append timestamps from source that are not already present in target."""
    existing = set(target)
    for timestamp in source:
        if timestamp not in existing:
            target.append(timestamp)
            existing.add(timestamp)


def merge_feedback_plan_paths(parent: Agent, child: Agent) -> None:
    """Copy child feedback path metadata without replacing existing paths."""
    for timestamp in child.feedback_times:
        path = child.feedback_plan_paths.get(timestamp)
        if path and not parent.feedback_plan_paths.get(timestamp):
            parent.feedback_plan_paths[timestamp] = path


def is_root_plan_workflow(agent: Agent) -> bool:
    """Check if an agent is the top-level plan workflow entry."""
    if agent.is_workflow_child:
        return False
    if agent.plan_chain_root or agent.agent_family_role == "root":
        return True
    return agent.agent_type == AgentType.WORKFLOW and (
        canonical_plan_chain_suffix(agent.role_suffix) == PLAN_CHAIN_PLAN_SUFFIX
    )


def is_awaiting_plan_review(agent: Agent) -> bool:
    """Return True when latest plan submission is newer than latest feedback."""
    if not agent.plan_times:
        return False
    return not agent.feedback_times or agent.plan_times[-1] > agent.feedback_times[-1]


def has_unanswered_completed_question(
    agent: Agent,
    parents_with_followup: set[str] | None = None,
) -> bool:
    """Return True when a completed row is still blocked on user input."""
    if agent.status != "DONE" or not agent.questions_times:
        return False
    if agent.question_response_path:
        return False
    if parents_with_followup is None:
        return not agent.followup_agents
    return bool(agent.raw_suffix) and agent.raw_suffix not in parents_with_followup


def has_inherited_family_question(
    agent: Agent,
    parent_by_suffix: dict[str, Agent],
) -> bool:
    """Return True when a root-question continuation only mirrors its asker."""
    if not agent.parent_timestamp or agent.parent_workflow:
        return False
    # Feedback/code rows can ask their own questions; only root-question
    # continuations inherit the asker's question timestamp by construction.
    if agent_family_role(agent) != "q":
        return False
    parent = parent_by_suffix.get(agent.parent_timestamp)
    if parent is None:
        return False
    question_times = set(agent.questions_times)
    if not question_times:
        return False
    return question_times <= set(parent.questions_times)


def has_unreviewed_submitted_plan(
    agent: Agent,
    all_agents: list[Agent],
    children_by_parent: dict[str, list[Agent]] | None = None,
    latest_child_launch_by_parent: dict[str, datetime] | None = None,
) -> bool:
    """Return True when a completed row's submitted plan still awaits review."""
    if agent.status != "DONE" or not agent.plan_times:
        return False
    if agent.plan_action in APPROVED_PLAN_ACTIONS:
        return False
    if not is_awaiting_plan_review(agent):
        return False
    return not feedback_child_progressed_past_review(
        agent, all_agents, children_by_parent, latest_child_launch_by_parent
    )


def done_handoff_status(parent: Agent, child: Agent) -> str:
    if (
        parent.plan_action == "tale"
        or child.plan_action == "tale"
        or parent.status in {"TALE APPROVED", "TALE DONE"}
    ):
        return "TALE DONE"
    return "PLAN DONE"


def active_approved_plan_handoff_status(parent: Agent, child: Agent) -> str | None:
    """Return the visible status for an active approved-plan code handoff."""
    if child.parent_workflow or child.status != "RUNNING":
        return None
    if not is_coder_agent(child):
        return None
    if (
        parent.plan_action == "tale"
        or child.plan_action == "tale"
        or parent.status in {"TALE APPROVED", "TALE DONE"}
    ):
        return "TALE APPROVED"
    return "PLAN APPROVED"


def is_completed_plan_handoff_child(agent: Agent) -> bool:
    """Return True for completed approved-plan continuation rows."""
    if agent.status != "DONE":
        return False
    role = agent_family_role(agent)
    if role == "code":
        return True
    if role == "feedback" and agent.question_response_path:
        return True
    return False


def is_completed_epic_followup_child(agent: Agent) -> bool:
    """Return True for completed epic creation follow-up rows."""
    return agent.status == "DONE" and agent_family_role(agent) == "epic"


def agent_family_name(agent: Agent) -> str | None:
    """Return the stable family name for a root or child row."""
    if agent.agent_family:
        return agent.agent_family
    if agent.agent_name:
        base = agent_family_base(
            agent.agent_name,
            include_legacy_dash=canonical_plan_chain_suffix(agent.role_suffix)
            is not None,
        )
        if base:
            return base
    return None


def child_launch_time(agent: Agent) -> datetime:
    return agent.run_start_time or agent.start_time or datetime.min


def is_main_workflow_agent_step(agent: Agent) -> bool:
    return (
        agent.parent_workflow is not None
        and agent.step_type == "agent"
        and agent.parent_step_index is None
    )


def is_family_child(agent: Agent, parent: Agent) -> bool:
    if not parent.raw_suffix or agent.parent_timestamp != parent.raw_suffix:
        return False
    if agent.parent_workflow:
        return is_main_workflow_agent_step(agent)
    return True


def children_by_parent_timestamp(all_agents: list[Agent]) -> dict[str, list[Agent]]:
    children_by_parent: dict[str, list[Agent]] = {}
    for agent in all_agents:
        if agent.parent_timestamp:
            children_by_parent.setdefault(agent.parent_timestamp, []).append(agent)
    return children_by_parent


def latest_non_workflow_child_launch_by_parent(
    children_by_parent: dict[str, list[Agent]],
) -> dict[str, datetime]:
    latest_by_parent: dict[str, datetime] = {}
    for parent_timestamp, children in children_by_parent.items():
        latest = max(
            (
                child_launch_time(child)
                for child in children
                if not child.parent_workflow
            ),
            default=None,
        )
        if latest is not None:
            latest_by_parent[parent_timestamp] = latest
    return latest_by_parent


def has_family_followup_child(
    parent: Agent,
    all_agents: list[Agent],
    children_by_parent: dict[str, list[Agent]] | None = None,
) -> bool:
    if not parent.raw_suffix:
        return False
    children = (
        children_by_parent.get(parent.raw_suffix, [])
        if children_by_parent is not None
        else all_agents
    )
    return any(
        child is not parent
        and child.parent_timestamp == parent.raw_suffix
        and not child.parent_workflow
        for child in children
    )


def feedback_child_progressed_past_review(
    agent: Agent,
    all_agents: list[Agent],
    children_by_parent: dict[str, list[Agent]] | None = None,
    latest_child_launch_by_parent: dict[str, datetime] | None = None,
) -> bool:
    """Return True when a feedback round's revised plan was already accepted."""
    if agent.plan_action in APPROVED_PLAN_ACTIONS:
        return True
    if not agent.parent_timestamp:
        return False

    launched_at = child_launch_time(agent)
    if latest_child_launch_by_parent is not None:
        return (
            latest_child_launch_by_parent.get(agent.parent_timestamp, datetime.min)
            > launched_at
        )
    siblings = (
        children_by_parent.get(agent.parent_timestamp, [])
        if children_by_parent is not None
        else all_agents
    )
    return any(
        child is not agent
        and child.parent_timestamp == agent.parent_timestamp
        and not child.parent_workflow
        and child_launch_time(child) > launched_at
        for child in siblings
    )


def planner_child_status(
    parent: Agent,
    all_agents: list[Agent] | None = None,
    children_by_parent: dict[str, list[Agent]] | None = None,
) -> str:
    """Status for the logical planner child derived from a family root."""
    if parent.status in {"STARTING", "WAITING", "RUNNING", "FAILED", "PLAN REJECTED"}:
        return parent.status
    if parent.status in {"QUESTION", "ANSWERED"}:
        return parent.status
    if all_agents is not None and has_family_followup_child(
        parent, all_agents, children_by_parent
    ):
        if parent.questions_times and not parent.plan_times:
            return "ANSWERED"
        return "DONE"
    if has_unanswered_completed_question(parent):
        return "QUESTION"
    if is_awaiting_plan_review(parent):
        return "PLAN"
    return "DONE"


def sync_planner_child_from_parent(
    parent: Agent,
    child: Agent,
    all_agents: list[Agent] | None = None,
    children_by_parent: dict[str, list[Agent]] | None = None,
) -> None:
    """Copy root planner metadata onto a concrete or synthetic planner child."""
    child.status = planner_child_status(parent, all_agents, children_by_parent)
    child.plan_times = list(parent.plan_times)
    child.feedback_times = list(parent.feedback_times)
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


def root_child_suffix(parent: Agent) -> str:
    return canonical_plan_chain_suffix(parent.role_suffix) or PLAN_CHAIN_PLAN_SUFFIX


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
            and (is_main_workflow_agent_step(agent) or not agent.parent_workflow)
            for agent in all_agents
        )
        if has_existing_child:
            continue
        family = agent_family_name(parent) or parent.agent_name or parent.display_name
        planner_name = agent_family_phase_name(family, child_suffix)
        child_role = agent_family_role_for_suffix(child_suffix)
        planner = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=planner_name,
            project_file=parent.project_file,
            status=planner_child_status(parent, all_agents),
            start_time=parent.run_start_time or parent.start_time,
            run_start_time=parent.run_start_time,
            stop_time=parent.stop_time,
            workflow=parent.workflow,
            parent_timestamp=parent.raw_suffix,
            role_suffix=child_suffix,
            artifacts_dir=parent.artifacts_dir,
            response_path=parent.response_path,
            diff_path=parent.diff_path,
            extra_files=list(parent.extra_files),
            step_output=dict(parent.step_output) if parent.step_output else None,
            agent_name=planner_name,
            agent_family=family,
            agent_family_role=child_role,
            model=parent.model,
            llm_provider=parent.llm_provider,
            vcs_provider=parent.vcs_provider,
            workspace_num=parent.workspace_num,
            workspace_dir=parent.workspace_dir,
        )
        planner.plan_times = list(parent.plan_times)
        planner.feedback_times = list(parent.feedback_times)
        planner.feedback_plan_paths = dict(parent.feedback_plan_paths)
        planner.questions_times = list(parent.questions_times)
        planner.question_request_path = parent.question_request_path
        planner.question_response_path = parent.question_response_path
        planner.question_session_id = parent.question_session_id
        agents.append(planner)
        all_agents.append(planner)
