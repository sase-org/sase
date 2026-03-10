"""Functions for loading and aggregating agents from all sources."""

from datetime import datetime

from ...changespec import find_all_changespecs
from ...hooks.processes import is_process_running
from ._loaders import (
    get_all_project_files,
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
from ._timestamps import (
    extract_timestamp_from_workflow,
    extract_timestamp_str_from_suffix,
)
from .agent import Agent, AgentType
from .fold_state import FoldLevel, FoldStateManager
from .workflow import WorkflowEntry


def _get_status_priority(status: str) -> int:
    """Return sort priority for agent status (lower = appears first).

    Completed/failed steps appear before running/waiting steps.
    """
    if status in ("DONE", "FAILED"):
        return 0
    # RUNNING, WAITING INPUT, and any other status
    return 1


def filter_agents_by_fold_state(
    agents: list[Agent],
    fold_manager: FoldStateManager,
) -> tuple[list[Agent], dict[str, tuple[int, int]]]:
    """Filter agent list based on fold state of workflow parents.

    Scans the flat agent list (children interleaved after parents) and
    filters children based on the fold level of their parent workflow.

    Args:
        agents: Full agent list with children after parents.
        fold_manager: Manager tracking fold state per workflow.

    Returns:
        Tuple of (filtered_agents, fold_counts) where fold_counts maps
        workflow raw_suffix -> (non_hidden_child_count, hidden_child_count).
    """
    # First pass: collect children per parent and compute counts
    fold_counts: dict[str, tuple[int, int]] = {}
    children_by_parent: dict[str, list[Agent]] = {}

    for agent in agents:
        if agent.is_workflow_child and agent.parent_timestamp:
            parent_key = agent.parent_timestamp
            if parent_key not in children_by_parent:
                children_by_parent[parent_key] = []
            children_by_parent[parent_key].append(agent)

    # Compute counts for each parent
    for parent_key, children in children_by_parent.items():
        non_hidden = sum(1 for c in children if not c.is_hidden_step)
        hidden = sum(1 for c in children if c.is_hidden_step)
        fold_counts[parent_key] = (non_hidden, hidden)

    # Identify parents whose children are ALL hidden (no visible work occurred)
    hidden_only_parents: set[str] = set()
    for parent_key, (non_hidden, hidden) in fold_counts.items():
        if non_hidden == 0 and hidden > 0:
            hidden_only_parents.add(parent_key)

    # Second pass: build filtered list
    result: list[Agent] = []
    for agent in agents:
        if agent.is_workflow_child and agent.parent_timestamp:
            parent_key = agent.parent_timestamp
            if parent_key in hidden_only_parents:
                continue
            level = fold_manager.get(parent_key)
            if level == FoldLevel.COLLAPSED:
                continue
            if level == FoldLevel.EXPANDED and agent.is_hidden_step:
                continue
            # FULLY_EXPANDED: include all children
            result.append(agent)
        else:
            # Skip parents whose only children are hidden
            if agent.raw_suffix in hidden_only_parents:
                continue
            result.append(agent)

    return result, fold_counts


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


def load_all_agents() -> list[Agent]:
    """Load all running agents from all sources.

    Sources:
    1. RUNNING field in project files (workspace claims)
    2. HOOKS field with suffix_type="running_agent" (fix-hook, summarize-hook)
    3. MENTORS field with suffix_type="running_agent"
    4. COMMENTS field with suffix_type="running_agent" (CRS)
    5. done.json marker files (DONE agents)

    Returns:
        List of Agent objects sorted by start time (most recent first),
        with agents that have no start time at the end.
    """
    agents: list[Agent] = []

    # Get all project files
    project_files = get_all_project_files()

    # Load all ChangeSpecs early to build bug lookup
    all_changespecs = find_all_changespecs()

    # Build bug URL lookup by CL name
    bug_by_cl_name: dict[str, str | None] = {}
    for cs in all_changespecs:
        if cs.bug:
            bug_id = cs.bug.removeprefix("http://b/")
            bug_by_cl_name[cs.name] = f"http://b/{bug_id}"

    # Build CL number lookup by CL name
    cl_by_cl_name: dict[str, str | None] = {}
    for cs in all_changespecs:
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
    workflow_agent_steps, step_meta_by_parent = load_workflow_agent_steps()

    # 1c. Load workflow entries as agents (with pre-collected meta fields)
    agents.extend(load_workflow_agents(step_meta_by_parent=step_meta_by_parent))

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

    # Filter out agents with dead PIDs (but keep completed agents)
    verified_agents: list[Agent] = []
    # Statuses that indicate completed work (don't filter these by PID)
    completed_statuses = (
        "DONE",
        "FAILED",
    )
    for agent in agents:
        # Completed agents represent finished work - always include them
        if agent.status in completed_statuses:
            verified_agents.append(agent)
        elif agent.pid is not None:
            if is_process_running(agent.pid):
                verified_agents.append(agent)
            # Skip agents with dead PIDs
        else:
            # Agents without PIDs (legacy entries) - still include them
            verified_agents.append(agent)

    agents = verified_agents

    # Deduplicate axe-spawned agents by timestamp
    # Axe agents appear in both RUNNING field (as RUNNING type with axe(...) workflow)
    # and ChangeSpec fields (also RUNNING type, with _from_changespec=True).
    # Prefer the RUNNING field entry and merge type-specific metadata from ChangeSpec.

    # Build index of RUNNING agents with axe(...) workflows by (cl_name, timestamp)
    running_axe_agents_by_key: dict[tuple[str, str], Agent] = {}
    _axe_workflow_prefixes = ["axe(mentor)", "axe(fix-hook)", "axe(crs)", "mentor("]
    for agent in agents:
        if agent.agent_type == AgentType.RUNNING:
            workflow = agent.workflow or ""
            if any(workflow.startswith(p) for p in _axe_workflow_prefixes):
                ts = extract_timestamp_from_workflow(workflow)
                # Fallback: mentor( workflows don't embed timestamps in
                # their name — use raw_suffix (14-digit) converted to 13-char
                if not ts and agent.raw_suffix:
                    ts_14 = agent.raw_suffix
                    if len(ts_14) == 14 and ts_14.isdigit():
                        ts = ts_14[2:8] + "_" + ts_14[8:]
                if ts:
                    key = (agent.cl_name, ts)
                    running_axe_agents_by_key[key] = agent

    # Also index done.json RUNNING agents by (cl_name, timestamp)
    # These have workflow like "fix-hook", "crs", "mentor-*" and raw_suffix as
    # 14-digit timestamp that needs converting to 13-char format for matching
    _done_axe_workflows = {"fix-hook", "crs", "summarize-hook"}
    _done_axe_prefixes = ["mentor-"]
    for agent in agents:
        if (
            agent.agent_type == AgentType.RUNNING
            and agent.status in ("DONE", "FAILED")
            and agent.workflow
        ):
            is_done_axe = agent.workflow in _done_axe_workflows or any(
                agent.workflow.startswith(p) for p in _done_axe_prefixes
            )
            if is_done_axe and agent.raw_suffix:
                ts_14 = agent.raw_suffix
                if len(ts_14) == 14 and ts_14.isdigit():
                    # Convert YYYYmmddHHMMSS -> YYmmdd_HHMMSS for matching
                    ts_13 = ts_14[2:8] + "_" + ts_14[8:]
                    key = (agent.cl_name, ts_13)
                    running_axe_agents_by_key[key] = agent

    # Match ChangeSpec entries with RUNNING field entries — keep RUNNING field, drop ChangeSpec
    final_agents: list[Agent] = []
    for agent in agents:
        if agent._from_changespec:
            ts = extract_timestamp_str_from_suffix(agent.raw_suffix)
            if ts:
                key = (agent.cl_name, ts)
                if key in running_axe_agents_by_key:
                    # Merge type-specific fields onto the RUNNING entry
                    matched = running_axe_agents_by_key[key]
                    if agent.hook_command:
                        matched.hook_command = agent.hook_command
                    if agent.mentor_profile:
                        matched.mentor_profile = agent.mentor_profile
                    if agent.mentor_name:
                        matched.mentor_name = agent.mentor_name
                    if agent.reviewer:
                        matched.reviewer = agent.reviewer
                    if agent.commit_entry_id:
                        matched.commit_entry_id = agent.commit_entry_id
                    continue  # Drop the ChangeSpec entry
        final_agents.append(agent)

    agents = final_agents

    # Remove embedded VCS workspace claims from axe-spawned agents.
    # When an axe agent embeds #hg or #gh, the VCS workflow claims its own
    # workspace (appearing as a separate RUNNING entry like "hg-<cl_name>").
    # These share the same PID as the parent axe agent via os.getppid().
    # We remove these entirely (not just hide) so they never appear as
    # duplicate PID entries, even when hidden agents are toggled visible.
    _vcs_workflow_prefixes = ("hg-", "gh-", "git-")
    # Plain workflow names from workflow_state.json / done.json for axe-spawned agents
    _plain_axe_workflows = {"fix-hook", "crs", "mentor", "summarize-hook"}
    _plain_axe_prefixes = ("mentor-",)
    axe_pids: set[int] = set()
    for agent in agents:
        if agent.pid is not None and agent.workflow:
            is_axe = (
                any(agent.workflow.startswith(p) for p in _axe_workflow_prefixes)
                or agent.workflow in _plain_axe_workflows
                or agent.workflow.startswith(_plain_axe_prefixes)
            )
            if is_axe:
                axe_pids.add(agent.pid)

    if axe_pids:
        agents = [
            agent
            for agent in agents
            if not (
                agent.agent_type == AgentType.RUNNING
                and agent.pid is not None
                and agent.pid in axe_pids
                and agent.workflow
                and agent.workflow.startswith(_vcs_workflow_prefixes)
            )
        ]

    # Deduplicate workflow entries: match by raw_suffix (timestamp)
    # Prefer workflow_state.json entries (accurate status), but copy
    # workspace_num and cl_name from RUNNING field entries
    seen_suffixes: dict[str, Agent] = {}
    for agent in agents:
        if agent.agent_type == AgentType.WORKFLOW and agent.raw_suffix:
            if agent.raw_suffix in seen_suffixes:
                existing = seen_suffixes[agent.raw_suffix]
                # Copy workspace_num from RUNNING field entry
                if existing.workspace_num is None and agent.workspace_num is not None:
                    existing.workspace_num = agent.workspace_num
                # Copy cl_name if existing has "unknown"
                if existing.cl_name == "unknown" and agent.cl_name != "unknown":
                    existing.cl_name = agent.cl_name
                # Prefer non-RUNNING status from workflow_state.json (accurate status)
                if existing.status == "RUNNING" and agent.status != "RUNNING":
                    existing.status = agent.status
                # Copy PID from workflow_state.json if existing has none
                if existing.pid is None and agent.pid is not None:
                    existing.pid = agent.pid
                # Copy error_traceback if existing has none
                if (
                    existing.error_traceback is None
                    and agent.error_traceback is not None
                ):
                    existing.error_traceback = agent.error_traceback
                # Copy agent_name if existing has none
                if existing.agent_name is None and agent.agent_name is not None:
                    existing.agent_name = agent.agent_name
            else:
                seen_suffixes[agent.raw_suffix] = agent

    # Filter out duplicates
    agents = [
        a
        for a in agents
        if a.agent_type != AgentType.WORKFLOW
        or a.raw_suffix not in seen_suffixes
        or seen_suffixes.get(a.raw_suffix) is a
    ]

    # Deduplicate RUNNING↔WORKFLOW: ace-run RUNNING agents vs WORKFLOW agents
    # from the same artifacts directory (matching raw_suffix / timestamp).
    # RUNNING field uses "ace(run)" workflow; done.json uses "ace-run" (dir name).
    # Prefer WORKFLOW (has step info / appears_as_agent), merge metadata from RUNNING.
    workflow_by_suffix: dict[str, Agent] = {}
    for agent in agents:
        if agent.agent_type == AgentType.WORKFLOW and agent.raw_suffix:
            workflow_by_suffix[agent.raw_suffix] = agent

    deduped_agents: list[Agent] = []
    for agent in agents:
        if (
            agent.agent_type == AgentType.RUNNING
            and agent.workflow is not None
            and (agent.workflow.startswith("ace(run)") or agent.workflow == "ace-run")
            and agent.raw_suffix
            and agent.raw_suffix in workflow_by_suffix
        ):
            # Match found — merge metadata into the WORKFLOW agent
            matched = workflow_by_suffix[agent.raw_suffix]
            if matched.cl_name == "unknown" and agent.cl_name != "unknown":
                matched.cl_name = agent.cl_name
            if matched.workspace_num is None and agent.workspace_num is not None:
                matched.workspace_num = agent.workspace_num
            if matched.response_path is None and agent.response_path is not None:
                matched.response_path = agent.response_path
            if matched.diff_path is None and agent.diff_path is not None:
                matched.diff_path = agent.diff_path
            if matched.bug is None and agent.bug is not None:
                matched.bug = agent.bug
            if matched.cl_num is None and agent.cl_num is not None:
                matched.cl_num = agent.cl_num
            if matched.model is None and agent.model is not None:
                matched.model = agent.model
            if matched.vcs_provider is None and agent.vcs_provider is not None:
                matched.vcs_provider = agent.vcs_provider
            if matched.error_message is None and agent.error_message is not None:
                matched.error_message = agent.error_message
            if matched.error_traceback is None and agent.error_traceback is not None:
                matched.error_traceback = agent.error_traceback
            if not matched.extra_files and agent.extra_files:
                matched.extra_files = agent.extra_files
            if matched.step_output is None and agent.step_output is not None:
                matched.step_output = agent.step_output
            if matched.agent_name is None and agent.agent_name is not None:
                matched.agent_name = agent.agent_name
            # Merge status: prefer non-RUNNING status (e.g. PLANNING, PLAN APPROVED)
            if matched.status == "RUNNING" and agent.status != "RUNNING":
                matched.status = agent.status
            continue  # Drop the RUNNING entry
        deduped_agents.append(agent)

    agents = deduped_agents

    # Final safety net: enforce no duplicate PIDs among all agents.
    # When multiple agents share a PID, keep the one with the most specific
    # workflow type (WORKFLOW > RUNNING) and remove the rest. This catches any
    # VCS workspace duplicates that slipped through earlier dedup passes.
    # Operates on ALL agents (including hidden) to prevent duplicate PIDs
    # from appearing when hidden agents are toggled visible.
    seen_pids: dict[int, Agent] = {}
    pid_remove_ids: set[int] = set()
    for agent in agents:
        if agent.pid is None:
            continue
        if agent.pid in seen_pids:
            existing = seen_pids[agent.pid]
            # Prefer WORKFLOW over RUNNING, and non-VCS over VCS workflows
            existing_is_vcs = existing.workflow and existing.workflow.startswith(
                _vcs_workflow_prefixes
            )
            agent_is_vcs = agent.workflow and agent.workflow.startswith(
                _vcs_workflow_prefixes
            )
            if agent_is_vcs and not existing_is_vcs:
                # New agent is VCS, existing is not — remove new
                pid_remove_ids.add(id(agent))
            elif existing_is_vcs and not agent_is_vcs:
                # Existing is VCS, new is not — remove existing, keep new
                pid_remove_ids.add(id(existing))
                seen_pids[agent.pid] = agent
            elif (
                agent.agent_type == AgentType.RUNNING
                and existing.agent_type == AgentType.WORKFLOW
            ):
                # Both non-VCS: prefer WORKFLOW over RUNNING
                pid_remove_ids.add(id(agent))
            elif (
                existing.agent_type == AgentType.RUNNING
                and agent.agent_type == AgentType.WORKFLOW
            ):
                pid_remove_ids.add(id(existing))
                seen_pids[agent.pid] = agent
            else:
                # Same type — remove the newer one (current agent)
                pid_remove_ids.add(id(agent))
        else:
            seen_pids[agent.pid] = agent

    if pid_remove_ids:
        agents = [a for a in agents if id(a) not in pid_remove_ids]

    # Sort by start time (most recent first), with None times at end
    def sort_key(a: Agent) -> tuple[bool, datetime]:
        if a.start_time is None:
            # Put None times at the end, sorted by a far-future date
            return (True, datetime.max)
        # Put non-None times first, sorted newest to oldest (reverse)
        return (False, a.start_time)

    agents.sort(key=sort_key, reverse=True)

    # Since we sorted reverse=True, we need to flip the None/non-None order
    # Actually, let's redo this more simply
    agents_with_time = [a for a in agents if a.start_time is not None]
    agents_without_time = [a for a in agents if a.start_time is None]

    # Sort with-time by start_time descending (most recent first)
    agents_with_time.sort(key=lambda a: a.start_time, reverse=True)  # type: ignore

    sorted_agents = agents_with_time + agents_without_time

    # Insert workflow agent steps immediately after their parent workflows
    if workflow_agent_steps:
        result: list[Agent] = []
        for agent in sorted_agents:
            result.append(agent)
            # Check if any agent steps belong to this agent (matching workflow+timestamp)
            if agent.agent_type == AgentType.WORKFLOW or (
                agent.workflow
                and (
                    agent.workflow.startswith("workflow-")
                    or agent.workflow.startswith("ace(run)")
                )
            ):
                # Find matching agent steps by timestamp
                matching_steps = [
                    step
                    for step in workflow_agent_steps
                    if step.parent_timestamp == agent.raw_suffix
                ]
                # Sort by workflow position: main steps first, then substeps
                matching_steps.sort(
                    key=lambda s: (
                        # Primary: completed/failed steps (0) before running/waiting steps (1)
                        _get_status_priority(s.status),
                        # Secondary: position in workflow (parent_step_index for
                        # substeps, step_index for main steps)
                        (
                            s.parent_step_index
                            if s.parent_step_index is not None
                            else (s.step_index or 0)
                        ),
                        # Tertiary: substeps (1) come after main steps (0)
                        1 if s.parent_step_index is not None else 0,
                        # Quaternary: order within substeps
                        s.step_index or 0,
                    )
                )
                result.extend(matching_steps)
        return result

    return sorted_agents
