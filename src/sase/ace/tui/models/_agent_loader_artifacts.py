"""Artifact snapshot selection and path helpers for the agent loader."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Protocol

from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.paths import sase_projects_dir

from ._timestamps import normalize_to_14_digit


_TUI_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=True,
    # The TUI reads prompt-step markers (workflow agent steps + meta_*
    # propagation) but does not render the raw_xprompt.md snippet; skip
    # the snippet read to keep the scan compact.
    include_raw_prompt_snippets=False,
)

_TIER1_RECENT_COMPLETED_LIMIT = 200
_TIER1_ACTIVE_LIMIT = 1000
_TIER1_FALLBACK_SCAN_OPTIONS = replace(
    _TUI_SCAN_OPTIONS,
    max_records=_TIER1_RECENT_COMPLETED_LIMIT,
    newest_first=True,
)
_PLAN_LIVE_SCAN_OPTIONS = replace(
    _TUI_SCAN_OPTIONS,
    include_prompt_step_markers=False,
)
_PLAN_LIVE_FALLBACK_SCAN_OPTIONS = replace(
    _PLAN_LIVE_SCAN_OPTIONS,
    max_records=_TIER1_RECENT_COMPLETED_LIMIT,
    newest_first=True,
)


@dataclass(frozen=True)
class AgentLoadState:
    """Artifact-history completeness for one TUI agent load."""

    tier: Literal["tier1", "tier2"]
    complete_history: bool
    artifact_source: Literal["artifact_index", "source_scan", "artifact_delta"]
    used_artifact_index: bool
    index_error: str | None = None
    complete_visible_inbox: bool = True
    repair_recommended: bool = False
    repair_reason: str | None = None
    truncated: bool = False
    deleted_artifact_dirs: frozenset[str] = field(default_factory=frozenset)
    record_count: int | None = None

    @property
    def needs_full_history_reconcile(self) -> bool:
        """Return whether the caller should schedule a Tier 2 refresh."""

        return (
            not self.complete_visible_inbox or self.repair_recommended or self.truncated
        )


class _ArtifactScanner(Protocol):
    def __call__(
        self,
        options: AgentArtifactScanOptionsWire | None = None,
    ) -> AgentArtifactScanWire: ...


class _ArtifactIndexQuery(Protocol):
    def __call__(
        self,
        index_path: Path,
        projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire: ...


class _Tier1IndexLoader(Protocol):
    def __call__(
        self,
        *,
        full_history: bool,
        freshness: Literal["revalidate", "cached"] = "cached",
    ) -> tuple[AgentArtifactScanWire, AgentLoadState] | None: ...


def query_artifact_index_for_loader(
    *,
    full_history: bool,
    freshness: Literal["revalidate", "cached"] = "cached",
    default_index_path: Callable[[], Path],
    projects_root: Callable[[], Path],
    query_index: _ArtifactIndexQuery,
    scan_artifacts: _ArtifactScanner,
) -> tuple[AgentArtifactScanWire, AgentLoadState] | None:
    """Return an index-backed snapshot when the persistent index exists."""

    if full_history:
        return None

    index_path = default_index_path()
    if not index_path.is_file():
        return None

    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=False,
        active_limit=_TIER1_ACTIVE_LIMIT,
        recent_completed_limit=_TIER1_RECENT_COMPLETED_LIMIT,
        include_hidden=False,
        freshness=freshness,
        record_shape="list",
    )
    try:
        snapshot = query_index(
            index_path,
            projects_root(),
            query=query,
            options=_TUI_SCAN_OPTIONS,
        )
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError) as exc:
        fallback_snapshot = scan_artifacts(_TIER1_FALLBACK_SCAN_OPTIONS)
        return (
            fallback_snapshot,
            AgentLoadState(
                tier="tier1",
                complete_history=False,
                complete_visible_inbox=False,
                artifact_source="source_scan",
                used_artifact_index=False,
                index_error=str(exc),
                repair_recommended=True,
                repair_reason="artifact_index_query_failed_bounded_fallback",
                record_count=len(fallback_snapshot.records),
            ),
        )

    return (
        snapshot,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=True,
            artifact_source="artifact_index",
            used_artifact_index=True,
            record_count=len(snapshot.records),
        ),
    )


def artifact_snapshot_for_tui_load(
    *,
    full_history: bool,
    use_artifact_index: bool,
    index_freshness: Literal["revalidate", "cached"] = "cached",
    scan_artifacts: _ArtifactScanner,
    load_tier1_index: _Tier1IndexLoader,
) -> tuple[AgentArtifactScanWire, AgentLoadState]:
    """Return the artifact snapshot for a TUI refresh."""

    if full_history:
        full_snapshot = scan_artifacts()
        return (
            full_snapshot,
            AgentLoadState(
                tier="tier2",
                complete_history=True,
                complete_visible_inbox=True,
                artifact_source="source_scan",
                used_artifact_index=False,
                record_count=len(full_snapshot.records),
            ),
        )

    if not use_artifact_index:
        unindexed_snapshot = scan_artifacts(_TIER1_FALLBACK_SCAN_OPTIONS)
        return (
            unindexed_snapshot,
            AgentLoadState(
                tier="tier1",
                complete_history=False,
                complete_visible_inbox=False,
                artifact_source="source_scan",
                used_artifact_index=False,
                record_count=len(unindexed_snapshot.records),
            ),
        )

    indexed = load_tier1_index(
        full_history=full_history,
        freshness=index_freshness,
    )
    if indexed is not None:
        return indexed

    fallback_snapshot = scan_artifacts(_TIER1_FALLBACK_SCAN_OPTIONS)
    return (
        fallback_snapshot,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=False,
            artifact_source="source_scan",
            used_artifact_index=False,
            repair_recommended=True,
            repair_reason="artifact_index_missing_bounded_fallback",
            record_count=len(fallback_snapshot.records),
        ),
    )


def artifact_snapshot_for_live_plan_load(
    *,
    default_index_path: Callable[[], Path],
    projects_root: Callable[[], Path],
    query_index: _ArtifactIndexQuery,
    scan_artifacts: _ArtifactScanner,
) -> AgentArtifactScanWire:
    """Return a bounded artifact snapshot for CLI plan notification matching."""

    index_path = default_index_path()
    if index_path.is_file():
        query = AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=True,
            include_full_history=False,
            active_limit=None,
            recent_completed_limit=_TIER1_RECENT_COMPLETED_LIMIT,
            include_hidden=False,
        )
        try:
            return query_index(
                index_path,
                projects_root(),
                query=query,
                options=_PLAN_LIVE_SCAN_OPTIONS,
            )
        except (ImportError, AttributeError, OSError, ValueError, RuntimeError):
            pass

    return scan_artifacts(_PLAN_LIVE_FALLBACK_SCAN_OPTIONS)


def normalize_timestamps(timestamps: Iterable[str]) -> set[str]:
    normalized: set[str] = set()
    for value in timestamps:
        timestamp = normalize_to_14_digit(str(value).strip())
        if timestamp:
            normalized.add(timestamp)
    return normalized


def artifact_dirs_for_normalized_timestamps(normalized: set[str]) -> list[Path]:
    if not normalized:
        return []

    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return []

    artifact_dirs: list[Path] = []
    for project_dir in projects_dir.iterdir():
        artifacts_dir = project_dir / "artifacts"
        if not artifacts_dir.is_dir():
            continue
        for workflow_dir in artifacts_dir.iterdir():
            if not workflow_dir.is_dir():
                continue
            for timestamp in normalized:
                candidate = resolve_agent_artifact_timestamp_path(
                    project_dir.name,
                    workflow_dir.name,
                    timestamp,
                    projects_root=projects_dir,
                )
                if candidate.is_dir():
                    artifact_dirs.append(candidate)
    return artifact_dirs


def prepare_artifact_delta_paths(
    artifact_dirs: Sequence[Path | str],
    deleted_artifact_dirs: Sequence[Path | str],
) -> tuple[list[Path], set[str], set[str]]:
    """Normalize and deduplicate exact artifact-delta paths."""

    unique_dirs: list[Path] = []
    seen_dirs: set[str] = set()
    for artifact_dir in artifact_dirs:
        path = Path(artifact_dir).expanduser()
        key = str(path)
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        unique_dirs.append(path)
    deleted_dir_keys = {
        str(Path(artifact_dir).expanduser()) for artifact_dir in deleted_artifact_dirs
    }
    return unique_dirs, seen_dirs, deleted_dir_keys


def update_artifact_index_from_delta(
    snapshot: AgentArtifactScanWire,
    *,
    update_index: bool,
) -> None:
    """Add records from an exact artifact delta to the persistent index."""

    if not update_index or not snapshot.records:
        return

    from sase.core.agent_artifact_index_lifecycle import (
        upsert_agent_artifact_index_artifacts,
    )

    upsert_agent_artifact_index_artifacts(
        record.artifact_dir for record in snapshot.records
    )


def artifact_delta_load_state(
    snapshot: AgentArtifactScanWire,
    *,
    seen_dirs: set[str],
    deleted_dir_keys: set[str],
) -> AgentLoadState:
    """Describe completeness after scanning an exact artifact delta."""

    scanned_dirs = {
        str(Path(record.artifact_dir).expanduser()) for record in snapshot.records
    }
    unexpected_missing_dirs = (seen_dirs - scanned_dirs) - deleted_dir_keys
    repair_recommended = bool(unexpected_missing_dirs)
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_delta",
        used_artifact_index=False,
        complete_visible_inbox=True,
        repair_recommended=repair_recommended,
        repair_reason="artifact_delta_scan_incomplete" if repair_recommended else None,
        deleted_artifact_dirs=frozenset(deleted_dir_keys & seen_dirs),
        record_count=len(snapshot.records),
    )
