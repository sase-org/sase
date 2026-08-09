"""Functions for loading and aggregating agents from all sources."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
    scan_agent_artifact_dirs,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import (
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.paths import sase_projects_dir

from ...patch import Patch, find_all_patches
from ...hooks.processes import is_process_running
from . import _agent_loader_artifacts as _artifacts
from ._agent_loader_artifacts import (
    AgentLoadState,
    artifact_delta_load_state as _artifact_delta_load_state,
    artifact_dirs_for_normalized_timestamps as _artifact_dirs_for_timestamps,
    artifact_snapshot_for_live_plan_load as _live_plan_artifact_snapshot,
    artifact_snapshot_for_tui_load as _tui_artifact_snapshot,
    normalize_timestamps as _normalize_artifact_timestamps,
    prepare_artifact_delta_paths as _prepare_artifact_delta_paths,
    query_artifact_index_for_loader as _query_artifact_index,
    update_artifact_index_from_delta as _update_artifact_index_from_delta,
)
from ._agent_loader_normalization import (
    apply_snapshot_clan_context as _apply_snapshot_clan_context,
    mark_live_artifact_delta_runners as _mark_delta_runners_live,
    normalize_live_plan_agents as _normalize_plan_agents,
    normalize_loaded_agents as _normalize_agents,
)
from ._agent_ordering import get_status_priority as _get_status_priority  # noqa: F401
from ._agent_status_overrides import (
    apply_status_overrides as _apply_status_overrides,
    is_coder_followup_suffix as _is_coder_followup_suffix,  # noqa: F401
    is_feedback_suffix as _is_feedback_suffix,  # noqa: F401
    is_root_plan_workflow as _is_root_plan_workflow,  # noqa: F401
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
from ._timestamps import normalize_to_14_digit
from .agent import Agent
from .workflow import WorkflowEntry

find_all_changespecs = find_all_patches


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
        sase_projects_dir(),
        options or _artifacts._TUI_SCAN_OPTIONS,
    )


def _scan_artifact_dirs_for_loader(
    artifact_dirs: Sequence[Path | str],
    options: AgentArtifactScanOptionsWire | None = None,
) -> "AgentArtifactScanWire":
    """Return a fresh exact artifact-dir snapshot for the TUI loader."""
    return scan_agent_artifact_dirs(
        sase_projects_dir(),
        artifact_dirs,
        options or _artifacts._TUI_SCAN_OPTIONS,
    )


def _projects_root_for_loader() -> Path:
    return sase_projects_dir()


def _query_artifact_index_for_loader(
    *,
    full_history: bool,
) -> tuple[AgentArtifactScanWire, AgentLoadState] | None:
    """Return an index-backed snapshot when the persistent index exists."""
    return _query_artifact_index(
        full_history=full_history,
        default_index_path=default_agent_artifact_index_path,
        projects_root=_projects_root_for_loader,
        query_index=query_agent_artifact_index,
        scan_artifacts=_scan_artifacts_for_loader,
    )


def _artifact_snapshot_for_tui_load(
    *,
    full_history: bool,
    use_artifact_index: bool = True,
) -> tuple[AgentArtifactScanWire, AgentLoadState]:
    """Return the artifact snapshot for a TUI refresh.

    Tier 1 uses the persistent artifact index when available. Missing or bad
    indexes fall back to a bounded source scan so first paint remains capped.
    Tier 2 always reconciles from source-of-truth artifacts so a stale index
    cannot keep visible history stale indefinitely.
    """

    return _tui_artifact_snapshot(
        full_history=full_history,
        use_artifact_index=use_artifact_index,
        scan_artifacts=_scan_artifacts_for_loader,
        load_tier1_index=_query_artifact_index_for_loader,
    )


def _artifact_snapshot_for_live_plan_load() -> AgentArtifactScanWire:
    """Return a bounded artifact snapshot for CLI plan notification matching."""
    return _live_plan_artifact_snapshot(
        default_index_path=default_agent_artifact_index_path,
        projects_root=_projects_root_for_loader,
        query_index=query_agent_artifact_index,
        scan_artifacts=_scan_artifacts_for_loader,
    )


def _normalize_timestamps(timestamps: Iterable[str]) -> set[str]:
    return _normalize_artifact_timestamps(timestamps)


def _artifact_dirs_for_normalized_timestamps(normalized: set[str]) -> list[Path]:
    return _artifact_dirs_for_timestamps(normalized)


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


def _patch_snapshot_for_loader(
    patch_snapshot: list[Patch] | None,
) -> list[Patch]:
    return (
        patch_snapshot
        if patch_snapshot is not None
        else find_all_changespecs(include_states="all")
    )


def _patch_agent_lookups(
    all_patches: list[Patch],
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    bug_by_cl_name: dict[str, str | None] = {}
    cl_by_cl_name: dict[str, str | None] = {}
    for cs in all_patches:
        if cs.bug:
            bug_id = cs.bug.removeprefix("http://b/")
            bug_by_cl_name[cs.name] = f"http://b/{bug_id}"
        if cs.pr_url:
            cl_by_cl_name[cs.name] = cs.pr_url
    return bug_by_cl_name, cl_by_cl_name


def _load_agents_from_artifact_snapshot_sources(
    artifact_snapshot: AgentArtifactScanWire,
    *,
    patch_snapshot: list[Patch] | None = None,
) -> tuple[list[Agent], list[Agent]]:
    """Load only artifact-backed agents from an exact scanner snapshot."""
    all_patches = _patch_snapshot_for_loader(patch_snapshot)
    bug_by_cl_name, cl_by_cl_name = _patch_agent_lookups(all_patches)

    agents: list[Agent] = []
    agents.extend(
        load_done_agents_from_snapshot(artifact_snapshot, bug_by_cl_name, cl_by_cl_name)
    )
    agents.extend(load_running_home_agents_from_snapshot(artifact_snapshot))
    workflow_agent_steps, step_meta_by_parent = load_workflow_agent_steps_from_snapshot(
        artifact_snapshot
    )
    agents.extend(
        load_workflow_agents_from_snapshot(
            artifact_snapshot,
            step_meta_by_parent=step_meta_by_parent,
        )
    )
    _apply_snapshot_clan_context(
        [*agents, *workflow_agent_steps],
        artifact_snapshot,
    )
    return agents, workflow_agent_steps


def _load_plan_agents_from_artifact_snapshot(
    artifact_snapshot: AgentArtifactScanWire,
) -> list[Agent]:
    """Load artifact-backed rows needed for plan notification liveness."""

    agents: list[Agent] = []
    agents.extend(load_done_agents_from_snapshot(artifact_snapshot, {}, {}))
    agents.extend(load_running_home_agents_from_snapshot(artifact_snapshot))
    agents.extend(
        load_workflow_agents_from_snapshot(
            artifact_snapshot,
            step_meta_by_parent=None,
        )
    )
    return agents


def _load_agents_from_all_sources(
    *,
    patch_snapshot: list[Patch] | None = None,
    artifact_snapshot: AgentArtifactScanWire | None = None,
) -> tuple[list[Agent], list[Agent]]:
    """Load agents from all sources and return (agents, workflow_agent_steps).

    Sources:
    1. RUNNING field in project files (workspace claims)
    2. done.json marker files (DONE agents)
    3. running.json markers (home mode agents)
    4. Workflow agent steps and workflow entries
    5. HOOKS, MENTORS, COMMENTS fields from Patches

    Args:
        patch_snapshot: Optional pre-fetched Patch list. When
            supplied, the loader skips the in-process ``find_all_patches()``
            call and reuses this snapshot for bug/PR lookups and the
            HOOKS/MENTORS/COMMENTS sweep.
    """
    agents: list[Agent] = []

    # Get all project files
    project_files = get_all_project_files()

    # Load all Patches early to build bug lookup. Caller-supplied
    # snapshots avoid re-globbing every project spec file when the TUI already
    # has a fresh cached snapshot in hand.
    all_patches = _patch_snapshot_for_loader(patch_snapshot)

    # Build bug URL and PR number lookups by Patch name (single pass)
    bug_by_cl_name, cl_by_cl_name = _patch_agent_lookups(all_patches)

    # 1. Load from RUNNING field (snapshot-independent; reads project spec files).
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

    # 2. Load from each Patch's fields
    for cs in all_patches:
        stripped_bug_id = cs.bug.removeprefix("http://b/") if cs.bug else None
        bug = f"http://b/{stripped_bug_id}" if stripped_bug_id else None
        cl_num = cs.pr_url

        # HOOKS - fix-hook and summarize agents
        agents.extend(load_agents_from_hooks(cs, bug, cl_num))

        # MENTORS - mentor agents
        agents.extend(load_agents_from_mentors(cs, bug, cl_num))

        # COMMENTS - CRS agents
        agents.extend(load_agents_from_comments(cs, bug, cl_num))

    _apply_snapshot_clan_context(
        [*agents, *workflow_agent_steps],
        artifact_snapshot,
    )
    return agents, workflow_agent_steps


def _load_agents_with_load_state(
    *,
    patch_snapshot: list[Patch] | None = None,
    full_history: bool = False,
    use_artifact_index: bool = True,
) -> _AgentLoadResult:
    """Load agents for the TUI and report whether history is complete."""

    artifact_snapshot, state = _artifact_snapshot_for_tui_load(
        full_history=full_history,
        use_artifact_index=use_artifact_index,
    )
    agents, workflow_agent_steps = _load_agents_from_all_sources(
        patch_snapshot=patch_snapshot,
        artifact_snapshot=artifact_snapshot,
    )
    return _AgentLoadResult(
        agents=agents,
        workflow_agent_steps=workflow_agent_steps,
        state=state,
    )


def _normalize_loaded_agents(
    agents: list[Agent],
    workflow_agent_steps: list[Agent],
) -> list[Agent]:
    return _normalize_agents(
        agents,
        workflow_agent_steps,
        is_process_running=is_process_running,
    )


def _mark_live_artifact_delta_runners(agents: list[Agent]) -> None:
    """Attach bounded PID liveness proof to exact-delta rows.

    Artifact deltas intentionally do not rescan ProjectSpec RUNNING claims.
    Rechecking only the PIDs already present in the exact delta keeps the
    worker-side operation bounded while preventing a stale retry marker from
    reviving a dead terminal row.
    """
    _mark_delta_runners_live(
        agents,
        is_process_running=is_process_running,
    )


def _normalize_live_plan_agents(agents: list[Agent]) -> list[Agent]:
    """Normalize the cheap visibility-affecting pieces for plan-list matching."""
    return _normalize_plan_agents(
        agents,
        is_process_running=is_process_running,
    )


def load_live_plan_agents() -> list[Agent]:
    """Load just the agent rows needed to match pending PlanApproval notifications."""

    agents: list[Agent] = []
    project_files = get_all_project_files()
    agents.extend(load_agents_from_running_field(project_files, {}, {}))
    artifact_snapshot = _artifact_snapshot_for_live_plan_load()
    agents.extend(_load_plan_agents_from_artifact_snapshot(artifact_snapshot))
    return _normalize_live_plan_agents(agents)


def load_live_plan_agents_for_timestamps(timestamps: Iterable[str]) -> list[Agent]:
    """Load plan-matching agent rows from exact artifact timestamps."""

    normalized = _normalize_timestamps(timestamps)
    if not normalized:
        return []

    agents = [
        agent
        for agent in load_agents_from_running_field(get_all_project_files(), {}, {})
        if agent.raw_suffix and normalize_to_14_digit(agent.raw_suffix) in normalized
    ]

    artifact_dirs = _artifact_dirs_for_normalized_timestamps(normalized)
    if not artifact_dirs:
        return _normalize_live_plan_agents(agents)
    snapshot = _scan_artifact_dirs_for_loader(
        artifact_dirs,
        _artifacts._PLAN_LIVE_SCAN_OPTIONS,
    )
    agents.extend(_load_plan_agents_from_artifact_snapshot(snapshot))
    return _normalize_live_plan_agents(agents)


def load_all_agents(
    *,
    patch_snapshot: list[Patch] | None = None,
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
        patch_snapshot: Optional pre-fetched Patch list. When
            supplied, the loader skips its own ``find_all_patches()``
            call and reuses this snapshot.

    Returns:
        List of Agent objects sorted by start time (most recent first),
        with agents that have no start time at the end.
    """
    agents, workflow_agent_steps = _load_agents_from_all_sources(
        patch_snapshot=patch_snapshot,
        artifact_snapshot=artifact_snapshot,
    )
    return _normalize_loaded_agents(agents, workflow_agent_steps)


def load_tiered_agents(
    *,
    patch_snapshot: list[Patch] | None = None,
    full_history: bool = False,
    use_artifact_index: bool = True,
) -> tuple[list[Agent], AgentLoadState]:
    """Load agents through the TUI tiered artifact path."""

    result = _load_agents_with_load_state(
        patch_snapshot=patch_snapshot,
        full_history=full_history,
        use_artifact_index=use_artifact_index,
    )
    return (
        _normalize_loaded_agents(result.agents, result.workflow_agent_steps),
        result.state,
    )


def load_artifact_delta_agents(
    artifact_dirs: Sequence[Path | str],
    *,
    patch_snapshot: list[Patch] | None = None,
    changespec_snapshot: list[Patch] | None = None,
    update_index: bool = True,
    deleted_artifact_dirs: Sequence[Path | str] = (),
) -> tuple[list[Agent], AgentLoadState]:
    """Load normalized agents from an exact set of artifact directories."""
    if patch_snapshot is None:
        patch_snapshot = changespec_snapshot

    unique_dirs, seen_dirs, deleted_dir_keys = _prepare_artifact_delta_paths(
        artifact_dirs,
        deleted_artifact_dirs,
    )

    snapshot = _scan_artifact_dirs_for_loader(unique_dirs)
    _update_artifact_index_from_delta(snapshot, update_index=update_index)
    state = _artifact_delta_load_state(
        snapshot,
        seen_dirs=seen_dirs,
        deleted_dir_keys=deleted_dir_keys,
    )
    agents, workflow_agent_steps = _load_agents_from_artifact_snapshot_sources(
        snapshot,
        patch_snapshot=patch_snapshot,
    )
    normalized = _normalize_loaded_agents(agents, workflow_agent_steps)
    _mark_live_artifact_delta_runners(normalized)
    return normalized, state
