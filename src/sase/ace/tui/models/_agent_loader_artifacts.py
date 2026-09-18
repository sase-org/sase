"""Artifact snapshot selection and path helpers for the agent loader."""

from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
from threading import RLock
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
_ARTIFACT_SNAPSHOT_CACHE_MAX_ENTRIES = 8

_IndexFileStat = tuple[str, int | None, int | None]
_IndexSignature = tuple[_IndexFileStat, _IndexFileStat]
_ArtifactSnapshotCacheKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class _ArtifactSnapshotCacheStats:
    """Process-local diagnostics for the TUI artifact snapshot cache."""

    hits: int = 0
    misses: int = 0
    stores: int = 0
    mutation_refusals: int = 0
    evictions: int = 0
    bypasses: int = 0


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
    bounded_prefix: bool = False
    requested_limit: int | None = None
    returned_count: int | None = None
    has_more: bool = False
    query_incomplete: bool = False
    history_query_key: tuple[str, str] | None = None
    marker_signatures_checked: int = 0
    rows_repaired: int = 0
    rows_discovered: int = 0
    rows_removed: int = 0
    record_json_decoded: int = 0

    @property
    def needs_full_history_reconcile(self) -> bool:
        """Return whether the caller should schedule a Tier 2 refresh."""

        return (
            not self.complete_visible_inbox
            or self.repair_recommended
            or self.truncated
            or self.query_incomplete
            or (self.tier == "tier2" and not self.complete_history)
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
    ) -> AgentArtifactScanWire | None: ...


class _Tier1IndexLoader(Protocol):
    def __call__(
        self,
        *,
        full_history: bool,
        freshness: Literal["revalidate", "cached"] = "cached",
        requested_limit: int | None = None,
        candidate_filter: dict[str, object] | None = None,
    ) -> tuple[AgentArtifactScanWire, AgentLoadState] | None: ...


class _ArtifactSnapshotCache:
    """Small mtime/size-guarded cache for warm bounded index snapshots."""

    def __init__(self, *, max_entries: int) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[
            _ArtifactSnapshotCacheKey,
            tuple[_IndexSignature, AgentArtifactScanWire, AgentLoadState],
        ] = OrderedDict()
        self._stats = _ArtifactSnapshotCacheStats()
        self._lock = RLock()

    def get(
        self,
        key: _ArtifactSnapshotCacheKey,
        signature: _IndexSignature,
    ) -> tuple[AgentArtifactScanWire, AgentLoadState] | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._stats = replace(self._stats, misses=self._stats.misses + 1)
                return None
            cached_signature, snapshot, state = entry
            if cached_signature != signature:
                del self._entries[key]
                self._stats = replace(self._stats, misses=self._stats.misses + 1)
                return None
            self._entries.move_to_end(key)
            self._stats = replace(self._stats, hits=self._stats.hits + 1)
            return snapshot, _cache_hit_load_state(state)

    def put(
        self,
        key: _ArtifactSnapshotCacheKey,
        signature: _IndexSignature,
        snapshot: AgentArtifactScanWire,
        state: AgentLoadState,
    ) -> None:
        with self._lock:
            self._entries[key] = (signature, snapshot, state)
            self._entries.move_to_end(key)
            stats = replace(self._stats, stores=self._stats.stores + 1)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
                stats = replace(stats, evictions=stats.evictions + 1)
            self._stats = stats

    def record_mutation_refusal(self) -> None:
        with self._lock:
            self._stats = replace(
                self._stats,
                mutation_refusals=self._stats.mutation_refusals + 1,
            )

    def record_bypass(self) -> None:
        with self._lock:
            self._stats = replace(self._stats, bypasses=self._stats.bypasses + 1)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._stats = _ArtifactSnapshotCacheStats()

    def stats(self) -> _ArtifactSnapshotCacheStats:
        with self._lock:
            return self._stats


_ARTIFACT_SNAPSHOT_CACHE = _ArtifactSnapshotCache(
    max_entries=_ARTIFACT_SNAPSHOT_CACHE_MAX_ENTRIES
)


def _stat_index_file(path: Path) -> _IndexFileStat:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _artifact_index_signature(index_path: Path) -> _IndexSignature:
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
) -> _ArtifactSnapshotCacheKey:
    return (
        str(index_path),
        str(projects_root),
        _json_key(asdict(query)),
        _json_key(asdict(options)),
    )


def _cache_hit_load_state(state: AgentLoadState) -> AgentLoadState:
    return replace(
        state,
        marker_signatures_checked=0,
        rows_repaired=0,
        rows_discovered=0,
        rows_removed=0,
        record_json_decoded=0,
    )


def query_artifact_index_for_loader(
    *,
    full_history: bool,
    freshness: Literal["revalidate", "cached"] = "cached",
    requested_limit: int | None = None,
    candidate_filter: dict[str, object] | None = None,
    default_index_path: Callable[[], Path],
    projects_root: Callable[[], Path],
    query_index: _ArtifactIndexQuery,
    scan_artifacts: _ArtifactScanner,
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

    active_limit = None if full_history else _TIER1_ACTIVE_LIMIT
    recent_completed_limit = None if full_history else _TIER1_RECENT_COMPLETED_LIMIT
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
        window_limit=None if full_history else requested_limit,
        candidate_filter=candidate_filter,
        agents_list_projection=True,
    )
    root = projects_root()
    cacheable = not full_history and query_freshness == "cached"
    cache_key: _ArtifactSnapshotCacheKey | None = None
    before_signature: _IndexSignature | None = None
    if cacheable:
        before_signature = _artifact_index_signature(index_path)
        cache_key = _artifact_snapshot_cache_key(
            index_path=index_path,
            projects_root=root,
            query=query,
            options=_TUI_SCAN_OPTIONS,
        )
        cached = _ARTIFACT_SNAPSHOT_CACHE.get(cache_key, before_signature)
        if cached is not None:
            return cached
    else:
        _ARTIFACT_SNAPSHOT_CACHE.record_bypass()

    try:
        snapshot = query_index(
            index_path,
            root,
            query=query,
            options=_TUI_SCAN_OPTIONS,
        )
        if snapshot is None:
            fallback_snapshot = scan_artifacts(
                None if full_history else _TIER1_FALLBACK_SCAN_OPTIONS
            )
            return (
                fallback_snapshot,
                AgentLoadState(
                    tier="tier2" if full_history else "tier1",
                    # Source scan is authoritative for the dirs it visited.
                    complete_history=full_history,
                    complete_visible_inbox=full_history,
                    artifact_source="source_scan",
                    used_artifact_index=False,
                    index_error="artifact index operation lock busy",
                    repair_recommended=False,
                    repair_reason=(
                        "artifact_index_lock_busy_full_history_fallback"
                        if full_history
                        else "artifact_index_lock_busy_bounded_fallback"
                    ),
                    record_count=len(fallback_snapshot.records),
                ),
            )
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError) as exc:
        fallback_snapshot = scan_artifacts(
            None if full_history else _TIER1_FALLBACK_SCAN_OPTIONS
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
    state = AgentLoadState(
        tier="tier2" if full_history else "tier1",
        complete_history=complete_history,
        complete_visible_inbox=True,
        artifact_source="artifact_index",
        used_artifact_index=True,
        record_count=len(snapshot.records),
        bounded_prefix=not full_history and index_window is not None,
        requested_limit=(
            None if index_window is None else index_window.requested_limit
        ),
        returned_count=(
            None if index_window is None else index_window.returned_record_count
        ),
        has_more=False if index_window is None else index_window.has_more,
        marker_signatures_checked=stats.marker_signatures_checked,
        rows_repaired=stats.rows_repaired,
        rows_discovered=stats.rows_discovered,
        rows_removed=stats.rows_removed,
        record_json_decoded=stats.record_json_decoded,
    )
    if cache_key is not None and before_signature is not None:
        after_signature = _artifact_index_signature(index_path)
        if after_signature == before_signature:
            _ARTIFACT_SNAPSHOT_CACHE.put(
                cache_key,
                after_signature,
                snapshot,
                state,
            )
        else:
            _ARTIFACT_SNAPSHOT_CACHE.record_mutation_refusal()
    return (snapshot, state)


def artifact_snapshot_for_tui_load(
    *,
    full_history: bool,
    use_artifact_index: bool,
    index_freshness: Literal["revalidate", "cached"] = "cached",
    requested_limit: int | None = None,
    candidate_filter: dict[str, object] | None = None,
    scan_artifacts: _ArtifactScanner,
    load_tier1_index: _Tier1IndexLoader,
) -> tuple[AgentArtifactScanWire, AgentLoadState]:
    """Return the artifact snapshot for a TUI refresh."""

    if full_history:
        if use_artifact_index:
            indexed = load_tier1_index(
                full_history=full_history,
                freshness=index_freshness,
                requested_limit=None,
                candidate_filter=candidate_filter,
            )
            if indexed is not None and indexed[1].complete_history:
                return indexed

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
        requested_limit=requested_limit,
        candidate_filter=candidate_filter,
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
            snapshot = query_index(
                index_path,
                projects_root(),
                query=query,
                options=_PLAN_LIVE_SCAN_OPTIONS,
            )
            if snapshot is not None:
                return snapshot
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
