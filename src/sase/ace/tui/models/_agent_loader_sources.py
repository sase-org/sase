"""Assemble agent rows from every loader source for the TUI agent loader."""

from sase.core.agent_scan_list_wire import AgentArtifactListSnapshotWire
from sase.core.agent_scan_wire import AgentArtifactScanWire
from sase.macro.project_identity import project_identity_load_scope

from ...patch import Patch, find_all_patches
from ._agent_loader_normalization import apply_snapshot_clan_context
from ._agent_loader_scans import (
    scan_artifacts_for_loader,
    scan_artifacts_for_loader_list,
)
from ._loader_memos import agent_loader_memos
from ._loaders import (
    get_all_project_files,
    load_agents_from_comments,
    load_agents_from_hooks,
    load_agents_from_mentors,
    load_agents_from_running_field,
    load_done_agents_from_snapshot,
    load_running_home_agents_from_snapshot,
    load_workflow_agent_steps_from_snapshot,
    load_workflow_agents_from_snapshot,
)
from ._loaders._compact_done_loaders import load_done_agents_from_compact_snapshot
from ._loaders._compact_running_loaders import (
    load_running_home_agents_from_compact_snapshot,
)
from ._loaders._compact_workflow_loaders import (
    load_compact_workflow_agent_steps_from_snapshot,
    load_compact_workflow_agents_from_snapshot,
)
from .agent import Agent


def _patch_snapshot_for_loader(
    patch_snapshot: list[Patch] | None,
) -> list[Patch]:
    return (
        patch_snapshot
        if patch_snapshot is not None
        else find_all_patches(include_states="all")
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


def load_agents_from_compact_snapshot_sources(
    artifact_snapshot: AgentArtifactListSnapshotWire,
    *,
    patch_snapshot: list[Patch] | None = None,
) -> tuple[list[Agent], list[Agent]]:
    with agent_loader_memos(), project_identity_load_scope():
        return _load_agents_from_compact_snapshot_sources_impl(
            artifact_snapshot,
            patch_snapshot=patch_snapshot,
        )


def _load_agents_from_compact_snapshot_sources_impl(
    artifact_snapshot: AgentArtifactListSnapshotWire,
    *,
    patch_snapshot: list[Patch] | None = None,
) -> tuple[list[Agent], list[Agent]]:
    """Load only artifact-backed agents from one compact list snapshot.

    Compact twin of
    :func:`_load_agents_from_artifact_snapshot_sources_impl`: every row is
    constructed directly from list facts, so no full marker record crosses
    this path. ``RUNNING``-field claims and Patch-field rows are callers'
    responsibility (see :func:`load_compact_agents_from_all_sources`).
    """
    all_patches = _patch_snapshot_for_loader(patch_snapshot)
    bug_by_cl_name, cl_by_cl_name = _patch_agent_lookups(all_patches)

    agents: list[Agent] = []
    agents.extend(
        load_done_agents_from_compact_snapshot(
            artifact_snapshot, bug_by_cl_name, cl_by_cl_name
        )
    )
    agents.extend(load_running_home_agents_from_compact_snapshot(artifact_snapshot))
    workflow_agent_steps, step_meta_by_parent = (
        load_compact_workflow_agent_steps_from_snapshot(artifact_snapshot)
    )
    agents.extend(
        load_compact_workflow_agents_from_snapshot(
            artifact_snapshot,
            step_meta_by_parent=step_meta_by_parent,
        )
    )
    apply_snapshot_clan_context(
        [*agents, *workflow_agent_steps],
        artifact_snapshot,
    )
    return agents, workflow_agent_steps


def load_plan_agents_from_compact_snapshot(
    artifact_snapshot: AgentArtifactListSnapshotWire,
) -> list[Agent]:
    """Load compact artifact-backed rows for plan notification liveness."""

    agents: list[Agent] = []
    agents.extend(load_done_agents_from_compact_snapshot(artifact_snapshot, {}, {}))
    agents.extend(load_running_home_agents_from_compact_snapshot(artifact_snapshot))
    agents.extend(
        load_compact_workflow_agents_from_snapshot(
            artifact_snapshot,
            step_meta_by_parent=None,
        )
    )
    return agents


def load_agents_from_all_sources(
    *,
    patch_snapshot: list[Patch] | None = None,
    artifact_snapshot: AgentArtifactScanWire | None = None,
) -> tuple[list[Agent], list[Agent]]:
    with agent_loader_memos(), project_identity_load_scope():
        return _load_agents_from_all_sources_impl(
            patch_snapshot=patch_snapshot,
            artifact_snapshot=artifact_snapshot,
        )


def _load_agents_from_all_sources_impl(
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
        artifact_snapshot = scan_artifacts_for_loader()

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

    apply_snapshot_clan_context(
        [*agents, *workflow_agent_steps],
        artifact_snapshot,
    )
    return agents, workflow_agent_steps


def load_compact_agents_from_all_sources(
    *,
    patch_snapshot: list[Patch] | None = None,
    artifact_snapshot: AgentArtifactListSnapshotWire | None = None,
) -> tuple[list[Agent], list[Agent]]:
    with agent_loader_memos(), project_identity_load_scope():
        return _load_compact_agents_from_all_sources_impl(
            patch_snapshot=patch_snapshot,
            artifact_snapshot=artifact_snapshot,
        )


def _load_compact_agents_from_all_sources_impl(
    *,
    patch_snapshot: list[Patch] | None = None,
    artifact_snapshot: AgentArtifactListSnapshotWire | None = None,
) -> tuple[list[Agent], list[Agent]]:
    """Load agents from all sources with compact artifact rows.

    Compact twin of :func:`_load_agents_from_all_sources_impl`.
    ``RUNNING``-field workspace claims keep their existing filesystem path;
    only the artifact-tree consumers move to the compact projection.
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

    # Acquire a single compact artifact snapshot for every artifact-tree
    # consumer below so the filesystem (and the Rust projection) only pays
    # the walking + JSON parsing cost once per refresh.
    if artifact_snapshot is None:
        artifact_snapshot = scan_artifacts_for_loader_list()

    # 1a. Load completed (DONE) agents from compact list facts.
    agents.extend(
        load_done_agents_from_compact_snapshot(
            artifact_snapshot, bug_by_cl_name, cl_by_cl_name
        )
    )

    # 1b. Load running home mode agents from compact list facts.
    agents.extend(load_running_home_agents_from_compact_snapshot(artifact_snapshot))

    # 1d. Load workflow agent steps first — also collects meta_* fields
    # per parent timestamp so workflow parents skip redundant enrichment.
    workflow_agent_steps, step_meta_by_parent = (
        load_compact_workflow_agent_steps_from_snapshot(artifact_snapshot)
    )

    # 1c. Load workflow entries as agents (with pre-collected meta fields).
    agents.extend(
        load_compact_workflow_agents_from_snapshot(
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

    apply_snapshot_clan_context(
        [*agents, *workflow_agent_steps],
        artifact_snapshot,
    )
    return agents, workflow_agent_steps
