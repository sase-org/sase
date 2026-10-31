"""Persistent artifact-index query path for the TUI agent loader."""

from collections.abc import Callable
from dataclasses import asdict, replace
import json
from pathlib import Path
from typing import Literal

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)

from . import _agent_loader_artifact_config as config
from ._agent_loader_artifact_cache import (
    ARTIFACT_SNAPSHOT_CACHE,
    ArtifactIndexSignature,
    ArtifactSnapshotCacheKey,
)
from ._agent_loader_artifact_state import (
    LOCK_BUSY_BOUNDED_FALLBACK_REASON,
    LOCK_BUSY_KEEP_ROSTER_REASON,
    LOCK_BUSY_SERVED_CACHED_REASON,
    AgentLoadState,
    ArtifactIndexQuery,
    ArtifactScanner,
)


_INDEX_LOCK_BUSY_ERROR = "artifact index operation lock busy"
_IndexFileStat = tuple[str, int | None, int | None]


def _stat_index_file(path: Path) -> _IndexFileStat:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _artifact_index_signature(index_path: Path) -> ArtifactIndexSignature:
    """Return the main database and WAL file signatures."""

    return (
        _stat_index_file(index_path),
        _stat_index_file(index_path.with_name(f"{index_path.name}-wal")),
    )


def _json_key(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _artifact_snapshot_cache_key(
    *,
    index_path: Path,
    projects_root: Path,
    query: AgentArtifactIndexQueryWire,
    options: AgentArtifactScanOptionsWire,
) -> ArtifactSnapshotCacheKey:
    """Build a stable cache key from the index query inputs."""

    return (
        str(index_path),
        str(projects_root),
        _json_key(asdict(query)),
        _json_key(asdict(options)),
    )


def _empty_loader_snapshot(projects_root: Path) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(projects_root),
        options=config.TUI_SCAN_OPTIONS,
        stats=AgentArtifactScanStatsWire(),
        records=[],
    )


def _lock_busy_keep_roster_result(
    *,
    full_history: bool,
    projects_root: Path,
) -> tuple[AgentArtifactScanWire, AgentLoadState]:
    return (
        _empty_loader_snapshot(projects_root),
        AgentLoadState(
            tier="tier2" if full_history else "tier1",
            complete_history=False,
            complete_visible_inbox=False,
            artifact_source="artifact_index",
            used_artifact_index=False,
            index_error=_INDEX_LOCK_BUSY_ERROR,
            repair_recommended=False,
            repair_reason=LOCK_BUSY_KEEP_ROSTER_REASON,
            record_count=0,
        ),
    )


def _lock_busy_loader_result(
    *,
    full_history: bool,
    cache_key: ArtifactSnapshotCacheKey | None,
    scan_artifacts: ArtifactScanner,
    allow_lock_busy_source_scan: bool,
    projects_root: Path,
) -> tuple[AgentArtifactScanWire, AgentLoadState]:
    """Answer a busy index lock from cache or by keeping the current roster."""

    if not full_history and cache_key is not None:
        stale = ARTIFACT_SNAPSHOT_CACHE.get_stale(cache_key)
        if stale is not None:
            snapshot, cached_state = stale
            return (
                snapshot,
                replace(
                    cached_state,
                    complete_history=False,
                    complete_visible_inbox=False,
                    artifact_source="artifact_index",
                    used_artifact_index=True,
                    index_error=_INDEX_LOCK_BUSY_ERROR,
                    repair_recommended=False,
                    repair_reason=LOCK_BUSY_SERVED_CACHED_REASON,
                ),
            )
    if full_history or not allow_lock_busy_source_scan:
        return _lock_busy_keep_roster_result(
            full_history=full_history,
            projects_root=projects_root,
        )
    fallback_snapshot = scan_artifacts(config.TIER1_FALLBACK_SCAN_OPTIONS)
    return (
        fallback_snapshot,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=False,
            artifact_source="source_scan",
            used_artifact_index=False,
            index_error=_INDEX_LOCK_BUSY_ERROR,
            repair_recommended=False,
            repair_reason=LOCK_BUSY_BOUNDED_FALLBACK_REASON,
            record_count=len(fallback_snapshot.records),
        ),
    )


def query_artifact_index_for_loader(
    *,
    full_history: bool,
    freshness: Literal["revalidate", "cached"] = "cached",
    requested_limit: int | None = None,
    candidate_filter: dict[str, object] | None = None,
    default_index_path: Callable[[], Path],
    projects_root: Callable[[], Path],
    query_index: ArtifactIndexQuery,
    scan_artifacts: ArtifactScanner,
    allow_lock_busy_source_scan: bool = True,
) -> tuple[AgentArtifactScanWire, AgentLoadState] | None:
    """Return an index-backed snapshot when the persistent index exists."""

    index_path = default_index_path()
    if not index_path.is_file():
        if not full_history:
            return None
        fallback_snapshot = scan_artifacts()
        return (
            fallback_snapshot,
            AgentLoadState(
                tier="tier2",
                complete_history=True,
                complete_visible_inbox=True,
                artifact_source="source_scan",
                used_artifact_index=False,
                repair_recommended=True,
                repair_reason="artifact_index_missing_full_history_fallback",
                record_count=len(fallback_snapshot.records),
            ),
        )

    active_limit = None if full_history else config.TIER1_ACTIVE_LIMIT
    recent_completed_limit = (
        None if full_history else config.TIER1_VISIBLE_COMPLETED_LIMIT
    )
    # A baseline read (Tier 1 cached read with no viewport window) must still
    # report truncation, so it is sent as a windowed query with the visible
    # safety-valve cap. Windowed mode requires cached freshness, so
    # revalidate reads stay unwindowed with the same cap.
    is_baseline_read = (
        not full_history and freshness == "cached" and requested_limit is None
    )
    window_limit = (
        None
        if full_history
        else (
            config.TIER1_VISIBLE_COMPLETED_LIMIT
            if is_baseline_read
            else requested_limit
        )
    )
    # A Tier-2 load sets the app's complete-history latch. Completeness is a
    # Rust-owned claim: revalidate runs source-directory discovery (new and
    # deleted dirs) plus bounded marker repair. Marker revalidation does not
    # discover previously unindexed directories, so this must not treat
    # ``include_full_history`` itself as proof the archive is complete.
    query_freshness: Literal["revalidate", "cached"] = (
        "revalidate" if full_history else freshness
    )

    query = AgentArtifactIndexQueryWire(
        include_active=not full_history,
        include_recent_completed=not full_history,
        include_full_history=full_history,
        # The viewport window narrows the Tier 1 tiers; it never replaces
        # their caps. The core only honors ``window_limit`` on cached reads
        # (``should_use_windowed_candidate_query``), so nulling the caps here
        # left every ``revalidate`` refresh completely unbounded: it selected
        # and stale-repaired every visible index row instead of the capped
        # tiers, which is both far more rows than Tier 1 promises and slow
        # enough to stall the TUI.
        active_limit=active_limit,
        recent_completed_limit=recent_completed_limit,
        include_hidden=False,
        freshness=query_freshness,
        record_shape="list",
        window_limit=window_limit,
        candidate_filter=candidate_filter,
        agents_list_projection=True,
    )
    root = projects_root()
    cacheable = not full_history and query_freshness == "cached"
    cache_key: ArtifactSnapshotCacheKey | None = None
    before_signature: ArtifactIndexSignature | None = None
    if cacheable:
        before_signature = _artifact_index_signature(index_path)
        cache_key = _artifact_snapshot_cache_key(
            index_path=index_path,
            projects_root=root,
            query=query,
            options=config.TUI_SCAN_OPTIONS,
        )
        cached = ARTIFACT_SNAPSHOT_CACHE.get(cache_key, before_signature)
        if cached is not None:
            return cached
    else:
        ARTIFACT_SNAPSHOT_CACHE.record_bypass()

    try:
        snapshot = query_index(
            index_path,
            root,
            query=query,
            options=config.TUI_SCAN_OPTIONS,
        )
        if snapshot is None:
            return _lock_busy_loader_result(
                full_history=full_history,
                cache_key=cache_key,
                scan_artifacts=scan_artifacts,
                allow_lock_busy_source_scan=allow_lock_busy_source_scan,
                projects_root=root,
            )
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError) as exc:
        fallback_snapshot = scan_artifacts(
            None if full_history else config.TIER1_FALLBACK_SCAN_OPTIONS
        )
        return (
            fallback_snapshot,
            AgentLoadState(
                tier="tier2" if full_history else "tier1",
                complete_history=full_history,
                complete_visible_inbox=full_history,
                artifact_source="source_scan",
                used_artifact_index=False,
                index_error=str(exc),
                repair_recommended=True,
                repair_reason=(
                    "artifact_index_query_failed_full_history_fallback"
                    if full_history
                    else "artifact_index_query_failed_bounded_fallback"
                ),
                record_count=len(fallback_snapshot.records),
            ),
        )

    index_window = snapshot.index_window
    completeness = snapshot.index_completeness
    complete_history = (
        bool(completeness is not None and completeness.complete_history)
        if full_history
        else False
    )
    if full_history and not complete_history:
        fallback_snapshot = scan_artifacts()
        return (
            fallback_snapshot,
            AgentLoadState(
                tier="tier2",
                complete_history=True,
                complete_visible_inbox=True,
                artifact_source="source_scan",
                used_artifact_index=False,
                repair_reason="artifact_index_incomplete_full_history_fallback",
                record_count=len(fallback_snapshot.records),
            ),
        )
    stats = snapshot.stats
    # A baseline read used a window internally only so Rust reports
    # truncation; it is never a bounded prefix. Viewport windows keep
    # describing themselves via requested_limit/returned_count/has_more,
    # while a baseline read reports has_more=False so viewport expansion
    # never fires off one.
    is_viewport_read = (
        not full_history and requested_limit is not None and index_window is not None
    )
    baseline_truncated = bool(
        is_baseline_read and index_window is not None and index_window.has_more
    )
    state = AgentLoadState(
        tier="tier2" if full_history else "tier1",
        complete_history=complete_history,
        complete_visible_inbox=not baseline_truncated,
        artifact_source="artifact_index",
        used_artifact_index=True,
        truncated=baseline_truncated,
        record_count=len(snapshot.records),
        bounded_prefix=is_viewport_read,
        requested_limit=(
            None
            if index_window is None or is_baseline_read
            else index_window.requested_limit
        ),
        returned_count=(
            None
            if index_window is None or is_baseline_read
            else index_window.returned_record_count
        ),
        has_more=False
        if (index_window is None or is_baseline_read)
        else index_window.has_more,
        marker_signatures_checked=stats.marker_signatures_checked,
        rows_repaired=stats.rows_repaired,
        rows_discovered=stats.rows_discovered,
        rows_removed=stats.rows_removed,
        record_json_decoded=stats.record_json_decoded,
    )
    if cache_key is not None and before_signature is not None:
        after_signature = _artifact_index_signature(index_path)
        if after_signature == before_signature:
            ARTIFACT_SNAPSHOT_CACHE.put(
                cache_key,
                after_signature,
                snapshot,
                state,
            )
        else:
            ARTIFACT_SNAPSHOT_CACHE.record_mutation_refusal()
    return (snapshot, state)
