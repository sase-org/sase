"""Workflow relationship status overrides for TUI agents."""

from datetime import datetime

from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_base,
    agent_family_phase_name,
    canonical_plan_chain_suffix,
)

from .agent import Agent, AgentType


def is_feedback_suffix(suffix: str | None) -> bool:
    """Check if a role suffix is a plan feedback round (e.g., "-2", ".2")."""
    canonical = canonical_plan_chain_suffix(suffix)
    if not canonical or not canonical.startswith("-"):
        return False
    return canonical[1:].isdigit()


def is_coder_followup_suffix(suffix: str | None) -> bool:
    """Check if a role suffix is the coder follow-up suffix."""
    return canonical_plan_chain_suffix(suffix) == PLAN_CHAIN_CODER_SUFFIX


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


def _agent_family_name(agent: Agent) -> str | None:
    """Return the stable family name for a root or child row."""
    if agent.agent_family:
        return agent.agent_family
    if agent.agent_name:
        base = agent_family_base(agent.agent_name)
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


def _planner_child_status(parent: Agent) -> str:
    """Status for the logical planner child derived from a family root."""
    if parent.status in {"STARTING", "WAITING", "RUNNING", "FAILED", "PLAN REJECTED"}:
        return parent.status
    if parent.status == "QUESTION" or (
        parent.questions_times and not parent.followup_agents
    ):
        return "QUESTION"
    if _is_awaiting_plan_review(parent):
        return "PLAN"
    return "DONE"


def _sync_planner_child_from_parent(parent: Agent, child: Agent) -> None:
    """Copy root planner metadata onto a concrete or synthetic planner child."""
    child.status = _planner_child_status(parent)
    child.plan_times = list(parent.plan_times)
    child.feedback_times = list(parent.feedback_times)
    child.feedback_plan_paths = dict(parent.feedback_plan_paths)
    child.questions_times = list(parent.questions_times)
    if parent.response_path and not child.response_path:
        child.response_path = parent.response_path
    if parent.diff_path and not child.diff_path:
        child.diff_path = parent.diff_path
    if parent.extra_files and not child.extra_files:
        child.extra_files = list(parent.extra_files)


def _ensure_synthetic_planner_children(
    agents: list[Agent],
    all_agents: list[Agent],
    parent_by_suffix: dict[str, Agent],
) -> None:
    """Add a logical planner child when no concrete main agent step exists."""
    existing_planner_parent_ts = {
        agent.parent_timestamp
        for agent in all_agents
        if canonical_plan_chain_suffix(agent.role_suffix) == PLAN_CHAIN_PLAN_SUFFIX
        and agent.parent_timestamp
        and (_is_main_workflow_agent_step(agent) or not agent.parent_workflow)
    }
    for parent in list(parent_by_suffix.values()):
        if not is_root_plan_workflow(parent) or not parent.raw_suffix:
            continue
        if parent.raw_suffix in existing_planner_parent_ts:
            continue
        family = _agent_family_name(parent) or parent.agent_name or parent.display_name
        planner_name = agent_family_phase_name(family, PLAN_CHAIN_PLAN_SUFFIX)
        planner = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=planner_name,
            project_file=parent.project_file,
            status=_planner_child_status(parent),
            start_time=parent.run_start_time or parent.start_time,
            run_start_time=parent.run_start_time,
            stop_time=parent.stop_time,
            workflow=parent.workflow,
            parent_timestamp=parent.raw_suffix,
            role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
            artifacts_dir=parent.artifacts_dir,
            response_path=parent.response_path,
            diff_path=parent.diff_path,
            extra_files=list(parent.extra_files),
            step_output=dict(parent.step_output) if parent.step_output else None,
            agent_name=planner_name,
            agent_family=family,
            agent_family_role="plan",
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
        agents.append(planner)
        all_agents.append(planner)


def apply_status_overrides(
    agents: list[Agent], workflow_agent_steps: list[Agent] | None = None
) -> None:
    """Override statuses based on workflow relationships (mutates in place).

    Agent-family roots act as containers: their visible status mirrors the
    newest planner/feedback/question/code child.  The pass still propagates
    child timestamps, diff paths, and meta_* fields back to the root for the
    detail panel.

    Compatibility behavior for non-family agents remains:
    - DONE -> QUESTION: agent submitted a question that was never answered
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
            and is_feedback_suffix(agent.role_suffix)
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
            canonical_plan_chain_suffix(agent.role_suffix) == PLAN_CHAIN_PLAN_SUFFIX
            and agent.parent_workflow
            and agent.parent_timestamp
        ):
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent and is_root_plan_workflow(parent):
                _sync_planner_child_from_parent(parent, agent)
        elif (
            is_feedback_suffix(agent.role_suffix)
            and agent.status in {"DONE", "RUNNING"}
            and _is_awaiting_plan_review(agent)
        ):
            agent.status = "PLAN"

    for agent in all_agents:
        if (
            agent.parent_timestamp
            and not agent.parent_workflow  # Follow-up agent, not workflow step
        ):
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent:
                role_suffix = canonical_plan_chain_suffix(agent.role_suffix)
                if (
                    agent.status == "DONE"
                    and agent.questions_times
                    and agent.raw_suffix
                    and agent.raw_suffix not in parents_with_followup
                ):
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
                if is_coder_followup_suffix(agent.role_suffix):
                    parent.code_time = agent.run_start_time or agent.start_time
                if role_suffix == PLAN_CHAIN_EPIC_SUFFIX:
                    parent.epic_time = (
                        agent.epic_time or agent.run_start_time or agent.start_time
                    )

                # Propagate diff_path from follow-up child to parent so the
                # file panel can display the code diff (more relevant than
                # the planner's own diff).
                if agent.diff_path:
                    parent.diff_path = agent.diff_path

    # Override DONE -> QUESTION for agents whose last question was never answered.
    # The .q follow-up is created only AFTER a response is received, so its
    # absence with a recorded questions_submitted_at means polling was killed
    # before the user answered.
    for agent in all_agents:
        if (
            agent.status == "DONE"
            and agent.questions_times
            and agent.raw_suffix
            and agent.raw_suffix not in parents_with_followup
        ):
            agent.status = "QUESTION"

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
