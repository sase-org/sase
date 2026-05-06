"""Workflow relationship status overrides for TUI agents."""

from datetime import datetime

from sase.plan_chain import PLAN_CHAIN_CODER_SUFFIX

from .agent import Agent, AgentType


def is_feedback_suffix(suffix: str | None) -> bool:
    """Check if a role suffix is a plan feedback round (e.g., ".2", ".3")."""
    if not suffix or not suffix.startswith("."):
        return False
    return suffix[1:].isdigit()


def is_coder_followup_suffix(suffix: str | None) -> bool:
    """Check if a role suffix is the coder follow-up suffix."""
    return suffix == PLAN_CHAIN_CODER_SUFFIX


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
    return (
        agent.agent_type == AgentType.WORKFLOW
        and agent.role_suffix == ".plan"
        and not agent.is_workflow_child
    )


def apply_status_overrides(agents: list[Agent]) -> None:
    """Override statuses based on workflow relationships (mutates in place).

    - DONE -> PLAN APPROVED: parent has active follow-up children
    - DONE -> PLAN DONE: plan workflow where all follow-ups completed
    - DONE -> EPIC CREATED: plan workflow whose latest completed follow-up is `.epic`
    - DONE -> PLANNING: plan workflow with no follow-up spawned yet
    - DONE -> QUESTION: agent submitted a question that was never answered
    """
    completed_statuses = {"DONE", "FAILED"}

    parent_by_suffix: dict[str, Agent] = {}
    for agent in agents:
        if agent.raw_suffix and not agent.is_workflow_child:
            parent_by_suffix[agent.raw_suffix] = agent

    # Collect parents that have an active (non-completed) feedback round so
    # later overrides can treat them as actively-running rather than waiting
    # for plan review.
    parents_with_active_feedback: set[str] = set()
    for agent in agents:
        if (
            agent.parent_timestamp
            and not agent.parent_workflow
            and is_feedback_suffix(agent.role_suffix)
            and agent.status not in completed_statuses
        ):
            parents_with_active_feedback.add(agent.parent_timestamp)

    # Propagate timestamps from feedback round children (.2, .3, ...) to parent
    # so the metadata panel shows one entry per proposal/feedback/question round.
    for agent in agents:
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
                # Active feedback round -> parent is processing feedback, not
                # waiting for plan review.
                if agent.status not in completed_statuses:
                    if parent.status == "PLANNING":
                        parent.status = "RUNNING"

    # Active workflow step child -> parent is running a step, not planning.
    for agent in agents:
        if agent.parent_workflow and agent.parent_timestamp:
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent and agent.status not in completed_statuses:
                if parent.status == "PLANNING":
                    parent.status = "RUNNING"

    parents_with_followup: set[str] = set()
    # Iterate children in start-time order so that, if multiple are active, the
    # most-recently-started child's role_suffix wins the override.
    followup_override: dict[str, str] = {}
    # Tracks the most-recently-completed follow-up's override per parent (last
    # writer wins). When the `.epic` follow-up was the newest to complete we
    # keep EPIC CREATED; a later non-epic completion overwrites with None so
    # the default PLAN DONE applies.
    completed_followup_override: dict[str, str | None] = {}
    ordered_agents = sorted(
        agents, key=lambda a: a.run_start_time or a.start_time or datetime.min
    )
    for agent in ordered_agents:
        if (
            agent.parent_timestamp
            and not agent.parent_workflow  # Follow-up agent, not workflow step
            and not is_feedback_suffix(agent.role_suffix)  # Skip feedback rounds
        ):
            parents_with_followup.add(agent.parent_timestamp)
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent:
                # Pick override status based on the follow-up child's role_suffix.
                # Active children: `.epic`/`.commit` map to EPIC APPROVED /
                # PLAN COMMITTED; anything else is PLAN APPROVED. Completed
                # children: a DONE `.epic` yields EPIC CREATED once every
                # follow-up has finished. Both paths resolve multiple children
                # via last-writer-wins on the start-time-ordered iteration
                # (newest child wins).
                if agent.status not in completed_statuses:
                    if agent.role_suffix == ".epic":
                        followup_override[agent.parent_timestamp] = "EPIC APPROVED"
                    elif agent.role_suffix == ".legend":
                        followup_override[agent.parent_timestamp] = "LEGEND APPROVED"
                    elif agent.role_suffix == ".commit":
                        followup_override[agent.parent_timestamp] = "PLAN COMMITTED"
                    else:
                        followup_override[agent.parent_timestamp] = "PLAN APPROVED"
                else:
                    if agent.status == "DONE" and agent.role_suffix == ".epic":
                        completed_followup_override[agent.parent_timestamp] = (
                            "EPIC CREATED"
                        )
                    else:
                        completed_followup_override[agent.parent_timestamp] = None

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
                if agent.role_suffix == ".epic":
                    parent.epic_time = (
                        agent.epic_time or agent.run_start_time or agent.start_time
                    )

                # Propagate diff_path from follow-up child to parent so the
                # file panel can display the code diff (more relevant than
                # the planner's own diff).
                if agent.diff_path:
                    parent.diff_path = agent.diff_path

    # Apply the chosen follow-up override to each parent that is still DONE.
    for parent_ts, status in followup_override.items():
        parent = parent_by_suffix.get(parent_ts)
        if parent and parent.status == "DONE":
            parent.status = status

    # Override DONE -> PLAN DONE / EPIC CREATED for plan workflows where all
    # follow-ups completed. If a parent still has status "DONE" at this point
    # and has follow-ups in parents_with_followup, all follow-ups must be
    # complete (active ones would have triggered the PLAN APPROVED override
    # above). When the newest completed follow-up is `.epic` DONE, surface
    # EPIC CREATED instead of the generic PLAN DONE.
    for agent in agents:
        if (
            is_root_plan_workflow(agent)
            and agent.status == "DONE"
            and agent.raw_suffix in parents_with_followup
        ):
            completed_override = completed_followup_override.get(agent.raw_suffix)
            if completed_override == "EPIC CREATED":
                agent.status = "EPIC CREATED"
            else:
                agent.status = "PLAN DONE"

    # Override DONE -> PLANNING for plan-only workflows (no follow-up spawned yet).
    # A workflow with role_suffix ".plan" that's still DONE means the plan was
    # submitted but no coder follow-up exists yet (awaiting user approval).
    # If a follow-up exists (even if completed), the plan was already approved.
    # If an active feedback round exists, the agent is actively processing
    # feedback, so use RUNNING instead of PLANNING.
    for agent in agents:
        if (
            is_root_plan_workflow(agent)
            and agent.status == "DONE"
            and agent.raw_suffix not in parents_with_followup
        ):
            if agent.raw_suffix in parents_with_active_feedback:
                agent.status = "RUNNING"
            else:
                agent.status = "PLANNING"

    # Override DONE -> QUESTION for agents whose last question was never answered.
    # The .q follow-up is created only AFTER a response is received, so its
    # absence with a recorded questions_submitted_at means polling was killed
    # before the user answered.
    for agent in agents:
        if (
            agent.status == "DONE"
            and agent.questions_times
            and agent.raw_suffix
            and agent.raw_suffix not in parents_with_followup
        ):
            agent.status = "QUESTION"

    # Attach all follow-up agents to their parent's followup_agents list.
    for agent in agents:
        if agent.parent_timestamp and not agent.parent_workflow:
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent:
                parent.followup_agents.append(agent)

    # Sort follow-up agents chronologically (oldest first).
    for agent in agents:
        if agent.followup_agents:
            agent.followup_agents.sort(key=lambda a: a.start_time or datetime.min)

    # Spawn-on-retry: build the retry-chain linkage. Each retry child has a
    # backward pointer (retry_of_timestamp) to its immediate parent; we
    # reverse-index that into the parent's retry_chain_siblings list so the
    # TUI can render the chain from either direction.
    by_suffix: dict[str, Agent] = {}
    for agent in agents:
        if agent.raw_suffix:
            by_suffix[agent.raw_suffix] = agent
    for agent in agents:
        if agent.retry_of_timestamp:
            parent = by_suffix.get(agent.retry_of_timestamp)
            if parent is not None:
                parent.retry_chain_siblings.append(agent)
    for agent in agents:
        if agent.retry_chain_siblings:
            agent.retry_chain_siblings.sort(
                key=lambda a: a.retry_attempt or 0,
            )
