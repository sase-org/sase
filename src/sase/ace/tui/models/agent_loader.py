"""Functions for loading and aggregating agents from all sources."""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

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


_TUI_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=True,
    # The TUI reads prompt-step markers (workflow agent steps + meta_*
    # propagation) but does not render the raw_xprompt.md snippet; skip
    # the snippet read to keep the scan compact.
    include_raw_prompt_snippets=False,
)

_TIER1_RECENT_COMPLETED_LIMIT = 200
_TIER1_FALLBACK_SCAN_OPTIONS = replace(
    _TUI_SCAN_OPTIONS,
    max_records=_TIER1_RECENT_COMPLETED_LIMIT,
    newest_first=True,
)


@dataclass(frozen=True)
class AgentLoadState:
    """Artifact-history completeness for one TUI agent load."""

    tier: Literal["tier1", "tier2"]
    complete_history: bool
    artifact_source: Literal["artifact_index", "source_scan"]
    used_artifact_index: bool
    index_error: str | None = None

    @property
    def needs_full_history_reconcile(self) -> bool:
        """Return whether the caller should schedule a Tier 2 refresh."""

        return not self.complete_history


@dataclass(frozen=True)
class _AgentLoadResult:
    """Agents plus metadata about the artifact-history tier used."""

    agents: list[Agent]
    workflow_agent_steps: list[Agent]
    state: AgentLoadState


def _scan_artifacts_for_loader(
    options: AgentArtifactScanOptionsWire | None = None,
) -> "AgentArtifactScanWire":
    """Return one fresh artifact-tree snapshot for the TUI loader.

    Single-purpose seam between :func:`_load_agents_from_all_sources` and
    :func:`scan_agent_artifacts` so tests can replace the snapshot with a
    fixture without having to patch every individual ``_from_snapshot``
    consumer.
    """
    return scan_agent_artifacts(
        Path.home() / ".sase" / "projects",
        options or _TUI_SCAN_OPTIONS,
    )


def _projects_root_for_loader() -> Path:
    return Path.home() / ".sase" / "projects"


def _query_artifact_index_for_loader(
    *,
    full_history: bool,
) -> tuple[AgentArtifactScanWire, AgentLoadState] | None:
    """Return an index-backed snapshot when the persistent index exists."""

    if full_history:
        return None

    index_path = default_agent_artifact_index_path()
    if not index_path.is_file():
        return None

    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=False,
        recent_completed_limit=_TIER1_RECENT_COMPLETED_LIMIT,
        include_hidden=False,
    )
    try:
        snapshot = query_agent_artifact_index(
            index_path,
            _projects_root_for_loader(),
            query=query,
            options=_TUI_SCAN_OPTIONS,
        )
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError) as exc:
        return (
            _scan_artifacts_for_loader(_TIER1_FALLBACK_SCAN_OPTIONS),
            AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="source_scan",
                used_artifact_index=False,
                index_error=str(exc),
            ),
        )

    return (
        snapshot,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
        ),
    )


def _artifact_snapshot_for_tui_load(
    *,
    full_history: bool,
) -> tuple[AgentArtifactScanWire, AgentLoadState]:
    """Return the artifact snapshot for a TUI refresh.

    Tier 1 uses the persistent artifact index when available. Missing or bad
    indexes fall back to a bounded source scan so first paint remains capped.
    Tier 2 always reconciles from source-of-truth artifacts so a stale index
    cannot keep visible history stale indefinitely.
    """

    if full_history:
        return (
            _scan_artifacts_for_loader(),
            AgentLoadState(
                tier="tier2",
                complete_history=True,
                artifact_source="source_scan",
                used_artifact_index=False,
            ),
        )

    indexed = _query_artifact_index_for_loader(full_history=full_history)
    if indexed is not None:
        return indexed

    return (
        _scan_artifacts_for_loader(_TIER1_FALLBACK_SCAN_OPTIONS),
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="source_scan",
            used_artifact_index=False,
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
    """Load agents from all sources and return (agents, workflow_agent_steps).

    Sources:
    1. RUNNING field in project files (workspace claims)
    2. done.json marker files (DONE agents)
    3. running.json markers (home mode agents)
    4. Workflow agent steps and workflow entries
    5. HOOKS, MENTORS, COMMENTS fields from ChangeSpecs

    Args:
        changespec_snapshot: Optional pre-fetched ChangeSpec list. When
            supplied, the loader skips the in-process ``find_all_changespecs()``
            call and reuses this snapshot for bug/CL lookups and the
            HOOKS/MENTORS/COMMENTS sweep.
    """
    agents: list[Agent] = []

    # Get all project files
    project_files = get_all_project_files()

    # Load all ChangeSpecs early to build bug lookup. Caller-supplied
    # snapshots avoid re-globbing every ``.gp`` file when the TUI already
    # has a fresh cached snapshot in hand.
    all_changespecs = (
        changespec_snapshot
        if changespec_snapshot is not None
        else find_all_changespecs()
    )

    # Build bug URL and CL number lookups by CL name (single pass)
    bug_by_cl_name: dict[str, str | None] = {}
    cl_by_cl_name: dict[str, str | None] = {}
    for cs in all_changespecs:
        if cs.bug:
            bug_id = cs.bug.removeprefix("http://b/")
            bug_by_cl_name[cs.name] = f"http://b/{bug_id}"
        if cs.cl:
            cl_by_cl_name[cs.name] = cs.cl

    # 1. Load from RUNNING field (snapshot-independent; reads project .gp files).
    agents.extend(
        load_agents_from_running_field(project_files, bug_by_cl_name, cl_by_cl_name)
    )

    # Acquire a single artifact snapshot for every artifact-tree consumer
    # below. Phase 3F replaces independent walks of done/running/workflow
    # subtrees with one ``scan_agent_artifacts()`` snapshot so the
    # filesystem (and, in Rust mode, the FFI conversion) only pays the
    # walking + JSON parsing cost once per refresh.
    if artifact_snapshot is None:
        artifact_snapshot = _scan_artifacts_for_loader()

    # 1a. Load completed (DONE) agents
    agents.extend(
        load_done_agents_from_snapshot(artifact_snapshot, bug_by_cl_name, cl_by_cl_name)
    )

    # 1b. Load running home mode agents (from running.json markers)
    agents.extend(load_running_home_agents_from_snapshot(artifact_snapshot))

    # 1d. Load workflow agent steps first — also collects meta_* fields
    # per parent timestamp so load_workflow_agents() can skip redundant
    # prompt_step_*.json reads.
    workflow_agent_steps, step_meta_by_parent = load_workflow_agent_steps_from_snapshot(
        artifact_snapshot
    )

    # 1c. Load workflow entries as agents (with pre-collected meta fields)
    agents.extend(
        load_workflow_agents_from_snapshot(
            artifact_snapshot,
            step_meta_by_parent=step_meta_by_parent,
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


def _load_agents_with_load_state(
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
    full_history: bool = False,
) -> _AgentLoadResult:
    """Load agents for the TUI and report whether history is complete."""

    artifact_snapshot, state = _artifact_snapshot_for_tui_load(
        full_history=full_history
    )
    agents, workflow_agent_steps = _load_agents_from_all_sources(
        changespec_snapshot=changespec_snapshot,
        artifact_snapshot=artifact_snapshot,
    )
    return _AgentLoadResult(
        agents=agents,
        workflow_agent_steps=workflow_agent_steps,
        state=state,
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
) -> tuple[list[Agent], AgentLoadState]:
    """Load agents through the TUI tiered artifact path."""

    result = _load_agents_with_load_state(
        changespec_snapshot=changespec_snapshot,
        full_history=full_history,
    )
    agents = result.agents

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

    return _sort_and_reorder(agents, result.workflow_agent_steps), result.state
