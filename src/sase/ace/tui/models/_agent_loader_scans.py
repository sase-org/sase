"""Artifact scan entry points for the TUI agent loader."""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from sase.core.agent_scan_facade import (
    agent_artifact_list_wire_schema_version,
    default_agent_artifact_index_path,
    query_agent_artifact_index_bounded as query_agent_artifact_index,
    query_agent_artifact_index_list_bounded as query_agent_artifact_index_list,
    scan_agent_artifact_dirs_list,
    scan_agent_artifacts,
    scan_agent_artifacts_list,
)
from sase.core.agent_scan_list_wire import (
    AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION,
    AgentArtifactListSnapshotWire,
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
from ._agent_loader_artifact_index_list import (
    query_artifact_index_for_loader_list as query_artifact_index_list_impl,
)
from ._agent_loader_artifact_snapshots import (
    artifact_snapshot_for_live_plan_load as live_plan_artifact_snapshot,
    artifact_snapshot_for_live_plan_load_list as live_plan_list_artifact_snapshot,
    artifact_snapshot_for_tui_load as tui_artifact_snapshot,
    artifact_snapshot_for_tui_load_list as tui_list_artifact_snapshot,
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


def _require_compact_list_contract() -> None:
    """Fail fast when the installed core predates the compact list contract.

    The TUI cutover always runs against the pinned core, so a mismatch is a
    deployment error, not a fallback case. Raising here (instead of letting
    the first list binding raise ``AttributeError``) names the expected
    schema so the failure points at the stale core install.
    """
    core_version = agent_artifact_list_wire_schema_version()
    if core_version != AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "compact agent list contract mismatch: "
            f"core reports schema {core_version}, "
            f"TUI expects {AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION}"
        )


def scan_artifacts_for_loader_list(
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactListSnapshotWire:
    """Return one fresh compact artifact-tree snapshot for the TUI loader.

    Compact twin of :func:`scan_artifacts_for_loader`: the same selection
    and ordering, but each record carries only list facts so Python never
    builds full marker dataclasses on the list path.
    """
    _require_compact_list_contract()
    return scan_agent_artifacts_list(
        sase_projects_dir(),
        options or TUI_SCAN_OPTIONS,
    )


def scan_artifact_dirs_for_loader_list(
    artifact_dirs: Sequence[Path | str],
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactListSnapshotWire:
    """Return a fresh compact exact artifact-dir snapshot for the TUI loader."""
    _require_compact_list_contract()
    return scan_agent_artifact_dirs_list(
        sase_projects_dir(),
        artifact_dirs,
        options or TUI_SCAN_OPTIONS,
    )


def _query_artifact_index_for_loader_list(
    *,
    full_history: bool,
    freshness: Literal["revalidate", "cached"] = "cached",
    requested_limit: int | None = None,
    candidate_filter: dict[str, object] | None = None,
    allow_lock_busy_source_scan: bool = True,
) -> tuple[AgentArtifactListSnapshotWire, AgentLoadState] | None:
    """Return a compact index-backed snapshot when the persistent index exists."""
    _require_compact_list_contract()
    return query_artifact_index_list_impl(
        full_history=full_history,
        freshness=freshness,
        requested_limit=requested_limit,
        candidate_filter=candidate_filter,
        default_index_path=default_agent_artifact_index_path,
        projects_root=_projects_root_for_loader,
        query_index=query_agent_artifact_index_list,
        scan_artifacts=scan_artifacts_for_loader_list,
        allow_lock_busy_source_scan=allow_lock_busy_source_scan,
    )


def artifact_snapshot_for_tui_load_list(
    *,
    full_history: bool,
    use_artifact_index: bool = True,
    index_freshness: Literal["revalidate", "cached"] = "cached",
    requested_limit: int | None = None,
    candidate_filter: dict[str, object] | None = None,
    allow_lock_busy_source_scan: bool = True,
) -> tuple[AgentArtifactListSnapshotWire, AgentLoadState]:
    """Return the compact artifact snapshot for a TUI refresh.

    Compact twin of :func:`artifact_snapshot_for_tui_load` with identical
    tier, fallback, and load-state semantics over list projections.
    """
    return tui_list_artifact_snapshot(
        full_history=full_history,
        use_artifact_index=use_artifact_index,
        index_freshness=index_freshness,
        requested_limit=requested_limit,
        candidate_filter=candidate_filter,
        scan_artifacts=scan_artifacts_for_loader_list,
        load_tier1_index=_query_artifact_index_for_loader_list,
        allow_lock_busy_source_scan=allow_lock_busy_source_scan,
    )


def artifact_snapshot_for_live_plan_load_list() -> AgentArtifactListSnapshotWire:
    """Return a bounded compact snapshot for CLI plan notification matching."""
    _require_compact_list_contract()
    return live_plan_list_artifact_snapshot(
        default_index_path=default_agent_artifact_index_path,
        projects_root=_projects_root_for_loader,
        query_index=query_agent_artifact_index_list,
        scan_artifacts=scan_artifacts_for_loader_list,
    )
