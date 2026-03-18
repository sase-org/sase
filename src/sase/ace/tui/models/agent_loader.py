"""Functions for loading and aggregating agents from all sources."""

from ...changespec import find_all_changespecs
from ...hooks.processes import is_process_running
from ._dedup import (
    dedup_axe_spawned_agents,
    dedup_by_pid,
    dedup_running_vs_workflow,
    dedup_workflow_entries,
    remove_vcs_workspace_claims,
)
from ._loaders import (
    get_all_project_files,
    get_workflow_timestamp_dirs,
    load_agents_from_comments,
    load_agents_from_hooks,
    load_agents_from_mentors,
    load_agents_from_running_field,
    load_done_agents,
    load_running_home_agents,
    load_workflow_agent_steps,
    load_workflow_agents,
    load_workflow_states,
)
from .agent import Agent, AgentType
from .workflow import WorkflowEntry


def _get_status_priority(status: str) -> int:
    """Return sort priority for agent status (lower = appears first).

    Completed/failed steps appear before running/waiting steps.
    """
    if status in ("DONE", "FAILED"):
        return 0
    # RUNNING, WAITING INPUT, and any other status
    return 1


def load_all_workflows() -> list[WorkflowEntry]:
    """Load all workflow entries from workflow_state.json files.

    Returns:
        List of WorkflowEntry objects sorted by start time (most recent first).
    """
    workflows = load_workflow_states()

    # Sort by start time (most recent first)
    workflows_with_time = [w for w in workflows if w.start_time is not None]
    workflows_without_time = [w for w in workflows if w.start_time is None]

    workflows_with_time.sort(key=lambda w: w.start_time, reverse=True)  # type: ignore

    return workflows_with_time + workflows_without_time


def _load_agents_from_all_sources() -> tuple[list[Agent], list[Agent]]:
    """Load agents from all sources and return (agents, workflow_agent_steps).

    Sources:
    1. RUNNING field in project files (workspace claims)
    2. done.json marker files (DONE agents)
    3. running.json markers (home mode agents)
    4. Workflow agent steps and workflow entries
    5. HOOKS, MENTORS, COMMENTS fields from ChangeSpecs
    """
    agents: list[Agent] = []

    # Get all project files
    project_files = get_all_project_files()

    # Load all ChangeSpecs early to build bug lookup
    all_changespecs = find_all_changespecs()

    # Build bug URL and CL number lookups by CL name (single pass)
    bug_by_cl_name: dict[str, str | None] = {}
    cl_by_cl_name: dict[str, str | None] = {}
    for cs in all_changespecs:
        if cs.bug:
            bug_id = cs.bug.removeprefix("http://b/")
            bug_by_cl_name[cs.name] = f"http://b/{bug_id}"
        if cs.cl:
            cl_by_cl_name[cs.name] = cs.cl

    # 1. Load from RUNNING field
    agents.extend(
        load_agents_from_running_field(project_files, bug_by_cl_name, cl_by_cl_name)
    )

    # 1a. Load completed (DONE) agents
    agents.extend(load_done_agents(bug_by_cl_name, cl_by_cl_name))

    # 1b. Load running home mode agents (from running.json markers)
    agents.extend(load_running_home_agents())

    # 1d. Load workflow agent steps first — also collects meta_* fields
    # per parent timestamp so load_workflow_agents() can skip redundant
    # prompt_step_*.json reads.
    # Cache the directory traversal so both loaders share a single scan.
    wf_timestamp_dirs = get_workflow_timestamp_dirs()
    workflow_agent_steps, step_meta_by_parent = load_workflow_agent_steps(
        timestamp_dirs=wf_timestamp_dirs,
    )

    # 1c. Load workflow entries as agents (with pre-collected meta fields)
    agents.extend(
        load_workflow_agents(
            step_meta_by_parent=step_meta_by_parent,
            timestamp_dirs=wf_timestamp_dirs,
        )
    )

    # 2. Load from each ChangeSpec's fields
    for cs in all_changespecs:
        stripped_bug_id = cs.bug.removeprefix("http://b/") if cs.bug else None
        bug = f"http://b/{stripped_bug_id}" if stripped_bug_id else None
        cl_num = cs.cl

        # HOOKS - fix-hook and summarize agents
        agents.extend(load_agents_from_hooks(cs, bug, cl_num))

        # MENTORS - mentor agents
        agents.extend(load_agents_from_mentors(cs, bug, cl_num))

        # COMMENTS - CRS agents
        agents.extend(load_agents_from_comments(cs, bug, cl_num))

    return agents, workflow_agent_steps


def _filter_dead_pids(agents: list[Agent]) -> list[Agent]:
    """Filter out agents with dead PIDs (but keep completed agents)."""
    verified_agents: list[Agent] = []
    completed_statuses = ("DONE", "FAILED")
    for agent in agents:
        if agent.status in completed_statuses:
            verified_agents.append(agent)
        elif agent.pid is not None:
            if is_process_running(agent.pid):
                verified_agents.append(agent)
            # Skip agents with dead PIDs
        else:
            # Agents without PIDs (legacy entries) - still include them
            verified_agents.append(agent)
    return verified_agents


def _apply_status_overrides(agents: list[Agent]) -> None:
    """Override statuses based on workflow relationships (mutates in place).

    - DONE → PLAN APPROVED: parent has active follow-up children
    - DONE → PLAN DONE: plan workflow where all follow-ups completed
    - DONE → PLANNING: plan workflow with no follow-up spawned yet
    """
    completed_statuses = {"DONE", "FAILED"}

    parent_by_suffix: dict[str, Agent] = {}
    for agent in agents:
        if agent.raw_suffix and not agent.is_workflow_child:
            parent_by_suffix[agent.raw_suffix] = agent

    parents_with_followup: set[str] = set()
    for agent in agents:
        if (
            agent.parent_timestamp
            and not agent.parent_workflow  # Follow-up agent, not workflow step
        ):
            parents_with_followup.add(agent.parent_timestamp)
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent:
                # Override DONE → PLAN APPROVED while follow-up is active
                if agent.status not in completed_statuses:
                    if parent.status == "DONE":
                        parent.status = "PLAN APPROVED"

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

                # Propagate diff_path from follow-up child to parent so the
                # file panel can display the code diff (more relevant than
                # the planner's own diff).
                if agent.diff_path:
                    parent.diff_path = agent.diff_path

    # Override DONE → PLAN DONE for plan workflows where all follow-ups completed.
    # If a parent still has status "DONE" at this point and has follow-ups in
    # parents_with_followup, all follow-ups must be complete (active ones would
    # have triggered the PLAN APPROVED override above).
    for agent in agents:
        if (
            agent.agent_type == AgentType.WORKFLOW
            and agent.role_suffix
            and agent.role_suffix.startswith(".plan")
            and agent.status == "DONE"
            and agent.raw_suffix in parents_with_followup
        ):
            agent.status = "PLAN DONE"

    # Override DONE → PLANNING for plan-only workflows (no follow-up spawned yet).
    # A workflow with role_suffix ".plan" (or ".plan.N" for feedback rounds)
    # that's still DONE means the plan was submitted but no coder follow-up
    # exists yet (awaiting user approval).
    # If a follow-up exists (even if completed), the plan was already approved.
    for agent in agents:
        if (
            agent.agent_type == AgentType.WORKFLOW
            and agent.role_suffix
            and agent.role_suffix.startswith(".plan")
            and agent.status == "DONE"
            and agent.raw_suffix not in parents_with_followup
        ):
            agent.status = "PLANNING"


def _sort_and_reorder(
    agents: list[Agent],
    workflow_agent_steps: list[Agent],
) -> list[Agent]:
    """Sort agents by time and insert workflow steps after their parents."""
    # Sort by start time (most recent first), with None times at end
    agents_with_time = [a for a in agents if a.start_time is not None]
    agents_without_time = [a for a in agents if a.start_time is None]

    agents_with_time.sort(key=lambda a: a.start_time, reverse=True)  # type: ignore

    sorted_agents = agents_with_time + agents_without_time

    # Reorder follow-up agents (parent_timestamp set, no parent_workflow)
    # to appear immediately after their parent workflow.
    # Without this, follow-ups sort before their parent by start_time
    # (since follow-ups start later and we sort most-recent-first),
    # causing them to render as orphaned children above their parent.
    followups_by_parent: dict[str, list[Agent]] = {}
    non_followup: list[Agent] = []
    for agent in sorted_agents:
        if agent.parent_timestamp and not agent.parent_workflow:
            followups_by_parent.setdefault(agent.parent_timestamp, []).append(agent)
        else:
            non_followup.append(agent)

    if followups_by_parent:
        reordered: list[Agent] = []
        for agent in non_followup:
            reordered.append(agent)
            if agent.raw_suffix and agent.raw_suffix in followups_by_parent:
                reordered.extend(followups_by_parent.pop(agent.raw_suffix))
        # Append any orphaned follow-ups (parent not found)
        for remaining in followups_by_parent.values():
            reordered.extend(remaining)
        sorted_agents = reordered

    # Insert workflow agent steps immediately after their parent workflows
    if workflow_agent_steps:
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
                    _get_status_priority(s.status),
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
        for agent in sorted_agents:
            if (
                agent.parent_timestamp
                and not agent.parent_workflow
                and agent.role_suffix
                and agent.step_index is None
            ):
                info = prompt_step_by_parent.get(agent.parent_timestamp)
                if info:
                    agent.step_index = info[0]
                    agent.total_steps = info[1]

        result: list[Agent] = []
        for agent in sorted_agents:
            result.append(agent)
            # Don't insert child steps for follow-up agents — they're
            # already nested under their parent workflow, so showing
            # their internal steps creates visual duplicates at the
            # same indent level (the flat list only supports one level
            # of nesting).
            if agent.parent_timestamp and not agent.parent_workflow:
                continue
            if agent.raw_suffix and (
                agent.agent_type == AgentType.WORKFLOW
                or (
                    agent.workflow
                    and (
                        agent.workflow.startswith("workflow-")
                        or agent.workflow.startswith("ace(run)")
                    )
                )
            ):
                matching = steps_by_parent.get(agent.raw_suffix)
                if matching:
                    result.extend(matching)
        return result

    return sorted_agents


def load_all_agents() -> list[Agent]:
    """Load all running agents from all sources.

    Sources:
    1. RUNNING field in project files (workspace claims)
    2. HOOKS field with suffix_type="running_agent" (fix_hook, summarize_hook)
    3. MENTORS field with suffix_type="running_agent"
    4. COMMENTS field with suffix_type="running_agent" (CRS)
    5. done.json marker files (DONE agents)

    Returns:
        List of Agent objects sorted by start time (most recent first),
        with agents that have no start time at the end.
    """
    agents, workflow_agent_steps = _load_agents_from_all_sources()

    # Filter out agents with dead PIDs (but keep completed agents)
    agents = _filter_dead_pids(agents)

    # Deduplication pipeline
    agents = dedup_axe_spawned_agents(agents)
    agents = remove_vcs_workspace_claims(agents)
    agents = dedup_workflow_entries(agents)
    agents = dedup_running_vs_workflow(agents)
    agents = dedup_by_pid(agents)

    # Override statuses based on workflow relationships
    _apply_status_overrides(agents)

    # Sort and insert workflow steps
    return _sort_and_reorder(agents, workflow_agent_steps)
