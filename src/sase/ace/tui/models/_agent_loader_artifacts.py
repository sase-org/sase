"""Artifact snapshot selection for TUI agent loading."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import time
from typing import Literal

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)

from ._agent_loader_state import AgentLoadState
from .agent import Agent

_TUI_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=True,
    # The TUI reads prompt-step markers (workflow agent steps + meta_*
    # propagation) but does not render the raw_xprompt.md snippet; skip
    # the snippet read to keep the scan compact.
    include_raw_prompt_snippets=False,
)
_TIER1_INDEX_SCAN_OPTIONS = replace(
    _TUI_SCAN_OPTIONS,
    include_prompt_step_markers=False,
)

_TIER1_RECENT_COMPLETED_LIMIT = 200
_TIER1_FALLBACK_SCAN_OPTIONS = replace(
    _TUI_SCAN_OPTIONS,
    max_records=_TIER1_RECENT_COMPLETED_LIMIT,
    newest_first=True,
)


def projects_root_for_loader() -> Path:
    return Path.home() / ".sase" / "projects"


def scan_artifacts_for_loader(
    scan_agent_artifacts_fn: Callable[
        [Path, AgentArtifactScanOptionsWire], AgentArtifactScanWire
    ],
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Return one fresh artifact-tree snapshot for the TUI loader."""

    return scan_agent_artifacts_fn(
        Path.home() / ".sase" / "projects",
        options or _TUI_SCAN_OPTIONS,
    )


def empty_snapshot_for_missing_index(
    projects_root_for_loader_fn: Callable[[], Path],
) -> AgentArtifactScanWire:
    """Build a deterministic empty snapshot for the missing-index Tier 1 path."""

    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(projects_root_for_loader_fn()),
        options=_TUI_SCAN_OPTIONS,
        stats=AgentArtifactScanStatsWire(),
        records=[],
    )


def load_state_with_stats(
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
    index_query_ms: float | None = None,
    source_scan_ms: float | None = None,
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
        index_query_ms=index_query_ms,
        source_scan_ms=source_scan_ms,
        index_row_count=(
            len(snapshot.records) if artifact_source == "artifact_index" else None
        ),
        source_row_count=(
            len(snapshot.records) if artifact_source == "source_scan" else None
        ),
        index_missing=index_missing,
    )


def tui_inbox_query() -> AgentArtifactIndexQueryWire:
    """Return the visibility-aware Tier 1 inbox query for ordinary refreshes."""

    return AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=False,
        recent_completed_limit=None,
        include_hidden=False,
        include_dismissed=False,
    )


def query_artifact_index_for_loader(
    *,
    full_history: bool,
    agent_search_active: bool,
    default_agent_artifact_index_path_fn: Callable[[], Path],
    query_agent_artifact_index_fn: Callable[..., AgentArtifactScanWire],
    scan_artifacts_for_loader_fn: Callable[
        [AgentArtifactScanOptionsWire | None], AgentArtifactScanWire
    ],
    projects_root_for_loader_fn: Callable[[], Path],
    empty_snapshot_for_missing_index_fn: Callable[[], AgentArtifactScanWire],
    tui_inbox_query_fn: Callable[[], AgentArtifactIndexQueryWire],
) -> tuple[AgentArtifactScanWire, AgentLoadState] | None:
    """Return an index-backed snapshot for the TUI inbox refresh."""

    if full_history:
        return None

    index_path = default_agent_artifact_index_path_fn()
    if not index_path.is_file():
        empty_snapshot = empty_snapshot_for_missing_index_fn()
        return (
            empty_snapshot,
            load_state_with_stats(
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

    from sase.core.agent_artifact_index_maintenance import (
        maybe_sync_dismissed_from_file,
    )

    maybe_sync_dismissed_from_file(index_path=index_path)

    query = tui_inbox_query_fn()
    try:
        from ..util.trace import tui_trace

        started = time.perf_counter()
        with tui_trace("agents.index_query") as trace_fields:
            snapshot = query_agent_artifact_index_fn(
                index_path,
                projects_root_for_loader_fn(),
                query=query,
                options=_TIER1_INDEX_SCAN_OPTIONS,
            )
            trace_fields["index_row_count"] = len(snapshot.records)
            trace_fields["prompt_step_markers_parsed"] = (
                snapshot.stats.prompt_step_markers_parsed
            )
        index_query_ms = (time.perf_counter() - started) * 1000.0
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError) as exc:
        started = time.perf_counter()
        fallback_snapshot = scan_artifacts_for_loader_fn(_TIER1_FALLBACK_SCAN_OPTIONS)
        source_scan_ms = (time.perf_counter() - started) * 1000.0
        return (
            fallback_snapshot,
            load_state_with_stats(
                fallback_snapshot,
                tier="tier1",
                complete_history=False,
                artifact_source="source_scan",
                used_artifact_index=False,
                index_error=str(exc),
                full_history=False,
                agent_search_active=agent_search_active,
                source_scan_ms=source_scan_ms,
            ),
        )

    return (
        snapshot,
        load_state_with_stats(
            snapshot,
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
            full_history=False,
            agent_search_active=agent_search_active,
            index_query_ms=index_query_ms,
        ),
    )


def artifact_snapshot_for_tui_load(
    *,
    full_history: bool,
    agent_search_active: bool,
    scan_artifacts_for_loader_fn: Callable[
        [AgentArtifactScanOptionsWire | None], AgentArtifactScanWire
    ],
    query_artifact_index_for_loader_fn: Callable[
        [bool, bool],
        tuple[AgentArtifactScanWire, AgentLoadState] | None,
    ],
) -> tuple[AgentArtifactScanWire, AgentLoadState]:
    """Return the artifact snapshot for a TUI refresh."""

    if full_history:
        from ..util.trace import tui_trace

        started = time.perf_counter()
        with tui_trace("agents.source_scan") as trace_fields:
            snapshot = scan_artifacts_for_loader_fn(None)
            trace_fields["source_row_count"] = len(snapshot.records)
            trace_fields["prompt_step_markers_parsed"] = (
                snapshot.stats.prompt_step_markers_parsed
            )
        source_scan_ms = (time.perf_counter() - started) * 1000.0
        return (
            snapshot,
            load_state_with_stats(
                snapshot,
                tier="tier2",
                complete_history=True,
                artifact_source="source_scan",
                used_artifact_index=False,
                full_history=True,
                agent_search_active=agent_search_active,
                source_scan_ms=source_scan_ms,
            ),
        )

    indexed = query_artifact_index_for_loader_fn(full_history, agent_search_active)
    assert indexed is not None, (
        "query_artifact_index_for_loader returns a snapshot for every "
        "non-full-history call after Phase 3 of sase-3r"
    )
    return indexed


def load_workflow_children_for_parent(
    parent: Agent,
    *,
    default_agent_artifact_index_path_fn: Callable[[], Path],
    query_agent_artifact_index_fn: Callable[..., AgentArtifactScanWire],
    projects_root_for_loader_fn: Callable[[], Path],
    load_workflow_agent_steps_from_snapshot_fn: Callable[
        [AgentArtifactScanWire], tuple[list[Agent], dict[str, dict[str, str]]]
    ],
) -> list[Agent]:
    """Load prompt-step child rows for one workflow parent from the index."""

    parent_timestamp = parent.raw_suffix
    if not parent_timestamp:
        return []

    index_path = default_agent_artifact_index_path_fn()
    if not index_path.is_file():
        return []

    query = AgentArtifactIndexQueryWire(
        include_active=False,
        include_recent_completed=False,
        include_full_history=False,
        recent_completed_limit=None,
        include_hidden=True,
        include_dismissed=True,
        parent_timestamps=(parent_timestamp,),
    )
    try:
        snapshot = query_agent_artifact_index_fn(
            index_path,
            projects_root_for_loader_fn(),
            query=query,
            options=_TUI_SCAN_OPTIONS,
        )
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError):
        return []
    children, _ = load_workflow_agent_steps_from_snapshot_fn(snapshot)
    return children
