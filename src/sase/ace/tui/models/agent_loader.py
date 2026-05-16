"""Functions for loading and aggregating agents from all sources."""

from dataclasses import replace
from pathlib import Path
import time

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)

from ...changespec import ChangeSpec, find_all_changespecs
from ...hooks.processes import is_process_running
from ._agent_loader_artifacts import (
    _TUI_SCAN_OPTIONS,  # re-exported for legacy private callers
    artifact_snapshot_for_tui_load as _artifact_snapshot_for_tui_load_impl,
    empty_snapshot_for_missing_index as _empty_snapshot_for_missing_index_impl,
    load_state_with_stats as _load_state_with_stats,
    load_workflow_children_for_parent as _load_workflow_children_for_parent_impl,
    projects_root_for_loader as _projects_root_for_loader_impl,
    query_artifact_index_for_loader as _query_artifact_index_for_loader_impl,
    scan_artifacts_for_loader as _scan_artifacts_for_loader_impl,
    tui_inbox_query as _tui_inbox_query_impl,
)
from ._agent_loader_sources import load_agents_from_all_sources
from ._agent_loader_state import AgentLoadResult as _AgentLoadResult
from ._agent_loader_state import AgentLoadState
from ._agent_ordering import (
    get_status_priority as _get_status_priority,  # noqa: F401
    sort_and_reorder as _sort_and_reorder,
)
from ._agent_status_overrides import (
    apply_status_overrides as _apply_status_overrides,
    is_coder_followup_suffix as _is_coder_followup_suffix,  # noqa: F401
    is_feedback_suffix as _is_feedback_suffix,  # noqa: F401
    is_root_plan_workflow as _is_root_plan_workflow,  # noqa: F401
)
from ._dedup import (
    dedup_axe_spawned_agents,
    dedup_by_pid,
    dedup_running_vs_workflow,
    dedup_workflow_entries,
    remove_vcs_workspace_claims,
)
from ._loaders import (
    get_all_project_files,
    get_workflow_timestamp_dirs,  # noqa: F401  re-exported for fallback callers
    load_agents_from_comments,
    load_agents_from_hooks,
    load_agents_from_mentors,
    load_agents_from_running_field,
    load_done_agents,  # noqa: F401  re-exported for fallback/tests
    load_done_agents_from_snapshot,
    load_running_home_agents,  # noqa: F401  re-exported for fallback/tests
    load_running_home_agents_from_snapshot,
    load_workflow_agent_steps,  # noqa: F401  re-exported for fallback/tests
    load_workflow_agent_steps_from_snapshot,
    load_workflow_agents,  # noqa: F401  re-exported for fallback/tests
    load_workflow_agents_from_snapshot,
    load_workflow_states,  # noqa: F401  re-exported for fallback/tests
    load_workflow_states_from_snapshot,  # noqa: F401  re-exported for fallback/tests
)
from .agent import Agent
from .workflow import WorkflowEntry


def _empty_snapshot_for_missing_index() -> AgentArtifactScanWire:
    """Build a deterministic empty snapshot for the missing-index Tier 1 path."""

    return _empty_snapshot_for_missing_index_impl(_projects_root_for_loader)


def _scan_artifacts_for_loader(
    options: AgentArtifactScanOptionsWire | None = None,
) -> "AgentArtifactScanWire":
    """Return one fresh artifact-tree snapshot for the TUI loader."""

    return _scan_artifacts_for_loader_impl(scan_agent_artifacts, options)


def _projects_root_for_loader() -> Path:
    return _projects_root_for_loader_impl()


def _tui_inbox_query() -> AgentArtifactIndexQueryWire:
    """Return the visibility-aware Tier 1 inbox query for ordinary refreshes."""

    return _tui_inbox_query_impl()


def _query_artifact_index_for_loader(
    *,
    full_history: bool,
    agent_search_active: bool,
) -> tuple[AgentArtifactScanWire, AgentLoadState] | None:
    """Return an index-backed snapshot for the TUI inbox refresh."""

    return _query_artifact_index_for_loader_impl(
        full_history=full_history,
        agent_search_active=agent_search_active,
        default_agent_artifact_index_path_fn=default_agent_artifact_index_path,
        query_agent_artifact_index_fn=query_agent_artifact_index,
        scan_artifacts_for_loader_fn=_scan_artifacts_for_loader,
        projects_root_for_loader_fn=_projects_root_for_loader,
        empty_snapshot_for_missing_index_fn=_empty_snapshot_for_missing_index,
        tui_inbox_query_fn=_tui_inbox_query,
    )


def load_workflow_children_for_parent(parent: Agent) -> list[Agent]:
    """Load prompt-step child rows for one workflow parent from the index."""

    return _load_workflow_children_for_parent_impl(
        parent,
        default_agent_artifact_index_path_fn=default_agent_artifact_index_path,
        query_agent_artifact_index_fn=query_agent_artifact_index,
        projects_root_for_loader_fn=_projects_root_for_loader,
        load_workflow_agent_steps_from_snapshot_fn=(
            load_workflow_agent_steps_from_snapshot
        ),
    )


def _artifact_snapshot_for_tui_load(
    *,
    full_history: bool,
    agent_search_active: bool,
) -> tuple[AgentArtifactScanWire, AgentLoadState]:
    """Return the artifact snapshot for a TUI refresh."""

    return _artifact_snapshot_for_tui_load_impl(
        full_history=full_history,
        agent_search_active=agent_search_active,
        scan_artifacts_for_loader_fn=_scan_artifacts_for_loader,
        query_artifact_index_for_loader_fn=lambda full, search: (
            _query_artifact_index_for_loader(
                full_history=full,
                agent_search_active=search,
            )
        ),
    )


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


def _load_agents_from_all_sources(
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
    artifact_snapshot: AgentArtifactScanWire | None = None,
) -> tuple[list[Agent], list[Agent]]:
    """Load agents from all sources and return (agents, workflow_agent_steps)."""

    return load_agents_from_all_sources(
        changespec_snapshot=changespec_snapshot,
        artifact_snapshot=artifact_snapshot,
        get_all_project_files_fn=get_all_project_files,
        find_all_changespecs_fn=find_all_changespecs,
        scan_artifacts_for_loader_fn=lambda: _scan_artifacts_for_loader(),
        load_agents_from_running_field_fn=load_agents_from_running_field,
        load_done_agents_from_snapshot_fn=load_done_agents_from_snapshot,
        load_running_home_agents_from_snapshot_fn=(
            load_running_home_agents_from_snapshot
        ),
        load_workflow_agent_steps_from_snapshot_fn=(
            load_workflow_agent_steps_from_snapshot
        ),
        load_workflow_agents_from_snapshot_fn=load_workflow_agents_from_snapshot,
        load_agents_from_hooks_fn=load_agents_from_hooks,
        load_agents_from_mentors_fn=load_agents_from_mentors,
        load_agents_from_comments_fn=load_agents_from_comments,
    )


def _load_agents_with_load_state(
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
    full_history: bool = False,
    agent_search_active: bool = False,
) -> _AgentLoadResult:
    """Load agents for the TUI and report whether history is complete."""

    artifact_snapshot, state = _artifact_snapshot_for_tui_load(
        full_history=full_history,
        agent_search_active=agent_search_active,
    )
    from ..util.trace import tui_trace

    started = time.perf_counter()
    with tui_trace(
        "agents.snapshot_model_hydration",
        snapshot_records=len(artifact_snapshot.records),
    ) as trace_fields:
        agents, workflow_agent_steps = _load_agents_from_all_sources(
            changespec_snapshot=changespec_snapshot,
            artifact_snapshot=artifact_snapshot,
        )
        trace_fields["loaded_parent_candidates"] = len(agents)
        trace_fields["loaded_child_candidates"] = len(workflow_agent_steps)
    hydration_ms = (time.perf_counter() - started) * 1000.0
    return _AgentLoadResult(
        agents=agents,
        workflow_agent_steps=workflow_agent_steps,
        state=replace(state, snapshot_hydration_ms=hydration_ms),
    )


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


def load_all_agents(
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
    artifact_snapshot: AgentArtifactScanWire | None = None,
) -> list[Agent]:
    """Load all running agents from all sources.

    Sources:
    1. RUNNING field in project files (workspace claims)
    2. HOOKS field with suffix_type="running_agent" (fix_hook, summarize_hook)
    3. MENTORS field with suffix_type="running_agent"
    4. COMMENTS field with suffix_type="running_agent" (CRS)
    5. done.json marker files (DONE agents)

    Args:
        changespec_snapshot: Optional pre-fetched ChangeSpec list. When
            supplied, the loader skips its own ``find_all_changespecs()``
            call and reuses this snapshot.

    Returns:
        List of Agent objects sorted by start time (most recent first),
        with agents that have no start time at the end.
    """
    agents, workflow_agent_steps = _load_agents_from_all_sources(
        changespec_snapshot=changespec_snapshot,
        artifact_snapshot=artifact_snapshot,
    )

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


def load_tiered_agents(
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
    full_history: bool = False,
    agent_search_active: bool = False,
) -> tuple[list[Agent], AgentLoadState]:
    """Load agents through the TUI tiered artifact path."""

    result = _load_agents_with_load_state(
        changespec_snapshot=changespec_snapshot,
        full_history=full_history,
        agent_search_active=agent_search_active,
    )
    agents = result.agents

    from ..util.trace import tui_trace

    started = time.perf_counter()
    # Filter out agents with dead PIDs (but keep completed agents)
    with tui_trace(
        "agents.python_model_pipeline",
        parent_candidates=len(agents),
        child_candidates=len(result.workflow_agent_steps),
    ) as trace_fields:
        agents = _filter_dead_pids(agents)

        # Deduplication pipeline
        agents = dedup_axe_spawned_agents(agents)
        agents = remove_vcs_workspace_claims(agents)
        agents = dedup_workflow_entries(agents)
        agents = dedup_running_vs_workflow(agents)
        agents = dedup_by_pid(agents)

        # Override statuses based on workflow relationships
        _apply_status_overrides(agents)

        sorted_agents = _sort_and_reorder(agents, result.workflow_agent_steps)
        trace_fields["sorted_agent_count"] = len(sorted_agents)
    model_sort_ms = (time.perf_counter() - started) * 1000.0
    state = replace(
        result.state,
        loaded_agent_count=len(sorted_agents),
        loaded_workflow_step_count=len(result.workflow_agent_steps),
        model_sort_ms=model_sort_ms,
    )
    return sorted_agents, state
