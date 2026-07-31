"""Agent-family status helpers for TUI status overrides."""

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
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_base,
    agent_family_phase_name,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
)
from sase.sdd.plan_tiers import cached_plan_tier

from ._agent_status_roles import agent_family_role
from .agent import Agent, AgentType


APPROVED_PLAN_ACTIONS = frozenset({"approve", "tale", "epic", "commit"})
APPROVED_PLANNER_ACTIONS = frozenset({"approve", "tale"})
PLANNER_FAMILY_ROLES = frozenset({"plan", "feedback"})
EPIC_CREATED_STATUS = "EPIC CREATED"

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


def pending_plan_status_for_agent(agent: Agent) -> str:
    """Return an agent's tier-aware pending plan-review status."""
    plan_path = agent.archived_plan_path or agent.plan_path or agent.sdd_plan_path
    return pending_plan_status_for_tier(cached_plan_tier(plan_path))


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


def _is_plan_chain_family_member(agent: Agent) -> bool:
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


def _is_natively_recognized_plan_root(agent: Agent) -> bool:
    """Whether ``is_root_plan_workflow`` would hold without the derived marker.

    Used to scope :func:`pull_plan_metadata_from_family_members` to roots that
    are plan-family roots *only* because of ``derived_plan_family_root``.
    Native plan-chain roots keep their pre-existing metadata untouched, even
    on the rare durable shape where a native root has no ``plan_action`` of
    its own (e.g. it asked a question before a continuation ever planned):
    that combination predates this fix and must not change behavior here.
    """
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
        if any(_is_plan_chain_family_member(child) for child in children):
            parent.derived_plan_family_root = True


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
    if not agent.parent_timestamp or not agent.is_family_member_child:
        return False
    # Feedback/code rows can ask their own questions; only root-question
    # continuations inherit the asker's question timestamp by construction.
    if agent_family_role(agent) != "q" and agent.agent_family_role != "q":
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


def _family_followup_children(
    parent: Agent,
    all_agents: list[Agent] | None = None,
    children_by_parent: dict[str, list[Agent]] | None = None,
) -> list[Agent]:
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


def _approved_planner_status(
    parent: Agent,
    all_agents: list[Agent] | None = None,
    children_by_parent: dict[str, list[Agent]] | None = None,
) -> str | None:
    """Return the sticky approved status for a logical planner child."""
    children = _family_followup_children(parent, all_agents, children_by_parent)
    code_children = [child for child in children if agent_family_role(child) == "code"]
    if parent.plan_action not in APPROVED_PLANNER_ACTIONS and not code_children:
        return None
    if (
        parent.plan_action == "tale"
        or parent.status in {TALE_APPROVED_STATUS, "TALE DONE"}
        or any(child.plan_action == "tale" for child in code_children)
    ):
        return TALE_APPROVED_STATUS
    return PLAN_APPROVED_STATUS


def _approved_epic_planner_status(parent: Agent) -> str | None:
    """Return the durable host-owned epic handoff status for a planner row."""
    is_epic_approved = parent.plan_action == "epic" or parent.status in {
        EPIC_APPROVED_STATUS,
        EPIC_CREATED_STATUS,
    }
    if not is_epic_approved:
        return None
    if parent.epic_bead_id:
        return EPIC_CREATED_STATUS
    return EPIC_APPROVED_STATUS


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


def is_answered_continuation_asker(
    agent: Agent,
    children_by_parent: dict[str, list[Agent]],
) -> bool:
    """Return True for a question continuation whose answer handed off."""
    if agent.status != "DONE":
        return False
    if not agent.parent_timestamp or not agent.is_family_member_child:
        return False
    if agent_family_role(agent) != "q":
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
    if agent_family_role(agent) != "q":
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


def planner_child_status(
    parent: Agent,
    all_agents: list[Agent] | None = None,
    children_by_parent: dict[str, list[Agent]] | None = None,
    *,
    logical_child: Agent | None = None,
) -> str:
    """Status for the logical planner child derived from a family root."""
    if parent.status in {
        "STARTING",
        "WAITING",
        "QUEUED",
        "RUNNING",
        "FAILED",
        "PLAN REJECTED",
    }:
        return parent.status
    if parent.status in {"QUESTION", "ANSWERED"}:
        return parent.status
    has_followup_child = all_agents is not None and has_family_followup_child(
        parent,
        all_agents,
        children_by_parent,
        exclude=logical_child,
    )
    if has_followup_child and parent.questions_times and not parent.plan_times:
        return "ANSWERED"
    epic_status = _approved_epic_planner_status(parent)
    if epic_status is not None:
        return epic_status
    approved_status = _approved_planner_status(parent, all_agents, children_by_parent)
    if approved_status is not None:
        return approved_status
    if has_followup_child:
        return "DONE"
    if has_unanswered_completed_question(parent):
        return "QUESTION"
    if is_awaiting_plan_review(parent):
        return pending_plan_status_for_agent(parent)
    return "DONE"


def _answered_asker_freeze_time(
    parent: Agent,
    child_status: str,
    all_agents: list[Agent] | None = None,
    children_by_parent: dict[str, list[Agent]] | None = None,
) -> datetime | None:
    """Return the answer-time stop marker for a handed-off asker row."""
    if child_status != "ANSWERED":
        return None
    if not parent.questions_times:
        return None
    if all_agents is None:
        return None
    if not has_family_followup_child(parent, all_agents, children_by_parent):
        return None
    return max(parent.questions_times)


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
    freeze_time = _answered_asker_freeze_time(
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
    """Backfill a plan-family root's tale/plan flavor from its planner member.

    Scoped to roots that are plan-family roots *only* because of
    ``derived_plan_family_root`` (see :func:`_is_natively_recognized_plan_root`):
    a promoted root has no ``plan_action`` of its own, so the newest
    plan-chain member's metadata is pulled up so the root's tale/plan flavor
    resolves correctly. Native plan-chain roots are left untouched — their
    artifact directory is the planner's own, so pulling member metadata onto
    them is unnecessary and, for at least one durable pre-fix shape (a native
    root that asked a question before any continuation ever planned), would
    change already-established behavior. Deliberately does not propagate
    ``plan_times``: giving the root borrowed ``plan_times`` would flip its own
    logical child's status from ``ANSWERED`` to a plan-approved status in
    :func:`planner_child_status`.
    """
    for parent_timestamp, children in children_by_parent.items():
        parent = parent_by_suffix.get(parent_timestamp)
        if (
            parent is None
            or not is_root_plan_workflow(parent)
            or _is_natively_recognized_plan_root(parent)
        ):
            continue
        members = sorted(
            (child for child in children if _is_plan_chain_family_member(child)),
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
            and (is_main_workflow_agent_step(agent) or agent.is_family_member_child)
            for agent in all_agents
        )
        if has_existing_child:
            continue
        family = agent_family_name(parent) or parent.agent_name or parent.display_name
        planner_name = agent_family_phase_name(family, child_suffix)
        child_role = agent_family_role_for_suffix(child_suffix)
        child_status = planner_child_status(parent, all_agents)
        freeze_time = _answered_asker_freeze_time(parent, child_status, all_agents)
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
