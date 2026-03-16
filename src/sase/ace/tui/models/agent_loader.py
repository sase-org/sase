"""Functions for loading and aggregating agents from all sources."""

from ...changespec import find_all_changespecs
from ...hooks.processes import is_process_running
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
from ._timestamps import (
    extract_timestamp_from_workflow,
    extract_timestamp_str_from_suffix,
    normalize_to_14_digit,
)
from .agent import Agent, AgentType
from .fold_state import FoldLevel, FoldStateManager
from .workflow import WorkflowEntry


def _merge_agent_fields(target: Agent, source: Agent) -> None:
    """Merge non-None fields from source agent into target agent.

    Only copies fields that are None/empty on the target but set on the source.
    This preserves metadata (workspace_num, model, etc.) from VCS workspace
    agents that are being removed as duplicates.
    """
    if target.workspace_num is None and source.workspace_num is not None:
        target.workspace_num = source.workspace_num
    if target.model is None and source.model is not None:
        target.model = source.model
    if target.llm_provider is None and source.llm_provider is not None:
        target.llm_provider = source.llm_provider
    if target.vcs_provider is None and source.vcs_provider is not None:
        target.vcs_provider = source.vcs_provider
    if target.agent_name is None and source.agent_name is not None:
        target.agent_name = source.agent_name
    if target.bug is None and source.bug is not None:
        target.bug = source.bug
    if target.cl_num is None and source.cl_num is not None:
        target.cl_num = source.cl_num
    if target.diff_path is None and source.diff_path is not None:
        target.diff_path = source.diff_path
    if not target.extra_files and source.extra_files:
        target.extra_files = source.extra_files
    if target.artifacts_dir is None and source.artifacts_dir is not None:
        target.artifacts_dir = source.artifacts_dir
    if not target.waiting_for and source.waiting_for:
        target.waiting_for = source.waiting_for
    if target.approve is False and source.approve is True:
        target.approve = source.approve
    if target.start_time is None and source.start_time is not None:
        target.start_time = source.start_time
    if target.raw_suffix is None and source.raw_suffix is not None:
        target.raw_suffix = source.raw_suffix


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
    2. HOOKS field with suffix_type="running_agent" (fix_hook, summarize_hook)
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
    _axe_workflow_prefixes = ["axe(mentor)", "axe(fix_hook)", "axe(crs)", "mentor("]
    for agent in agents:
        if agent.agent_type == AgentType.RUNNING:
            workflow = (agent.workflow or "").replace("-", "_")
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
    # These have workflow like "fix_hook", "crs", "mentor-*" and raw_suffix as
    # 14-digit timestamp that needs converting to 13-char format for matching
    _done_axe_workflows = {"fix_hook", "crs", "summarize_hook"}
    _done_axe_prefixes = ["mentor_"]
    for agent in agents:
        if (
            agent.agent_type == AgentType.RUNNING
            and agent.status in ("DONE", "FAILED")
            and agent.workflow
        ):
            norm_wf = agent.workflow.replace("-", "_")
            is_done_axe = norm_wf in _done_axe_workflows or any(
                norm_wf.startswith(p) for p in _done_axe_prefixes
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
                    if matched.start_time is None and agent.start_time is not None:
                        matched.start_time = agent.start_time
                    if matched.raw_suffix is None and agent.raw_suffix:
                        # ChangeSpec raw_suffix is full suffix
                        # (e.g. "mentor_code_quality-PID-YYmmdd_HHMMSS");
                        # extract and normalize timestamp to 14-digit format
                        cs_ts = extract_timestamp_str_from_suffix(agent.raw_suffix)
                        if cs_ts:
                            matched.raw_suffix = normalize_to_14_digit(cs_ts)
                    continue  # Drop the ChangeSpec entry
        final_agents.append(agent)

    agents = final_agents

    # Remove embedded VCS workspace claims from axe-spawned agents.
    # When an axe agent embeds #hg or #gh, the VCS workflow claims its own
    # workspace (appearing as a separate RUNNING entry like "hg-<cl_name>").
    # These share the same PID as the parent axe agent via os.getppid().
    # We remove these entirely (not just hide) so they never appear as
    # duplicate PID entries, even when hidden agents are toggled visible.
    # Before removal, merge VCS agent fields (workspace_num, model, etc.)
    # into the surviving axe agent so no metadata is lost.
    _vcs_workflow_prefixes = ("hg-", "gh-", "git-")
    # Plain workflow names from workflow_state.json / done.json for axe-spawned agents
    _plain_axe_workflows = {"fix_hook", "crs", "mentor", "summarize_hook"}
    _plain_axe_prefixes = ("mentor_",)
    axe_agents_by_pid: dict[int, Agent] = {}
    for agent in agents:
        if agent.pid is not None and agent.workflow:
            norm_wf = agent.workflow.replace("-", "_")
            is_axe = (
                any(norm_wf.startswith(p) for p in _axe_workflow_prefixes)
                or norm_wf in _plain_axe_workflows
                or norm_wf.startswith(_plain_axe_prefixes)
            )
            if is_axe:
                axe_agents_by_pid[agent.pid] = agent

    if axe_agents_by_pid:
        vcs_remove_ids: set[int] = set()
        for agent in agents:
            if (
                agent.agent_type == AgentType.RUNNING
                and agent.pid is not None
                and agent.pid in axe_agents_by_pid
                and agent.workflow
                and agent.workflow.startswith(_vcs_workflow_prefixes)
            ):
                # Merge fields from VCS workspace into surviving axe agent
                axe_agent = axe_agents_by_pid[agent.pid]
                _merge_agent_fields(axe_agent, agent)
                vcs_remove_ids.add(id(agent))
        if vcs_remove_ids:
            agents = [a for a in agents if id(a) not in vcs_remove_ids]

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
                _merge_agent_fields(existing, agent)
                pid_remove_ids.add(id(agent))
            elif existing_is_vcs and not agent_is_vcs:
                # Existing is VCS, new is not — remove existing, keep new
                _merge_agent_fields(agent, existing)
                pid_remove_ids.add(id(existing))
                seen_pids[agent.pid] = agent
            elif (
                agent.agent_type == AgentType.RUNNING
                and existing.agent_type == AgentType.WORKFLOW
            ):
                # Both non-VCS: prefer WORKFLOW over RUNNING
                _merge_agent_fields(existing, agent)
                pid_remove_ids.add(id(agent))
            elif (
                existing.agent_type == AgentType.RUNNING
                and agent.agent_type == AgentType.WORKFLOW
            ):
                _merge_agent_fields(agent, existing)
                pid_remove_ids.add(id(existing))
                seen_pids[agent.pid] = agent
            elif (
                agent.agent_type == AgentType.WORKFLOW
                and existing.agent_type == AgentType.WORKFLOW
                and agent.raw_suffix
                and existing.raw_suffix
                and agent.raw_suffix != existing.raw_suffix
            ):
                # Both WORKFLOWs with distinct artifact dirs — these are
                # follow-up phases (plan→code) from the same runner process.
                # Keep both; they represent different work, not duplicates.
                pass
            else:
                # Same type — remove the newer one (current agent)
                _merge_agent_fields(existing, agent)
                pid_remove_ids.add(id(agent))
        else:
            seen_pids[agent.pid] = agent

    if pid_remove_ids:
        agents = [a for a in agents if id(a) not in pid_remove_ids]

    # Override status for DONE parents with active follow-up children.
    # When a planner workflow completes and spawns a coder follow-up
    # (linked via parent_timestamp), the parent should show PLAN APPROVED.
    _completed_statuses = {"DONE", "FAILED"}
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
            if agent.status not in _completed_statuses:
                parent = parent_by_suffix.get(agent.parent_timestamp)
                if parent and parent.status == "DONE":
                    parent.status = "PLAN APPROVED"

    # Override DONE → PLANNING for plan-only workflows (no follow-up spawned yet).
    # A workflow with role_suffix ".plan" that's still DONE means the plan was
    # submitted but no coder follow-up exists yet (awaiting user approval).
    # If a follow-up exists (even if completed), the plan was already approved.
    for agent in agents:
        if (
            agent.agent_type == AgentType.WORKFLOW
            and agent.role_suffix == ".plan"
            and agent.status == "DONE"
            and agent.raw_suffix not in parents_with_followup
        ):
            agent.status = "PLANNING"

    # Sort by start time (most recent first), with None times at end
    agents_with_time = [a for a in agents if a.start_time is not None]
    agents_without_time = [a for a in agents if a.start_time is None]

    agents_with_time.sort(key=lambda a: a.start_time, reverse=True)  # type: ignore

    sorted_agents = agents_with_time + agents_without_time

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

        result: list[Agent] = []
        for agent in sorted_agents:
            result.append(agent)
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
