"""Artifact scan entry points for the TUI agent loader."""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index_bounded as query_agent_artifact_index,
    scan_agent_artifact_dirs,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import (
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.paths import sase_projects_dir

from ._agent_loader_artifact_config import TUI_SCAN_OPTIONS
from ._agent_loader_artifact_index import (
    query_artifact_index_for_loader as query_artifact_index_impl,
)
from ._agent_loader_artifact_snapshots import (
    artifact_snapshot_for_live_plan_load as live_plan_artifact_snapshot,
    artifact_snapshot_for_tui_load as tui_artifact_snapshot,
)
from ._agent_loader_artifact_state import AgentLoadState


def scan_artifacts_for_loader(
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Return one fresh artifact-tree snapshot for the TUI loader.

    Single-purpose seam between the snapshot selectors below and
    :func:`scan_agent_artifacts` so tests can replace the snapshot with a
    fixture without having to patch every individual ``_from_snapshot``
    consumer.
    """
    return scan_agent_artifacts(
        sase_projects_dir(),
        options or TUI_SCAN_OPTIONS,
    )


def scan_artifact_dirs_for_loader(
    artifact_dirs: Sequence[Path | str],
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Return a fresh exact artifact-dir snapshot for the TUI loader."""
    return scan_agent_artifact_dirs(
        sase_projects_dir(),
        artifact_dirs,
        options or TUI_SCAN_OPTIONS,
    )


def _projects_root_for_loader() -> Path:
    return sase_projects_dir()


def _query_artifact_index_for_loader(
    *,
    full_history: bool,
    freshness: Literal["revalidate", "cached"] = "cached",
    requested_limit: int | None = None,
    candidate_filter: dict[str, object] | None = None,
    allow_lock_busy_source_scan: bool = True,
) -> tuple[AgentArtifactScanWire, AgentLoadState] | None:
    """Return an index-backed snapshot when the persistent index exists."""
    return query_artifact_index_impl(
        full_history=full_history,
        freshness=freshness,
        requested_limit=requested_limit,
        candidate_filter=candidate_filter,
        default_index_path=default_agent_artifact_index_path,
        projects_root=_projects_root_for_loader,
        query_index=query_agent_artifact_index,
        scan_artifacts=scan_artifacts_for_loader,
        allow_lock_busy_source_scan=allow_lock_busy_source_scan,
    )


def artifact_snapshot_for_tui_load(
    *,
    full_history: bool,
    use_artifact_index: bool = True,
    index_freshness: Literal["revalidate", "cached"] = "cached",
    requested_limit: int | None = None,
    candidate_filter: dict[str, object] | None = None,
    allow_lock_busy_source_scan: bool = True,
) -> tuple[AgentArtifactScanWire, AgentLoadState]:
    """Return the artifact snapshot for a TUI refresh.

    Tier 1 uses the persistent artifact index when available. Missing or bad
    indexes fall back to a bounded source scan so first paint remains capped.
    A busy index lock serves the last same-key snapshot or keeps the roster.
    Tier 2 uses a revalidated index query and falls back to source artifacts when the
    index path is unavailable.
    """
    return tui_artifact_snapshot(
        full_history=full_history,
        use_artifact_index=use_artifact_index,
        index_freshness=index_freshness,
        requested_limit=requested_limit,
        candidate_filter=candidate_filter,
        scan_artifacts=scan_artifacts_for_loader,
        load_tier1_index=_query_artifact_index_for_loader,
        allow_lock_busy_source_scan=allow_lock_busy_source_scan,
    )


def artifact_snapshot_for_live_plan_load() -> AgentArtifactScanWire:
    """Return a bounded artifact snapshot for CLI plan notification matching."""
    return live_plan_artifact_snapshot(
        default_index_path=default_agent_artifact_index_path,
        projects_root=_projects_root_for_loader,
        query_index=query_agent_artifact_index,
        scan_artifacts=scan_artifacts_for_loader,
    )
