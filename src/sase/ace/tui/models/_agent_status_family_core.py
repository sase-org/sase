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
# chain. ``PLAN_CHAIN_QUESTION_SUFFIX`` / role "q" are deliberately excluded:
# a question continuation on its own does not make a family a plan family.
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

    The suffix clause is what catches a rename-on-attach continuation whose
    stored ``agent_family_role`` predates a later plan submission (e.g. a
    root-question continuation rewritten to ``--plan`` when it submitted a
    tale/plan): its role is still "q" but its canonical suffix already reads
    "--plan".
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


def has_family_followup_child(
    parent: Agent,
    all_agents: list[Agent],
    children_by_parent: dict[str, list[Agent]] | None = None,
    *,
    exclude: Agent | None = None,
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
        and child is not exclude
        and child.parent_timestamp == parent.raw_suffix
        and child.is_family_member_child
        for child in children
    )


def family_followup_children(
    parent: Agent,
    all_agents: list[Agent] | None = None,
    children_by_parent: dict[str, list[Agent]] | None = None,
) -> list[Agent]:
    """Return concrete family-member children belonging to a parent row."""
    if not parent.raw_suffix:
        return []
    children = (
        children_by_parent.get(parent.raw_suffix, [])
        if children_by_parent is not None
        else all_agents or []
    )
    return [
        child
        for child in children
        if child is not parent
        and child.parent_timestamp == parent.raw_suffix
        and child.is_family_member_child
    ]


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


def _loaded_family_root_identity(agent: Agent) -> tuple[str, str | None, str] | None:
    """Return the durable identity key for one loaded family-root row."""
    if not agent.is_family_root_entry or not agent.raw_suffix or not agent.agent_family:
        return None
    return (agent.project_file, agent.agent_clan_generation, agent.agent_family)


def normalize_monitor_family_display_parents(all_agents: list[Agent]) -> None:
    """Reroot monitor-member rows onto their loaded family root for display.

    A monitor started by a mid-family continuation (e.g. an approved coder)
    persists a direct ``parent_timestamp`` back to that continuation instead
    of to the family root -- durable data monitor follow-up settlement relies
    on to fork the starter safely. The Agents tab treats ``parent_timestamp``
    as the display-containment link though, so left alone the monitor is
    nested under an already-completed child row instead of surfacing as a
    live family member, and the collapsed root wrongly appears terminal while
    the monitor is still running.

    This rewrites only the in-memory ``parent_timestamp`` used for display
    grouping; the persisted monitor/starter metadata on disk is never
    touched. It is a no-op for monitors already parented directly to their
    root, for monitors outside any loaded family, and whenever the family
    identity does not resolve to exactly one loaded root (including
    same-name families in different projects or clan generations) -- always
    failing safe rather than attaching a monitor to an unrelated row.
    Idempotent: repeated calls over the same (possibly cached) agent objects
    recompute the same fixed point.
    """
    roots: dict[tuple[str, str | None, str], Agent | None] = {}
    for agent in all_agents:
        identity = _loaded_family_root_identity(agent)
        if identity is None:
            continue
        roots[identity] = None if identity in roots else agent

    for agent in all_agents:
        if (
            not agent.is_monitor
            or agent.parent_timestamp is None
            or not agent.agent_family
        ):
            continue
        identity = (agent.project_file, agent.agent_clan_generation, agent.agent_family)
        root = roots.get(identity)
        if root is None or root.raw_suffix is None:
            continue
        agent.parent_timestamp = root.raw_suffix
