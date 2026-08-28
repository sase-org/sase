"""Status policy for concrete sequential family handoff rows."""

from sase.agent.status_buckets import (
    EPIC_APPROVED_STATUS,
    PLAN_APPROVED_STATUS,
    PLAN_COMMITTED_STATUS,
    TALE_APPROVED_STATUS,
    WORKING_PLAN_STATUS,
    WORKING_TALE_STATUS,
)
from sase.plan_chain import canonical_plan_chain_suffix

from ._agent_status_family_core import (
    has_later_family_continuation,
    is_main_workflow_agent_step,
    is_root_plan_workflow,
    root_child_suffix,
)
from ._agent_status_roles import agent_family_role
from .agent import Agent


APPROVED_PLANNER_ACTIONS = frozenset({"approve", "tale"})
PLANNER_FAMILY_ROLES = frozenset({"plan", "feedback"})


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
        agent.parent_timestamp is None
        or agent.agent_family_parallel
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
    are excluded because their question state is now owned by gate-shell rows.
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
