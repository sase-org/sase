"""Family identity, topology, and relationship helpers for agent statuses."""

from datetime import datetime

from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_base,
    canonical_plan_chain_suffix,
)

from ._agent_status_roles import agent_family_role
from .agent import Agent, AgentType


# Family-member roles/suffixes that mark a family as having entered a plan
# chain. Ordinary question continuations are excluded: a question handoff on
# its own does not make a family a plan family.
PLAN_CHAIN_MEMBER_ROLES = frozenset({"plan", "code", "epic", "commit", "feedback"})
_PLAN_CHAIN_MEMBER_SUFFIXES = frozenset(
    {
        PLAN_CHAIN_PLAN_SUFFIX,
        PLAN_CHAIN_CODER_SUFFIX,
        PLAN_CHAIN_EPIC_SUFFIX,
        PLAN_CHAIN_COMMIT_SUFFIX,
    }
)


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


def is_plan_chain_family_member(agent: Agent) -> bool:
    """Return True when a family member row belongs to a plan chain.

    The suffix clause catches a rename-on-attach continuation whose stored
    ``agent_family_role`` predates a later plan submission; its canonical
    suffix already reads ``--plan`` even if the stored role did not change.
    """
    if agent.agent_family_parallel or not agent.is_family_member_child:
        return False
    if agent_family_role(agent) in PLAN_CHAIN_MEMBER_ROLES:
        return True
    canonical = canonical_plan_chain_suffix(agent.role_suffix)
    if canonical is not None and (
        canonical in _PLAN_CHAIN_MEMBER_SUFFIXES
        or canonical.startswith(PLAN_CHAIN_PLAN_SUFFIX)
    ):
        return True
    return bool(agent.plan_times)


def is_root_plan_workflow(agent: Agent) -> bool:
    """Check if an agent is the top-level plan workflow entry.

    True from durable root metadata recorded at promotion time
    (``plan_chain_root``, or a native ``--plan`` role suffix), or from a plan
    chain the family entered later (``derived_plan_family_root``, set by
    :func:`mark_derived_plan_family_roots` when a promoted root's members
    reveal a plan chain that started after the root was promoted).
    """
    if agent.is_child_row or agent.agent_family_parallel:
        return False
    if agent.plan_chain_root:
        return True
    if agent.derived_plan_family_root:
        return True
    return agent.agent_type == AgentType.WORKFLOW and (
        canonical_plan_chain_suffix(agent.role_suffix) == PLAN_CHAIN_PLAN_SUFFIX
    )


def is_natively_recognized_plan_root(agent: Agent) -> bool:
    """Whether a root would be recognized without its derived marker."""
    if agent.is_child_row or agent.agent_family_parallel:
        return False
    if agent.plan_chain_root:
        return True
    return agent.agent_type == AgentType.WORKFLOW and (
        canonical_plan_chain_suffix(agent.role_suffix) == PLAN_CHAIN_PLAN_SUFFIX
    )


def mark_derived_plan_family_roots(
    children_by_parent: dict[str, list[Agent]],
    parent_by_suffix: dict[str, Agent],
) -> None:
    """Mark promoted family roots whose members reveal a later plan chain.

    Sticky: only ever sets the marker, never clears it, so a family that has
    entered a plan chain never leaves it across repeated normalization passes
    over the same in-memory rows (including after an artifact-delta merge
    that may carry a partial agent list).
    """
    for parent_timestamp, children in children_by_parent.items():
        parent = parent_by_suffix.get(parent_timestamp)
        if parent is None or not parent.is_family_root_entry:
            continue
        if any(is_plan_chain_family_member(child) for child in children):
            parent.derived_plan_family_root = True


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
    if agent.is_workflow_step_child:
        return is_main_workflow_agent_step(agent)
    return agent.is_family_member_child


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
                if child.is_family_member_child
            ),
            default=None,
        )
        if latest is not None:
            latest_by_parent[parent_timestamp] = latest
    return latest_by_parent


def has_later_family_continuation(
    agent: Agent,
    children_by_parent: dict[str, list[Agent]],
) -> bool:
    """Return True when a non-workflow sibling launched after this row."""
    if not agent.parent_timestamp:
        return False
    launched_at = child_launch_time(agent)
    return any(
        sibling is not agent
        and sibling.parent_timestamp == agent.parent_timestamp
        and sibling.is_family_member_child
        and child_launch_time(sibling) > launched_at
        for sibling in children_by_parent.get(agent.parent_timestamp, [])
    )


def root_child_suffix(parent: Agent) -> str:
    return canonical_plan_chain_suffix(parent.role_suffix) or PLAN_CHAIN_PLAN_SUFFIX
