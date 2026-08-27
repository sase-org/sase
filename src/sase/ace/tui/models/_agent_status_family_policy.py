"""Status policy for sequential agent-family and plan-chain rows."""

from datetime import datetime

from sase.agent.status_buckets import (
    EPIC_APPROVED_STATUS,
    PLAN_APPROVED_STATUS,
    PLAN_COMMITTED_STATUS,
    TALE_APPROVED_STATUS,
    WORKING_PLAN_STATUS,
    WORKING_TALE_STATUS,
    pending_plan_status_for_tier,
)
from sase.plan_chain import canonical_plan_chain_suffix
from sase.sdd.plan_tiers import cached_plan_tier

from ._agent_status_family_core import (
    child_launch_time,
    has_later_family_continuation,
    is_main_workflow_agent_step,
    is_root_plan_workflow,
    root_child_suffix,
)
from ._agent_status_roles import agent_family_role
from .agent import Agent


APPROVED_PLAN_ACTIONS = frozenset({"approve", "tale", "epic", "commit"})
APPROVED_PLANNER_ACTIONS = frozenset({"approve", "tale"})
PLANNER_FAMILY_ROLES = frozenset({"plan", "feedback"})


def pending_plan_status_for_agent(agent: Agent) -> str:
    """Return an agent's tier-aware pending plan-review status."""
    plan_path = agent.archived_plan_path or agent.plan_path or agent.sdd_plan_path
    return pending_plan_status_for_tier(cached_plan_tier(plan_path))


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
    """Return True when a continuation only mirrors its parent's question."""
    if not agent.parent_timestamp or not agent.is_family_member_child:
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
        or parent.status in {TALE_APPROVED_STATUS, "TALE DONE"}
    ):
        return "TALE DONE"
    return "PLAN DONE"


def active_approved_plan_handoff_status(parent: Agent, child: Agent) -> str | None:
    """Return the visible status for an active approved-plan handoff."""
    if (
        not child.is_family_member_child
        or child.agent_family_parallel
        or child.status != "RUNNING"
    ):
        return None

    role = agent_family_role(child)
    if role == "epic":
        return EPIC_APPROVED_STATUS
    if role == "commit":
        return PLAN_COMMITTED_STATUS
    if role != "code":
        return None

    if (
        parent.plan_action == "tale"
        or child.plan_action == "tale"
        or parent.status in {TALE_APPROVED_STATUS, "TALE DONE"}
    ):
        return WORKING_TALE_STATUS
    return WORKING_PLAN_STATUS


def is_completed_plan_handoff_child(agent: Agent) -> bool:
    """Return True for completed approved-plan continuation rows."""
    if agent.agent_family_parallel or agent.status != "DONE":
        return False
    role = agent_family_role(agent)
    if role == "code":
        return True
    if role == "feedback" and agent.question_response_path:
        return True
    return False


def is_completed_epic_followup_child(agent: Agent) -> bool:
    """Return True for legacy completed epic creation follow-up rows."""
    return (
        not agent.agent_family_parallel
        and agent.status == "DONE"
        and agent_family_role(agent) == "epic"
    )


def approved_followup_planner_status(agent: Agent) -> str | None:
    """Return the sticky approved status for a concrete follow-up planner."""
    if (
        agent.agent_family_parallel
        or agent_family_role(agent) not in PLANNER_FAMILY_ROLES
    ):
        return None
    if not agent.plan_times:
        return None
    if agent.plan_action not in APPROVED_PLANNER_ACTIONS:
        return None
    if agent.plan_action == "tale":
        return TALE_APPROVED_STATUS
    return PLAN_APPROVED_STATUS


def _is_planner_family_row(agent: Agent) -> bool:
    """Return True for visible planner/replanner rows in a plan family."""
    if (
        agent.agent_family_parallel
        or agent_family_role(agent) not in PLANNER_FAMILY_ROLES
    ):
        return False
    return agent.is_family_member_child or is_main_workflow_agent_step(agent)


def superseded_by_feedback_round(
    agent: Agent,
    children_by_parent: dict[str, list[Agent]],
) -> bool:
    """Return True when a later planner-family sibling superseded this row."""
    if not agent.parent_timestamp or not _is_planner_family_row(agent):
        return False
    if not agent.plan_times:
        return False
    launched_at = child_launch_time(agent)
    return any(
        sibling is not agent
        and sibling.parent_timestamp == agent.parent_timestamp
        and _is_planner_family_row(sibling)
        and child_launch_time(sibling) > launched_at
        and bool(agent.feedback_times or sibling.feedback_times)
        for sibling in children_by_parent.get(agent.parent_timestamp, [])
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
        and child.is_family_member_child
        and child_launch_time(child) > launched_at
        for child in siblings
    )


def is_answered_continuation_asker(
    agent: Agent,
    children_by_parent: dict[str, list[Agent]],
) -> bool:
    """Return True for a family child whose answered question handed off."""
    if agent.status != "DONE":
        return False
    if not agent.parent_timestamp or not agent.is_family_member_child:
        return False
    if not agent.questions_times or not agent.question_response_path:
        return False
    return has_later_family_continuation(agent, children_by_parent)


def is_answered_root_asker_step(
    agent: Agent,
    parent_by_suffix: dict[str, Agent],
    children_by_parent: dict[str, list[Agent]],
) -> bool:
    """Return True for a family root's own step whose answer handed off.

    A rename-on-attach root's own work renders as its concrete ``main``
    workflow step, which is a workflow-step child rather than a family-member
    child, so :func:`is_answered_continuation_asker` skips it. Plan-chain roots
    are excluded because :func:`planner_child_status` already owns that row.
    """
    if agent.status != "DONE":
        return False
    if not agent.parent_timestamp or not agent.is_workflow_step_child:
        return False
    if not is_main_workflow_agent_step(agent):
        return False
    if not agent.questions_times or not agent.question_response_path:
        return False
    parent = parent_by_suffix.get(agent.parent_timestamp)
    if parent is None or not parent.is_family_root_entry:
        return False
    if is_root_plan_workflow(parent):
        return False
    if canonical_plan_chain_suffix(agent.role_suffix) != root_child_suffix(parent):
        return False
    return has_later_family_continuation(agent, children_by_parent)
