"""Final agent ordering helpers for the TUI agent list."""

from .agent import Agent, AgentType


def get_status_priority(status: str) -> int:
    """Return sort priority for agent status (lower = appears first).

    Completed/failed steps appear before running/waiting steps.
    """
    if status in ("DONE", "FAILED"):
        return 0
    # RUNNING, WAITING INPUT, and any other status
    return 1


def sort_and_reorder(
    agents: list[Agent],
    workflow_agent_steps: list[Agent],
) -> list[Agent]:
    """Sort agents by time and insert workflow steps after their parents."""
    _clear_runtime_children(agents, workflow_agent_steps)

    # Sort by start time (most recent first), with None times at end
    agents_with_time = [a for a in agents if a.start_time is not None]
    agents_without_time = [a for a in agents if a.start_time is None]

    agents_with_time.sort(key=lambda a: a.start_time, reverse=True)  # type: ignore

    sorted_agents = agents_with_time + agents_without_time

    # Separate follow-up agents (parent_timestamp set, no parent_workflow)
    # from regular agents so they can be grouped with their parent's main
    # agent step (plan -> feedback rounds -> coder) instead of scattering
    # by start time.
    followups_by_parent: dict[str, list[Agent]] = {}
    non_followup: list[Agent] = []
    for agent in sorted_agents:
        if agent.parent_timestamp and not agent.parent_workflow:
            followups_by_parent.setdefault(agent.parent_timestamp, []).append(agent)
        else:
            non_followup.append(agent)

    # Sort follow-ups chronologically (oldest first) so the display reads
    # plan -> feedback -> coder in natural order.
    for followups in followups_by_parent.values():
        followups.sort(key=lambda a: a.start_time or "")

    sorted_agents = non_followup

    # Insert workflow agent steps and follow-ups after their parent workflows.
    # Follow-ups are interleaved right after the main agent step (before
    # embedded steps) so plan-related agents appear as a cohesive group.
    if workflow_agent_steps or followups_by_parent:
        # Pre-index steps by parent_timestamp for O(1) lookup
        steps_by_parent: dict[str, list[Agent]] = {}
        for step in workflow_agent_steps:
            if step.parent_timestamp:
                if step.parent_timestamp not in steps_by_parent:
                    steps_by_parent[step.parent_timestamp] = []
                steps_by_parent[step.parent_timestamp].append(step)

        # Pre-sort each group once
        for steps in steps_by_parent.values():
            steps.sort(
                key=lambda s: (
                    get_status_priority(s.status),
                    (
                        s.parent_step_index
                        if s.parent_step_index is not None
                        else (s.step_index or 0)
                    ),
                    1 if s.parent_step_index is not None else 0,
                    s.step_index or 0,
                )
            )

        # Set step numbering on follow-up agents (e.g., .code, .q) from their
        # parent workflow's main prompt step so they render as "1/1.code".
        prompt_step_by_parent: dict[str, tuple[int, int]] = {}
        for parent_ts, steps in steps_by_parent.items():
            for step in steps:
                if (
                    step.step_type == "agent"
                    and not step.is_hidden_step
                    and step.parent_step_index is None
                ):
                    prompt_step_by_parent[parent_ts] = (
                        step.step_index or 0,
                        step.total_steps or 1,
                    )
                    break
        for parent_ts, followups in followups_by_parent.items():
            info = prompt_step_by_parent.get(parent_ts)
            if info:
                for agent in followups:
                    if agent.role_suffix and agent.step_index is None:
                        agent.step_index = info[0]
                        agent.total_steps = info[1]

        _attach_runtime_children(
            agents,
            workflow_agent_steps,
            steps_by_parent,
            followups_by_parent,
        )

        result: list[Agent] = []
        for agent in sorted_agents:
            result.append(agent)
            suffix = agent.raw_suffix
            if not suffix:
                continue
            if agent.agent_type == AgentType.WORKFLOW or (
                agent.workflow
                and (
                    agent.workflow.startswith("workflow-")
                    or agent.workflow.startswith("ace(run)")
                )
            ):
                steps = steps_by_parent.get(suffix, [])
                followups = followups_by_parent.pop(suffix, [])
                # Separate main agent steps from embedded/other steps so
                # follow-ups (feedback, coder) appear right after the plan.
                main_agent_steps = [
                    s
                    for s in steps
                    if s.step_type == "agent" and s.parent_step_index is None
                ]
                other_steps = [
                    s
                    for s in steps
                    if not (s.step_type == "agent" and s.parent_step_index is None)
                ]
                result.extend(main_agent_steps)
                result.extend(followups)
                result.extend(other_steps)
            elif suffix in followups_by_parent:
                # Non-workflow parent with follow-ups
                result.extend(followups_by_parent.pop(suffix))
        # Append any orphaned follow-ups (parent not found)
        for remaining in followups_by_parent.values():
            result.extend(remaining)
        return result

    return sorted_agents


def _clear_runtime_children(
    agents: list[Agent], workflow_agent_steps: list[Agent]
) -> None:
    """Reset load-time runtime links before rebuilding relationships."""
    seen: set[int] = set()
    for agent in [*agents, *workflow_agent_steps]:
        agent_id = id(agent)
        if agent_id in seen:
            continue
        seen.add(agent_id)
        agent.runtime_children.clear()


def _attach_runtime_children(
    agents: list[Agent],
    workflow_agent_steps: list[Agent],
    steps_by_parent: dict[str, list[Agent]],
    followups_by_parent: dict[str, list[Agent]],
) -> None:
    """Attach direct visible runtime children to their parent rows."""
    parent_by_suffix: dict[str, Agent] = {}
    for agent in [*agents, *workflow_agent_steps]:
        if agent.raw_suffix:
            parent_by_suffix[agent.raw_suffix] = agent

    for parent_suffix, parent in parent_by_suffix.items():
        children: list[Agent] = []
        children.extend(
            step
            for step in steps_by_parent.get(parent_suffix, [])
            if step.step_type == "agent" and step.parent_step_index is None
        )
        children.extend(followups_by_parent.get(parent_suffix, []))
        if children:
            parent.runtime_children.extend(children)
