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
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
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


def _empty_snapshot_for_missing_index() -> AgentArtifactScanWire:
    """Build a deterministic empty snapshot for the missing-index Tier 1 path.

    Phase 3 of ``sase-3r`` (Fast Agents Tab Disk Loading) stops the loader
    from issuing a source-tree scan when the persistent artifact index is
    absent. The caller-visible loader contract still requires a wire — the
    snapshot is intentionally empty so artifact-derived agents are skipped
    until the rebuild worker repopulates the index, while RUNNING-field
    project entries continue to flow through ``_load_agents_from_all_sources``.
    """

    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(_projects_root_for_loader()),
        options=_TUI_SCAN_OPTIONS,
        stats=AgentArtifactScanStatsWire(),
        records=[],
    )


@dataclass(frozen=True)
class AgentLoadState:
    """Artifact-history completeness for one TUI agent load.

    Phase 1 of bead ``sase-3r`` (Fast Agents Tab Disk Loading) widens this
    contract so future phases can see exactly what the loader did without
    having to reproduce its branching logic. The added fields are
    measurement-only and intentionally do not change loader behavior:

    Attributes:
        tier: ``tier1`` for visibility-bounded refreshes; ``tier2`` for
            full-history reconciles.
        complete_history: Whether every artifact-backed agent is present
            in the result (Tier 2 / explicit full-history loads only).
        artifact_source: ``artifact_index`` when the snapshot came from
            the persistent index; ``source_scan`` when it came from the
            filesystem walk.
        used_artifact_index: Convenience flag mirroring
            ``artifact_source == "artifact_index"``.
        index_error: Stringified exception from the index query that
            triggered a source-scan fallback, or ``None`` on success.
        full_history: ``True`` when the caller asked for (or was forced
            into) a Tier 2 full-history load. Captured separately from
            ``complete_history`` so Phase 3 can demote "search forces
            full history" without rewriting every assertion.
        agent_search_active: ``True`` when the Agents-tab search query
            was non-empty at the time the loader was invoked. Today this
            implies ``full_history=True``; the contract test in
            ``tests/ace/tui/actions/test_agent_loader_phase1_guardrails.py``
            locks that in so Phase 3 must change it deliberately.
        snapshot_records: Number of ``AgentArtifactRecordWire`` rows in
            the underlying scan snapshot.
        loaded_agent_count: Number of agents the loader returned to the
            TUI (after dedup and status overrides).
        loaded_workflow_step_count: Number of workflow agent-step rows
            returned alongside the loader's agents list.
        artifact_dirs_visited: Snapshot ``stats.artifact_dirs_visited``
            when available, else ``None``.
        marker_files_parsed: Snapshot ``stats.marker_files_parsed`` when
            available, else ``None``.
        prompt_step_markers_parsed: Snapshot
            ``stats.prompt_step_markers_parsed`` when available, else
            ``None``.
        index_missing: Phase 3 of ``sase-3r``. ``True`` when the loader
            could not consult the persistent artifact index because the
            sqlite file was absent and the snapshot was returned empty
            instead of doing a fallback source scan. The apply layer uses
            this to schedule a one-off index rebuild rather than a Tier 2
            source scan.
    """

    tier: Literal["tier1", "tier2"]
    complete_history: bool
    artifact_source: Literal["artifact_index", "source_scan"]
    used_artifact_index: bool
    index_error: str | None = None
    full_history: bool = False
    agent_search_active: bool = False
    snapshot_records: int = 0
    loaded_agent_count: int = 0
    loaded_workflow_step_count: int = 0
    artifact_dirs_visited: int | None = None
    marker_files_parsed: int | None = None
    prompt_step_markers_parsed: int | None = None
    index_missing: bool = False

    @property
    def needs_full_history_reconcile(self) -> bool:
        """Return whether the caller should schedule a Tier 2 refresh.

        Phase 3 of ``sase-3r`` narrows this to source-scan fallbacks (the
        bounded-scan path triggered by an index-query error). The
        visibility-aware Tier 1 inbox query is the answer the caller
        wants, so successful index reads no longer schedule a Tier 2
        reconcile. Missing-index loads expose ``index_missing`` for the
        rebuild path instead.
        """

        if self.complete_history:
            return False
        if self.index_missing:
            return False
        return self.artifact_source == "source_scan"

    def trace_fields(self) -> dict[str, object]:
        """Return a JSON-friendly mapping for ``tui_trace`` enrichment."""

        return {
            "tier": self.tier,
            "complete_history": self.complete_history,
            "artifact_source": self.artifact_source,
            "used_artifact_index": self.used_artifact_index,
            "index_error": self.index_error,
            "full_history": self.full_history,
            "agent_search_active": self.agent_search_active,
            "snapshot_records": self.snapshot_records,
            "loaded_agent_count": self.loaded_agent_count,
            "loaded_workflow_step_count": self.loaded_workflow_step_count,
            "artifact_dirs_visited": self.artifact_dirs_visited,
            "marker_files_parsed": self.marker_files_parsed,
            "prompt_step_markers_parsed": self.prompt_step_markers_parsed,
            "index_missing": self.index_missing,
        }


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


def _load_state_with_stats(
    snapshot: AgentArtifactScanWire,
    *,
    tier: Literal["tier1", "tier2"],
    complete_history: bool,
    artifact_source: Literal["artifact_index", "source_scan"],
    used_artifact_index: bool,
    full_history: bool,
    agent_search_active: bool,
    index_error: str | None = None,
    index_missing: bool = False,
) -> AgentLoadState:
    """Build :class:`AgentLoadState` populated with diagnostic snapshot stats."""

    stats = snapshot.stats
    return AgentLoadState(
        tier=tier,
        complete_history=complete_history,
        artifact_source=artifact_source,
        used_artifact_index=used_artifact_index,
        index_error=index_error,
        full_history=full_history,
        agent_search_active=agent_search_active,
        snapshot_records=len(snapshot.records),
        artifact_dirs_visited=stats.artifact_dirs_visited,
        marker_files_parsed=stats.marker_files_parsed,
        prompt_step_markers_parsed=stats.prompt_step_markers_parsed,
        index_missing=index_missing,
    )


def _tui_inbox_query() -> AgentArtifactIndexQueryWire:
    """Return the visibility-aware Tier 1 inbox query for ordinary refreshes.

    Phase 3 of ``sase-3r`` (Fast Agents Tab Disk Loading) replaces the
    bounded "active + 200 recent completed" query with a true inbox view:
    every active/incomplete row plus every completed row whose identity
    is **not** in the dismissed-agent sidecar. Dismissed completions are
    filtered server-side so the TUI no longer scans historical artifact
    directories on every keystroke.
    """

    return AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=False,
        recent_completed_limit=None,
        include_hidden=False,
        include_dismissed=False,
    )


def _query_artifact_index_for_loader(
    *,
    full_history: bool,
    agent_search_active: bool,
) -> tuple[AgentArtifactScanWire, AgentLoadState] | None:
    """Return an index-backed snapshot for the TUI inbox refresh.

    Behavior under Phase 3 of ``sase-3r``:

    - Explicit ``full_history=True`` requests skip the index entirely so
      revive/archive/repair flows still get a complete source scan.
    - Missing index returns an empty snapshot with ``index_missing=True``
      instead of doing a bounded source-tree scan. The apply layer
      schedules a one-off rebuild and the cached working set stays
      visible via the existing watermark merge.
    - Index-query errors fall back to a bounded source scan as before so
      a corrupt sqlite file does not blank the list.
    """

    if full_history:
        return None

    index_path = default_agent_artifact_index_path()
    if not index_path.is_file():
        empty_snapshot = _empty_snapshot_for_missing_index()
        return (
            empty_snapshot,
            _load_state_with_stats(
                empty_snapshot,
                tier="tier1",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=False,
                full_history=False,
                agent_search_active=agent_search_active,
                index_missing=True,
            ),
        )

    query = _tui_inbox_query()
    try:
        snapshot = query_agent_artifact_index(
            index_path,
            _projects_root_for_loader(),
            query=query,
            options=_TUI_SCAN_OPTIONS,
        )
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError) as exc:
        fallback_snapshot = _scan_artifacts_for_loader(_TIER1_FALLBACK_SCAN_OPTIONS)
        return (
            fallback_snapshot,
            _load_state_with_stats(
                fallback_snapshot,
                tier="tier1",
                complete_history=False,
                artifact_source="source_scan",
                used_artifact_index=False,
                index_error=str(exc),
                full_history=False,
                agent_search_active=agent_search_active,
            ),
        )

    return (
        snapshot,
        _load_state_with_stats(
            snapshot,
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
            full_history=False,
            agent_search_active=agent_search_active,
        ),
    )


def _artifact_snapshot_for_tui_load(
    *,
    full_history: bool,
    agent_search_active: bool,
) -> tuple[AgentArtifactScanWire, AgentLoadState]:
    """Return the artifact snapshot for a TUI refresh.

    Tier 1 normal refreshes always go through
    :func:`_query_artifact_index_for_loader`, which returns a
    visibility-aware inbox snapshot when the index is present, an empty
    snapshot when the index is absent (flagging ``index_missing`` so the
    apply layer can rebuild rather than source-scan), or a bounded source
    scan when the index query raises. Tier 2 reconciles from source-of-
    truth artifacts so explicit revive/archive/repair paths still see a
    complete history.
    """

    if full_history:
        snapshot = _scan_artifacts_for_loader()
        return (
            snapshot,
            _load_state_with_stats(
                snapshot,
                tier="tier2",
                complete_history=True,
                artifact_source="source_scan",
                used_artifact_index=False,
                full_history=True,
                agent_search_active=agent_search_active,
            ),
        )

    indexed = _query_artifact_index_for_loader(
        full_history=full_history,
        agent_search_active=agent_search_active,
    )
    assert indexed is not None, (
        "_query_artifact_index_for_loader returns a snapshot for every "
        "non-full-history call after Phase 3 of sase-3r"
    )
    return indexed


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
    # snapshots avoid re-globbing every project spec file when the TUI already
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
    agent_search_active: bool = False,
) -> _AgentLoadResult:
    """Load agents for the TUI and report whether history is complete."""

    artifact_snapshot, state = _artifact_snapshot_for_tui_load(
        full_history=full_history,
        agent_search_active=agent_search_active,
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
    agent_search_active: bool = False,
) -> tuple[list[Agent], AgentLoadState]:
    """Load agents through the TUI tiered artifact path."""

    result = _load_agents_with_load_state(
        changespec_snapshot=changespec_snapshot,
        full_history=full_history,
        agent_search_active=agent_search_active,
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

    sorted_agents = _sort_and_reorder(agents, result.workflow_agent_steps)
    state = replace(
        result.state,
        loaded_agent_count=len(sorted_agents),
        loaded_workflow_step_count=len(result.workflow_agent_steps),
    )
    return sorted_agents, state
