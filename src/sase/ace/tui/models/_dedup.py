"""Deduplication logic for loaded agents.

Handles merging duplicate agents that appear from multiple sources
(RUNNING field, ChangeSpec fields, workflow_state.json, done.json).
"""

from ._timestamps import (
    extract_timestamp_from_workflow,
    extract_timestamp_str_from_suffix,
    normalize_to_14_digit,
)
from .agent import Agent, AgentType

# Workflow name prefixes for axe-spawned agents (normalized: dashes → underscores)
_AXE_WORKFLOW_PREFIXES = ["axe(mentor)", "axe(fix_hook)", "axe(crs)", "mentor("]

# Done.json workflow names/prefixes for axe-spawned agents (normalized)
_DONE_AXE_WORKFLOWS = {"fix_hook", "crs", "summarize_hook"}
_DONE_AXE_PREFIXES = ["mentor_"]

# Plain workflow names from workflow_state.json / done.json for axe-spawned agents
_PLAIN_AXE_WORKFLOWS = {"fix_hook", "crs", "mentor", "summarize_hook"}
_PLAIN_AXE_PREFIXES = ("mentor_",)


def _is_workspace_claim_workflow(workflow: str | None) -> bool:
    """Return whether *workflow* is a registered workspace-provider claim."""
    if not workflow:
        return False

    from sase.workspace_provider import get_workflow_names

    return any(workflow.startswith(f"{name}-") for name in get_workflow_names())


def _merge_agent_fields(target: Agent, source: Agent) -> None:
    """Merge non-None fields from source agent into target agent.

    Only copies fields that are None/empty on the target but set on the source.
    This preserves metadata (workspace_num, model, etc.) from VCS workspace
    agents that are being removed as duplicates.
    """
    if target.workspace_num is None and source.workspace_num is not None:
        target.workspace_num = source.workspace_num
    if source.runner_is_live:
        target.runner_is_live = True
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
    if target.wait_runners is None and source.wait_runners is not None:
        target.wait_runners = source.wait_runners
        target.wait_runners_explicit = source.wait_runners_explicit
    if target.slot_requested_at is None and source.slot_requested_at is not None:
        target.slot_requested_at = source.slot_requested_at
    if target.approve is False and source.approve is True:
        target.approve = source.approve
    if target.start_time is None and source.start_time is not None:
        target.start_time = source.start_time
    if target.raw_suffix is None and source.raw_suffix is not None:
        target.raw_suffix = source.raw_suffix
    if target.retried_as_timestamp is None and source.retried_as_timestamp is not None:
        target.retried_as_timestamp = source.retried_as_timestamp
    if target.retry_of_timestamp is None and source.retry_of_timestamp is not None:
        target.retry_of_timestamp = source.retry_of_timestamp
    if (
        target.retry_chain_root_timestamp is None
        and source.retry_chain_root_timestamp is not None
    ):
        target.retry_chain_root_timestamp = source.retry_chain_root_timestamp
    if target.retry_attempt == 0 and source.retry_attempt > 0:
        target.retry_attempt = source.retry_attempt
    if not target.retry_terminal and source.retry_terminal:
        target.retry_terminal = True
    if target.retry_error_category is None and source.retry_error_category is not None:
        target.retry_error_category = source.retry_error_category
    # ChangeSpec-sourced fields (mentor, hook, CRS metadata)
    if target.mentor_profile is None and source.mentor_profile is not None:
        target.mentor_profile = source.mentor_profile
    if target.mentor_name is None and source.mentor_name is not None:
        target.mentor_name = source.mentor_name
    if target.hook_command is None and source.hook_command is not None:
        target.hook_command = source.hook_command
    if target.reviewer is None and source.reviewer is not None:
        target.reviewer = source.reviewer
    if target.commit_entry_id is None and source.commit_entry_id is not None:
        target.commit_entry_id = source.commit_entry_id


def dedup_axe_spawned_agents(agents: list[Agent]) -> list[Agent]:
    """Deduplicate axe-spawned agents by timestamp.

    Axe agents appear in both RUNNING field (as RUNNING type with axe(...) workflow)
    and ChangeSpec fields (also RUNNING type, with _from_changespec=True).
    Prefer the RUNNING field entry and merge type-specific metadata from ChangeSpec.
    """
    # Build index of RUNNING agents with axe(...) workflows by (cl_name, timestamp)
    running_axe_agents_by_key: dict[tuple[str, str], Agent] = {}
    for agent in agents:
        if agent.agent_type == AgentType.RUNNING:
            workflow = agent.workflow or ""
            norm_workflow = workflow.replace("-", "_")
            if any(norm_workflow.startswith(p) for p in _AXE_WORKFLOW_PREFIXES):
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
    for agent in agents:
        if (
            agent.agent_type == AgentType.RUNNING
            and agent.status in ("DONE", "FAILED")
            and agent.workflow
        ):
            norm_wf = agent.workflow.replace("-", "_")
            is_done_axe = norm_wf in _DONE_AXE_WORKFLOWS or any(
                norm_wf.startswith(p) for p in _DONE_AXE_PREFIXES
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

    return final_agents


def remove_vcs_workspace_claims(agents: list[Agent]) -> list[Agent]:
    """Remove embedded VCS workspace claims from axe-spawned agents.

    When an axe agent embeds a workspace workflow, that workflow claims its own
    workspace (appearing as a separate RUNNING entry like ``git-<ref>``).
    These share the same PID as the parent axe agent via os.getppid().
    We remove these entirely (not just hide) so they never appear as
    duplicate PID entries, even when hidden agents are toggled visible.
    Before removal, merge VCS agent fields (workspace_num, model, etc.)
    into the surviving axe agent so no metadata is lost.
    """
    axe_agents_by_pid: dict[int, Agent] = {}
    for agent in agents:
        if agent.pid is not None and agent.workflow:
            norm_wf = agent.workflow.replace("-", "_")
            is_axe = (
                any(norm_wf.startswith(p) for p in _AXE_WORKFLOW_PREFIXES)
                or norm_wf in _PLAIN_AXE_WORKFLOWS
                or norm_wf.startswith(_PLAIN_AXE_PREFIXES)
            )
            if is_axe:
                axe_agents_by_pid[agent.pid] = agent

    if not axe_agents_by_pid:
        return agents

    vcs_remove_ids: set[int] = set()
    for agent in agents:
        if (
            agent.agent_type == AgentType.RUNNING
            and agent.pid is not None
            and agent.pid in axe_agents_by_pid
            and _is_workspace_claim_workflow(agent.workflow)
        ):
            # Merge fields from VCS workspace into surviving axe agent
            axe_agent = axe_agents_by_pid[agent.pid]
            _merge_agent_fields(axe_agent, agent)
            vcs_remove_ids.add(id(agent))
    if vcs_remove_ids:
        agents = [a for a in agents if id(a) not in vcs_remove_ids]

    return agents


def dedup_workflow_entries(agents: list[Agent]) -> list[Agent]:
    """Deduplicate workflow entries: match by (project_file, raw_suffix).

    Prefer workflow_state.json entries (accurate status), but copy
    workspace_num and cl_name from RUNNING field entries.

    The dedup key is project-scoped — two agents are only treated as
    duplicates when they share the same project's artifact tree. A bare
    ``raw_suffix`` (timestamp dir name) is only unique within one project,
    so two unrelated projects whose runs launched in the same clock second
    would otherwise collide and cross-contaminate status/pid/cl_name.
    """
    seen_suffixes: dict[tuple[str, str], Agent] = {}
    for agent in agents:
        if agent.agent_type == AgentType.WORKFLOW and agent.raw_suffix:
            key = (agent.project_file, agent.raw_suffix)
            if key in seen_suffixes:
                existing = seen_suffixes[key]
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
                seen_suffixes[key] = agent

    # Filter out duplicates
    return [
        a
        for a in agents
        if a.agent_type != AgentType.WORKFLOW
        or not a.raw_suffix
        or (a.project_file, a.raw_suffix) not in seen_suffixes
        or seen_suffixes.get((a.project_file, a.raw_suffix)) is a
    ]


def dedup_running_vs_workflow(agents: list[Agent]) -> list[Agent]:
    """Deduplicate RUNNING↔WORKFLOW: ace-run RUNNING agents vs WORKFLOW agents.

    From the same artifacts directory (matching raw_suffix / timestamp).
    RUNNING field uses "ace(run)" workflow; done.json uses "ace-run" (dir name).
    Prefer WORKFLOW (has step info / appears_as_agent), merge metadata from RUNNING.

    The match key is project-scoped — a RUNNING ace-run agent only merges into
    a WORKFLOW agent from the same project's artifact tree. A bare ``raw_suffix``
    is only unique within one project, so without scoping a running agent in
    project A could be conflated with a workflow agent in project B that happened
    to launch in the same clock second.
    """
    workflow_by_suffix: dict[tuple[str, str], Agent] = {}
    for agent in agents:
        if agent.agent_type == AgentType.WORKFLOW and agent.raw_suffix:
            workflow_by_suffix[(agent.project_file, agent.raw_suffix)] = agent

    deduped_agents: list[Agent] = []
    for agent in agents:
        if (
            agent.agent_type == AgentType.RUNNING
            and agent.workflow is not None
            and (
                agent.workflow.startswith("ace(run)")
                or agent.workflow == "ace-run"
                or agent.workflow == "run"
            )
            and agent.raw_suffix
            and (agent.project_file, agent.raw_suffix) in workflow_by_suffix
        ):
            # Match found — merge metadata into the WORKFLOW agent
            matched = workflow_by_suffix[(agent.project_file, agent.raw_suffix)]
            _merge_agent_fields(matched, agent)
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
            if matched.llm_provider is None and agent.llm_provider is not None:
                matched.llm_provider = agent.llm_provider
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
            elif matched.step_output is not None and agent.step_output is not None:
                for k, v in agent.step_output.items():
                    if k not in matched.step_output:
                        matched.step_output[k] = v
            if matched.agent_name is None and agent.agent_name is not None:
                matched.agent_name = agent.agent_name
            # A failed anonymous workflow can still belong to a live outer
            # runner that is waiting to retry it. Keep the row live so the
            # retry-state projection can promote it to RETRYING. A terminal
            # failure has no live RUNNING claim and reaches the loader through
            # done.json instead.
            if agent.status in {"DONE", "FAILED", "FAILED (RETRIED)", "STOPPED"}:
                matched.status = agent.status
            elif matched.status == "FAILED" and agent.status == "RUNNING":
                matched.status = "RUNNING"
            # Otherwise prefer semantic non-RUNNING statuses (e.g. PLAN,
            # PLAN APPROVED, WORKING PLAN) over the raw live-process row.
            elif matched.status == "RUNNING" and agent.status != "RUNNING":
                matched.status = agent.status
            continue  # Drop the RUNNING entry
        deduped_agents.append(agent)

    return deduped_agents


def dedup_by_pid(agents: list[Agent]) -> list[Agent]:
    """Final safety net: enforce no duplicate PIDs among all agents.

    When multiple agents share a PID, keep the one with the most specific
    workflow type (WORKFLOW > RUNNING) and remove the rest. This catches any
    VCS workspace duplicates that slipped through earlier dedup passes.
    Operates on ALL agents (including hidden) to prevent duplicate PIDs
    from appearing when hidden agents are toggled visible.
    """
    seen_pids: dict[int, Agent] = {}
    pid_remove_ids: set[int] = set()
    for agent in agents:
        if agent.pid is None:
            continue
        if agent.pid in seen_pids:
            existing = seen_pids[agent.pid]
            # Prefer WORKFLOW over RUNNING, and non-VCS over VCS workflows
            existing_is_vcs = _is_workspace_claim_workflow(existing.workflow)
            agent_is_vcs = _is_workspace_claim_workflow(agent.workflow)
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
            elif (
                agent.agent_type == AgentType.RUNNING
                and existing.agent_type == AgentType.RUNNING
                and agent.raw_suffix
                and existing.raw_suffix
                and agent.raw_suffix != existing.raw_suffix
            ):
                # Both RUNNING agents with distinct timestamps — these are
                # separate agents that share a PID due to OS PID recycling.
                # Keep both.
                pass
            else:
                # Same type, same or missing suffix — remove the newer one
                _merge_agent_fields(existing, agent)
                pid_remove_ids.add(id(agent))
        else:
            seen_pids[agent.pid] = agent

    if pid_remove_ids:
        agents = [a for a in agents if id(a) not in pid_remove_ids]

    return agents
