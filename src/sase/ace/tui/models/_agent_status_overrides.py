"""Workflow relationship status overrides for TUI agents."""

from datetime import datetime

from sase.plan_chain import (
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_base,
    agent_family_role_for_suffix,
    agent_family_phase_name,
    canonical_plan_chain_suffix,
    is_plan_feedback_suffix,
)

from .agent import Agent, AgentType
from ._diff_badge import diff_has_real_edits


_APPROVED_PLAN_ACTIONS = frozenset({"approve", "tale", "epic", "legend", "commit"})


def is_feedback_suffix(
    suffix: str | None,
    *,
    agent_family_role: str | None = None,
) -> bool:
    """Check if a role suffix is a plan feedback round (e.g., "--2" or ".2")."""
    return is_plan_feedback_suffix(suffix, agent_family_role=agent_family_role)


def is_coder_followup_suffix(
    suffix: str | None,
    *,
    agent_family_role: str | None = None,
) -> bool:
    """Check if a role suffix is the coder follow-up suffix."""
    role = agent_family_role_for_suffix(
        suffix,
        agent_family_role=agent_family_role,
    )
    return role == "code"


def _agent_family_role(agent: Agent) -> str | None:
    return agent_family_role_for_suffix(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )


def _is_feedback_agent(agent: Agent) -> bool:
    return is_feedback_suffix(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )


def _is_coder_agent(agent: Agent) -> bool:
    return is_coder_followup_suffix(
        agent.role_suffix,
        agent_family_role=agent.agent_family_role,
    )


def _append_unique_timestamps(target: list[datetime], source: list[datetime]) -> None:
    """Append timestamps from source that are not already present in target."""
    existing = set(target)
    for timestamp in source:
        if timestamp not in existing:
            target.append(timestamp)
            existing.add(timestamp)


def _merge_feedback_plan_paths(parent: Agent, child: Agent) -> None:
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


def _is_awaiting_plan_review(agent: Agent) -> bool:
    """Return True when latest plan submission is newer than latest feedback."""
    if not agent.plan_times:
        return False
    return not agent.feedback_times or agent.plan_times[-1] > agent.feedback_times[-1]


def _has_unanswered_completed_question(
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


def _has_unreviewed_submitted_plan(agent: Agent, all_agents: list[Agent]) -> bool:
    """Return True when a completed row's submitted plan still awaits review."""
    if agent.status != "DONE" or not agent.plan_times:
        return False
    if agent.plan_action in _APPROVED_PLAN_ACTIONS:
        return False
    if not _is_awaiting_plan_review(agent):
        return False
    return not _feedback_child_progressed_past_review(agent, all_agents)


def _done_handoff_status(parent: Agent, child: Agent) -> str:
    if (
        parent.plan_action == "tale"
        or child.plan_action == "tale"
        or parent.status in {"TALE APPROVED", "TALE DONE"}
    ):
        return "TALE DONE"
    return "PLAN DONE"


def _active_approved_plan_handoff_status(parent: Agent, child: Agent) -> str | None:
    """Return the visible status for an active approved-plan code handoff."""
    if child.parent_workflow or child.status != "RUNNING":
        return None
    if not _is_coder_agent(child):
        return None
    if (
        parent.plan_action == "tale"
        or child.plan_action == "tale"
        or parent.status in {"TALE APPROVED", "TALE DONE"}
    ):
        return "TALE APPROVED"
    return "PLAN APPROVED"


def _is_completed_plan_handoff_child(agent: Agent) -> bool:
    """Return True for completed approved-plan continuation rows."""
    if agent.status != "DONE":
        return False
    role = _agent_family_role(agent)
    if role == "code":
        return True
    if role == "feedback" and agent.question_response_path:
        return True
    return False


def _is_completed_epic_followup_child(agent: Agent) -> bool:
    """Return True for completed epic creation follow-up rows."""
    return agent.status == "DONE" and _agent_family_role(agent) == "epic"


def _agent_family_name(agent: Agent) -> str | None:
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


def _child_launch_time(agent: Agent) -> datetime:
    return agent.run_start_time or agent.start_time or datetime.min


def _is_main_workflow_agent_step(agent: Agent) -> bool:
    return (
        agent.parent_workflow is not None
        and agent.step_type == "agent"
        and agent.parent_step_index is None
    )


def _is_family_child(agent: Agent, parent: Agent) -> bool:
    if not parent.raw_suffix or agent.parent_timestamp != parent.raw_suffix:
        return False
    if agent.parent_workflow:
        return _is_main_workflow_agent_step(agent)
    return True


def _has_family_followup_child(parent: Agent, all_agents: list[Agent]) -> bool:
    if not parent.raw_suffix:
        return False
    return any(
        child is not parent
        and child.parent_timestamp == parent.raw_suffix
        and not child.parent_workflow
        for child in all_agents
    )


def _feedback_child_progressed_past_review(
    agent: Agent,
    all_agents: list[Agent],
) -> bool:
    """Return True when a feedback round's revised plan was already accepted."""
    if agent.plan_action in _APPROVED_PLAN_ACTIONS:
        return True
    if not agent.parent_timestamp:
        return False

    launched_at = _child_launch_time(agent)
    return any(
        child is not agent
        and child.parent_timestamp == agent.parent_timestamp
        and not child.parent_workflow
        and _child_launch_time(child) > launched_at
        for child in all_agents
    )


def _planner_child_status(
    parent: Agent,
    all_agents: list[Agent] | None = None,
) -> str:
    """Status for the logical planner child derived from a family root."""
    if parent.status in {"STARTING", "WAITING", "RUNNING", "FAILED", "PLAN REJECTED"}:
        return parent.status
    if parent.status in {"QUESTION", "ANSWERED"}:
        return parent.status
    if all_agents is not None and _has_family_followup_child(parent, all_agents):
        return "DONE"
    if _has_unanswered_completed_question(parent):
        return "QUESTION"
    if _is_awaiting_plan_review(parent):
        return "PLAN"
    return "DONE"


def _sync_planner_child_from_parent(
    parent: Agent,
    child: Agent,
    all_agents: list[Agent] | None = None,
) -> None:
    """Copy root planner metadata onto a concrete or synthetic planner child."""
    child.status = _planner_child_status(parent, all_agents)
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


def _copy_missing_display_metadata(parent: Agent, child: Agent) -> None:
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


def classify_live_file_change_hint(agent: Agent) -> bool | None:
    """Compute the active-workspace pencil hint for a row without a diff_path.

    This is the *expensive* classification path: it runs a live VCS diff
    (``get_vcs_provider`` + ``diff_with_untracked``) for the agent's
    workspace. It must NOT run on the startup-critical loader pass — the
    Agents TUI schedules it as deferred, coalesced background work after the
    first load applies (see ``AgentLiveHintMixin``).

    Fails closed (returns ``None``) on any error so live VCS access can never
    destabilize row rendering.
    """
    if agent.diff_path:
        return None
    from sase.ace.tui.widgets.file_panel._diff import live_agent_file_change_hint

    try:
        return live_agent_file_change_hint(agent)
    except Exception:
        return None


def _classify_diff_badges(agents: list[Agent]) -> None:
    """Classify cheap persisted diff badges for every agent.

    Only reads the finalized ``diff_path`` artifact, which is fast and never
    touches a workspace or VCS provider. The live workspace pencil hint for
    active rows without a ``diff_path`` is intentionally left untouched here:
    computing it inline ran hundreds of live VCS diffs on the first agents
    load and dominated startup. That work is deferred to a background pass
    (:func:`classify_live_file_change_hint`); ``live_file_change_hint`` keeps
    whatever a prior deferred pass computed (``None`` for freshly loaded
    rows).
    """
    for agent in agents:
        agent.diff_has_real_edits = (
            diff_has_real_edits(agent.diff_path) if agent.diff_path else None
        )


def _root_child_suffix(parent: Agent) -> str:
    return canonical_plan_chain_suffix(parent.role_suffix) or PLAN_CHAIN_PLAN_SUFFIX


def _ensure_synthetic_planner_children(
    agents: list[Agent],
    all_agents: list[Agent],
    parent_by_suffix: dict[str, Agent],
) -> None:
    """Add a logical root child when no concrete main agent step exists."""
    for parent in list(parent_by_suffix.values()):
        if not is_root_plan_workflow(parent) or not parent.raw_suffix:
            continue
        child_suffix = _root_child_suffix(parent)
        has_existing_child = any(
            agent.parent_timestamp == parent.raw_suffix
            and canonical_plan_chain_suffix(agent.role_suffix) == child_suffix
            and (_is_main_workflow_agent_step(agent) or not agent.parent_workflow)
            for agent in all_agents
        )
        if has_existing_child:
            continue
        family = _agent_family_name(parent) or parent.agent_name or parent.display_name
        planner_name = agent_family_phase_name(family, child_suffix)
        child_role = agent_family_role_for_suffix(child_suffix)
        planner = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=planner_name,
            project_file=parent.project_file,
            status=_planner_child_status(parent, all_agents),
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


def apply_status_overrides(
    agents: list[Agent],
    workflow_agent_steps: list[Agent] | None = None,
    *,
    classify_diff_badges: bool = True,
) -> None:
    """Override statuses based on workflow relationships (mutates in place).

    Agent-family roots act as containers: their visible status mirrors the
    newest planner/feedback/question/code child.  The pass still propagates
    child timestamps, diff paths, and meta_* fields back to the root for the
    detail panel.

    Compatibility behavior for non-family agents remains:
    - DONE -> QUESTION: agent submitted a question that was never answered
    - DONE -> PLAN: agent submitted a plan that was never reviewed
    """
    all_agents = [*agents, *(workflow_agent_steps or [])]
    for agent in all_agents:
        agent.followup_agents.clear()

    completed_statuses = {"DONE", "FAILED", "FAILED (RETRIED)", "PLAN REJECTED"}

    parent_by_suffix: dict[str, Agent] = {}
    for agent in all_agents:
        if agent.raw_suffix and not agent.is_workflow_child:
            parent_by_suffix[agent.raw_suffix] = agent

    _ensure_synthetic_planner_children(agents, all_agents, parent_by_suffix)

    # Propagate timestamps from feedback round children (.2, .3, ...) to parent
    # so the metadata panel shows one entry per proposal/feedback/question round.
    for agent in all_agents:
        if (
            agent.parent_timestamp
            and not agent.parent_workflow
            and _is_feedback_agent(agent)
        ):
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent:
                if agent.plan_times:
                    _append_unique_timestamps(parent.plan_times, agent.plan_times)
                if agent.feedback_times:
                    _append_unique_timestamps(
                        parent.feedback_times, agent.feedback_times
                    )
                    _merge_feedback_plan_paths(parent, agent)
                if agent.questions_times:
                    _append_unique_timestamps(
                        parent.questions_times, agent.questions_times
                    )
                if agent.question_request_path:
                    parent.question_request_path = agent.question_request_path
                if agent.question_response_path:
                    parent.question_response_path = agent.question_response_path
                if agent.question_session_id:
                    parent.question_session_id = agent.question_session_id

    # Active workflow step child -> parent is running a step, not planning.
    for agent in all_agents:
        if agent.parent_workflow and agent.parent_timestamp:
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent and agent.status not in completed_statuses:
                if parent.status == "PLAN":
                    parent.status = "RUNNING"

    # Pre-compute which agents have follow-up children so unanswered questions
    # can distinguish "waiting for user" from "answered and continued".
    parents_with_followup: set[str] = set()
    for agent in all_agents:
        if agent.parent_timestamp and not agent.parent_workflow:
            parents_with_followup.add(agent.parent_timestamp)

    for agent in all_agents:
        if (
            agent.parent_workflow
            and agent.parent_timestamp
            and _is_main_workflow_agent_step(agent)
        ):
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if (
                parent
                and is_root_plan_workflow(parent)
                and canonical_plan_chain_suffix(agent.role_suffix)
                == _root_child_suffix(parent)
            ):
                _sync_planner_child_from_parent(parent, agent, all_agents)
        elif (
            _is_feedback_agent(agent)
            and agent.status in {"DONE", "RUNNING"}
            and _is_awaiting_plan_review(agent)
        ):
            agent.status = (
                "DONE"
                if _feedback_child_progressed_past_review(agent, all_agents)
                else "PLAN"
            )

    for agent in all_agents:
        if (
            agent.parent_timestamp
            and not agent.parent_workflow  # Follow-up agent, not workflow step
        ):
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent:
                role = _agent_family_role(agent)
                if _has_unanswered_completed_question(agent, parents_with_followup):
                    agent.status = "QUESTION"

                # Propagate meta_* fields from follow-up child to parent
                # so the metadata panel shows dynamic variables (e.g. Commit
                # Message) on the main workflow entry too.
                if agent.step_output and isinstance(agent.step_output, dict):
                    meta_fields = {
                        k: v
                        for k, v in agent.step_output.items()
                        if k.startswith("meta_") and v
                    }
                    if meta_fields:
                        if parent.step_output is None:
                            parent.step_output = {}
                        parent.step_output.update(meta_fields)

                # Propagate code_time from coder follow-up to parent so
                # the metadata panel shows when the coder was launched.
                if _is_coder_agent(agent):
                    parent.code_time = agent.run_start_time or agent.start_time
                if role == "epic":
                    parent.epic_time = (
                        agent.epic_time or agent.run_start_time or agent.start_time
                    )

                # Propagate diff_path from follow-up child to parent so the
                # file panel can display the code diff (more relevant than
                # the planner's own diff). Planner rows only fill a missing
                # parent diff; synthetic planner rows copy the parent diff and
                # must not clobber a coder diff propagated earlier in the pass.
                if agent.diff_path and (role != "plan" or not parent.diff_path):
                    parent.diff_path = agent.diff_path

    # Override DONE -> QUESTION for agents whose last question was never answered.
    # A persisted question_response_path means the row resumed after user input;
    # pending_question.json remains the active-row signal before completion.
    for agent in all_agents:
        if _has_unanswered_completed_question(agent, parents_with_followup):
            agent.status = "QUESTION"

    # Override DONE -> PLAN for rows whose submitted plan still awaits manual
    # review. This mirrors the QUESTION catch-all and covers planner entries
    # that fall through suffix-gated workflow-step/feedback branches above.
    for agent in all_agents:
        if _has_unreviewed_submitted_plan(agent, all_agents):
            agent.status = "PLAN"

    # Active family code handoff rows display the plan approval state while the
    # implementation agent runs. Normalize before root mirroring so the family
    # root reflects PLAN APPROVED / TALE APPROVED instead of raw RUNNING.
    for agent in all_agents:
        if not (agent.parent_timestamp and not agent.parent_workflow):
            continue
        parent = parent_by_suffix.get(agent.parent_timestamp)
        if parent and is_root_plan_workflow(parent):
            handoff_status = _active_approved_plan_handoff_status(parent, agent)
            if handoff_status:
                agent.status = handoff_status

    # Completed family handoff rows are semantic terminal states rather than
    # plain DONE. Do this after QUESTION normalization so unanswered rows keep
    # their blocked status, and before root mirroring so the root sees it.
    for agent in all_agents:
        if not (agent.parent_timestamp and not agent.parent_workflow):
            continue
        parent = parent_by_suffix.get(agent.parent_timestamp)
        if not (parent and is_root_plan_workflow(parent)):
            continue
        if _is_completed_epic_followup_child(agent):
            agent.status = "EPIC CREATED"
        elif _is_completed_plan_handoff_child(agent):
            agent.status = _done_handoff_status(parent, agent)

    # Attach all follow-up agents to their parent's followup_agents list.
    for agent in all_agents:
        if agent.parent_timestamp and not agent.parent_workflow:
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent:
                parent.followup_agents.append(agent)

    # Sort follow-up agents chronologically (oldest first).
    for agent in all_agents:
        if agent.followup_agents:
            agent.followup_agents.sort(key=lambda a: a.start_time or datetime.min)

    # Agent-family roots mirror the newest logical child. This runs after child
    # statuses are normalized so active coder, failed latest child, and
    # awaiting-review planner/feedback rows all flow directly to the root.
    for parent in parent_by_suffix.values():
        if not is_root_plan_workflow(parent):
            continue
        children = [
            child
            for child in all_agents
            if child is not parent and _is_family_child(child, parent)
        ]
        if not children:
            continue
        newest = max(children, key=_child_launch_time)
        parent.status = newest.status
        _copy_missing_display_metadata(parent, newest)

    # Spawn-on-retry: build the retry-chain linkage. Each retry child has a
    # backward pointer (retry_of_timestamp) to its immediate parent; we
    # reverse-index that into the parent's retry_chain_siblings list so the
    # TUI can render the chain from either direction.
    by_suffix: dict[str, Agent] = {}
    for agent in all_agents:
        if agent.raw_suffix and not agent.is_workflow_child:
            by_suffix[agent.raw_suffix] = agent
    for agent in all_agents:
        if agent.retry_of_timestamp:
            parent = by_suffix.get(agent.retry_of_timestamp)
            if parent is not None:
                parent.retry_chain_siblings.append(agent)
    for agent in all_agents:
        if agent.retry_chain_siblings:
            agent.retry_chain_siblings.sort(
                key=lambda a: a.retry_attempt or 0,
            )

    if classify_diff_badges:
        _classify_diff_badges(all_agents)
