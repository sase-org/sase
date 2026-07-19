"""Cached off-thread enrichment for Agent Tribe detail documents."""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from sase.ace.tui.tools._constants import SLOW_TOOL_CALL_THRESHOLD_MS
from sase.stats.query import query_run_stats

from ...models._agent_clan_sections import (
    ClanAgentIdentity,
    ClanDiskSection,
    ClanDiskSnapshot,
    ClanSlowToolEntry,
    ClanTextEntry,
)
from ...models.agent import Agent
from ...models.agent_tribe_summary import (
    AgentTribeSummarySnapshot,
    TribePanelIdentity,
    tribe_unit_real_rows,
    tribe_unit_roots,
)
from ._agent_clan_aggregation import (
    build_agent_group_disk_snapshot,
    cache_clan_disk_snapshot,
    get_cached_clan_section_snapshot,
    prepare_clan_section_snapshot,
    should_refresh_clan_disk_snapshot,
)

type TribeEnrichmentSection = Literal[
    "replies",
    "slow-tool-calls",
    "runtime-statistics",
]

_TRIBE_DISK_SECTIONS: frozenset[TribeEnrichmentSection] = frozenset(
    {"replies", "slow-tool-calls"}
)
_TRIBE_SNAPSHOT_CACHE_MAX_ENTRIES = 64
_TRIBE_DISK_REFRESH_SECONDS = 10.0
_TRIBE_RUNTIME_STATS_TTL_SECONDS = 60.0
_TRIBE_STATS_TOP_N = 10_000


@dataclass(frozen=True, slots=True)
class TribeTextEntry:
    """One reply attributed to both its tribe unit and real member."""

    unit_identity: ClanAgentIdentity
    unit_label: str
    entry: ClanTextEntry


@dataclass(frozen=True, slots=True)
class TribeSlowToolEntry:
    """One slow tool call attributed to its tribe unit and real member."""

    unit_identity: ClanAgentIdentity
    unit_label: str
    entry: ClanSlowToolEntry


@dataclass(frozen=True, slots=True)
class TribeRuntimeStatistics:
    """All-time runtime statistics for one tribe."""

    runs: int
    total_seconds: float
    mean_seconds: float
    p50_seconds: float
    p95_seconds: float
    max_seconds: float
    share: float


@dataclass(frozen=True, slots=True)
class _TribeDiskSnapshot:
    """Aggregated disk-backed sections across ordered tribe units."""

    loaded_sections: frozenset[TribeEnrichmentSection]
    replies: tuple[TribeTextEntry, ...]
    slow_tool_calls: tuple[TribeSlowToolEntry, ...]


@dataclass(frozen=True, slots=True)
class TribeSectionSnapshot:
    """Renderer-facing cached enrichment state for one tribe panel."""

    panel_identity: TribePanelIdentity
    source_signature: tuple[tuple[ClanAgentIdentity, ...], ...]
    disk: _TribeDiskSnapshot | None = None
    runtime_statistics_loaded: bool = False
    runtime_statistics: TribeRuntimeStatistics | None = None
    loading_sections: frozenset[TribeEnrichmentSection] = frozenset()


@dataclass(frozen=True, slots=True)
class TribeUnitSource:
    """Loaded in-memory rows captured for one off-thread unit load."""

    root: Agent
    unit_identity: ClanAgentIdentity
    unit_label: str
    rows: tuple[Agent, ...]
    labels: dict[ClanAgentIdentity, str]

    @property
    def signature(self) -> tuple[ClanAgentIdentity, ...]:
        return (self.unit_identity, *(row.identity for row in self.rows))


@dataclass(frozen=True, slots=True)
class TribeEnrichmentResult:
    """One worker result, including clan snapshots worth reusing later."""

    panel_identity: TribePanelIdentity
    source_signature: tuple[tuple[ClanAgentIdentity, ...], ...]
    disk: _TribeDiskSnapshot | None
    runtime_statistics_refreshed: bool
    runtime_statistics: TribeRuntimeStatistics | None
    clan_updates: tuple[tuple[Agent, ClanDiskSnapshot], ...] = ()


@dataclass(frozen=True, slots=True)
class _TribeSnapshotCacheEntry:
    snapshot: TribeSectionSnapshot
    sources: tuple[TribeUnitSource, ...]
    disk_enriched_monotonic: float | None = None
    stats_enriched_monotonic: float | None = None


def prepare_tribe_section_snapshot(
    widget: object,
    summary: AgentTribeSummarySnapshot,
    agents: Sequence[Agent],
) -> TribeSectionSnapshot:
    """Refresh the pure source projection while retaining matching caches."""
    roots = tribe_unit_roots(agents)
    units_by_identity = {unit.identity: unit for unit in summary.units}
    sources: list[TribeUnitSource] = []
    for root in roots:
        unit = units_by_identity.get(root.identity)
        if unit is None:
            continue
        rows = tribe_unit_real_rows(root)
        labels = {unit.identity: unit.label}
        labels.update({child.identity: child.label for child in unit.children})
        sources.append(
            TribeUnitSource(
                root=root,
                unit_identity=unit.identity,
                unit_label=unit.label,
                rows=rows,
                labels=labels,
            )
        )
        if root.is_clan_container:
            prepare_clan_section_snapshot(widget, root)

    frozen_sources = tuple(sources)
    signature = tuple(source.signature for source in frozen_sources)
    cache = _tribe_snapshot_cache(widget)
    cached = cache.get(summary.container_identity)
    same_sources = cached is not None and cached.snapshot.source_signature == signature
    snapshot = TribeSectionSnapshot(
        panel_identity=summary.container_identity,
        source_signature=signature,
        disk=(cached.snapshot.disk if same_sources and cached is not None else None),
        runtime_statistics_loaded=(
            cached.snapshot.runtime_statistics_loaded if cached is not None else False
        ),
        runtime_statistics=(
            cached.snapshot.runtime_statistics if cached is not None else None
        ),
        loading_sections=(
            cached.snapshot.loading_sections
            if same_sources and cached is not None
            else frozenset()
        ),
    )
    cache[summary.container_identity] = _TribeSnapshotCacheEntry(
        snapshot=snapshot,
        sources=frozen_sources,
        disk_enriched_monotonic=(
            cached.disk_enriched_monotonic if same_sources and cached else None
        ),
        stats_enriched_monotonic=(
            cached.stats_enriched_monotonic if cached is not None else None
        ),
    )
    _trim_tribe_snapshot_cache(cache)
    return snapshot


def get_cached_tribe_section_snapshot(
    widget: object,
    panel_identity: TribePanelIdentity,
) -> TribeSectionSnapshot | None:
    """Return renderer-facing tribe enrichment without doing I/O."""
    cache = _tribe_snapshot_cache(widget)
    entry = cache.get(panel_identity)
    if entry is None:
        return None
    cache.move_to_end(panel_identity)
    return entry.snapshot


def get_cached_tribe_sources(
    widget: object,
    panel_identity: TribePanelIdentity,
) -> tuple[TribeUnitSource, ...]:
    """Return the current source projection captured for a tribe worker."""
    entry = _tribe_snapshot_cache(widget).get(panel_identity)
    return entry.sources if entry is not None else ()


def tribe_sections_to_refresh(
    widget: object,
    panel_identity: TribePanelIdentity,
    sections: Collection[TribeEnrichmentSection],
) -> frozenset[TribeEnrichmentSection]:
    """Return stale or uncovered requirements using only cache metadata."""
    requested = frozenset(sections)
    entry = _tribe_snapshot_cache(widget).get(panel_identity)
    if entry is None:
        return requested
    refresh: set[TribeEnrichmentSection] = set()
    requested_disk = requested & _TRIBE_DISK_SECTIONS
    disk = entry.snapshot.disk
    if requested_disk and (
        disk is None
        or not requested_disk.issubset(disk.loaded_sections)
        or entry.disk_enriched_monotonic is None
        or time.monotonic() - entry.disk_enriched_monotonic
        >= _TRIBE_DISK_REFRESH_SECONDS
    ):
        refresh.update(requested_disk)
    if "runtime-statistics" in requested and (
        not entry.snapshot.runtime_statistics_loaded
        or entry.stats_enriched_monotonic is None
        or time.monotonic() - entry.stats_enriched_monotonic
        >= _TRIBE_RUNTIME_STATS_TTL_SECONDS
    ):
        refresh.add("runtime-statistics")
    return frozenset(refresh)


def mark_tribe_snapshot_loading(
    widget: object,
    panel_identity: TribePanelIdentity,
    sections: Collection[TribeEnrichmentSection],
) -> None:
    """Publish worker requirements without disturbing cached values."""
    cache = _tribe_snapshot_cache(widget)
    entry = cache.get(panel_identity)
    if entry is None:
        return
    entry_snapshot = entry.snapshot
    snapshot = TribeSectionSnapshot(
        panel_identity=entry_snapshot.panel_identity,
        source_signature=entry_snapshot.source_signature,
        disk=entry_snapshot.disk,
        runtime_statistics_loaded=entry_snapshot.runtime_statistics_loaded,
        runtime_statistics=entry_snapshot.runtime_statistics,
        loading_sections=frozenset((*entry_snapshot.loading_sections, *sections)),
    )
    cache[panel_identity] = _replace_snapshot(entry, snapshot)


def clear_tribe_snapshot_loading(
    widget: object,
    panel_identity: TribePanelIdentity,
    sections: Collection[TribeEnrichmentSection],
) -> None:
    """Clear loading flags belonging to one terminal worker request."""
    cache = _tribe_snapshot_cache(widget)
    entry = cache.get(panel_identity)
    if entry is None:
        return
    remaining = entry.snapshot.loading_sections - frozenset(sections)
    if remaining == entry.snapshot.loading_sections:
        return
    snapshot = TribeSectionSnapshot(
        panel_identity=entry.snapshot.panel_identity,
        source_signature=entry.snapshot.source_signature,
        disk=entry.snapshot.disk,
        runtime_statistics_loaded=entry.snapshot.runtime_statistics_loaded,
        runtime_statistics=entry.snapshot.runtime_statistics,
        loading_sections=remaining,
    )
    cache[panel_identity] = _replace_snapshot(entry, snapshot)


def build_tribe_enrichment(
    widget: object,
    panel_identity: TribePanelIdentity,
    sources: tuple[TribeUnitSource, ...],
    *,
    sections: Collection[TribeEnrichmentSection],
    slow_tool_threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS,
) -> TribeEnrichmentResult:
    """Load requested tribe sections; call only from a worker thread."""
    requested = frozenset(sections)
    requested_disk = cast(frozenset[ClanDiskSection], requested & _TRIBE_DISK_SECTIONS)
    replies: list[TribeTextEntry] = []
    slow_calls: list[TribeSlowToolEntry] = []
    loaded_disk_sections: set[TribeEnrichmentSection] = set(
        requested & _TRIBE_DISK_SECTIONS
    )
    clan_updates: list[tuple[Agent, ClanDiskSnapshot]] = []

    if requested_disk:
        for source in sources:
            disk = _disk_snapshot_for_source(
                widget,
                source,
                sections=requested_disk,
                slow_tool_threshold_ms=slow_tool_threshold_ms,
            )
            loaded_disk_sections.update(
                cast(Collection[TribeEnrichmentSection], disk.loaded_sections)
            )
            replies.extend(
                TribeTextEntry(source.unit_identity, source.unit_label, entry)
                for entry in disk.replies
            )
            slow_calls.extend(
                TribeSlowToolEntry(source.unit_identity, source.unit_label, entry)
                for entry in disk.slow_tool_calls
            )
            if source.root.is_clan_container:
                clan_updates.append((source.root, disk))

    stats_refreshed = "runtime-statistics" in requested
    stats = (
        _load_tribe_runtime_statistics(panel_identity[1]) if stats_refreshed else None
    )
    disk_snapshot = (
        _TribeDiskSnapshot(
            loaded_sections=frozenset(loaded_disk_sections),
            replies=tuple(replies),
            slow_tool_calls=tuple(slow_calls),
        )
        if requested_disk
        else None
    )
    return TribeEnrichmentResult(
        panel_identity=panel_identity,
        source_signature=tuple(source.signature for source in sources),
        disk=disk_snapshot,
        runtime_statistics_refreshed=stats_refreshed,
        runtime_statistics=stats,
        clan_updates=tuple(clan_updates),
    )


def cache_tribe_enrichment(
    widget: object,
    result: TribeEnrichmentResult,
) -> TribeSectionSnapshot | None:
    """Merge a worker result only into its matching source projection."""
    cache = _tribe_snapshot_cache(widget)
    entry = cache.get(result.panel_identity)
    if entry is None or entry.snapshot.source_signature != result.source_signature:
        return None
    for clan, disk in result.clan_updates:
        cache_clan_disk_snapshot(widget, clan, disk)
    now = time.monotonic()
    snapshot = TribeSectionSnapshot(
        panel_identity=result.panel_identity,
        source_signature=entry.snapshot.source_signature,
        disk=result.disk if result.disk is not None else entry.snapshot.disk,
        runtime_statistics_loaded=(
            True
            if result.runtime_statistics_refreshed
            else entry.snapshot.runtime_statistics_loaded
        ),
        runtime_statistics=(
            result.runtime_statistics
            if result.runtime_statistics_refreshed
            else entry.snapshot.runtime_statistics
        ),
        loading_sections=entry.snapshot.loading_sections,
    )
    cache[result.panel_identity] = _TribeSnapshotCacheEntry(
        snapshot=snapshot,
        sources=entry.sources,
        disk_enriched_monotonic=(
            now if result.disk is not None else entry.disk_enriched_monotonic
        ),
        stats_enriched_monotonic=(
            now
            if result.runtime_statistics_refreshed
            else entry.stats_enriched_monotonic
        ),
    )
    cache.move_to_end(result.panel_identity)
    return snapshot


def _load_tribe_runtime_statistics(
    panel_key: str | None,
    *,
    end_ts: int | None = None,
) -> TribeRuntimeStatistics | None:
    """Query and select one all-time tribe runtime row off-thread."""
    try:
        payload = query_run_stats(
            start_ts=0,
            end_ts=end_ts if end_ts is not None else math.ceil(time.time()),
            runtime_group_by="tribe",
            top_n=_TRIBE_STATS_TOP_N,
        )
    except (OSError, RuntimeError):
        # A fresh installation may not have an artifact index yet.  That is
        # the same user-facing state as an archive with no runs for this tribe.
        return None
    raw_rows = payload.get("runtime_groups", ())
    rows = tuple(row for row in raw_rows if isinstance(row, dict))
    selected = next(
        (
            row
            for row in rows
            if _runtime_group_matches_panel(row.get("group"), panel_key)
        ),
        None,
    )
    if selected is None:
        return None
    total_all = sum(_number(row.get("total_seconds")) for row in rows)
    total = _number(selected.get("total_seconds"))
    return TribeRuntimeStatistics(
        runs=_integer(selected.get("runs")),
        total_seconds=total,
        mean_seconds=_number(selected.get("mean_seconds")),
        p50_seconds=_number(selected.get("p50_seconds")),
        p95_seconds=_number(selected.get("p95_seconds")),
        max_seconds=_number(selected.get("max_seconds")),
        share=total / total_all if total_all > 0 else 0.0,
    )


def _disk_snapshot_for_source(
    widget: object,
    source: TribeUnitSource,
    *,
    sections: frozenset[ClanDiskSection],
    slow_tool_threshold_ms: int,
) -> ClanDiskSnapshot:
    if source.root.is_clan_container:
        cached = get_cached_clan_section_snapshot(widget, source.root)
        if (
            cached is not None
            and cached.disk is not None
            and sections.issubset(cached.disk.loaded_sections)
            and not should_refresh_clan_disk_snapshot(widget, source.root, sections)
        ):
            return cached.disk
    return build_agent_group_disk_snapshot(
        widget,
        source.rows,
        labels=source.labels,
        sections=sections,
        slow_tool_threshold_ms=slow_tool_threshold_ms,
    )


def _runtime_group_matches_panel(value: object, panel_key: str | None) -> bool:
    from ...models.agent_panels import (
        DEFAULT_AGENT_TRIBE,
        effective_panel_tribe,
        is_reserved_default_panel,
    )

    if value is None:
        return is_reserved_default_panel(panel_key)
    label = str(value).strip()
    if not is_reserved_default_panel(panel_key):
        return label.removeprefix("@") == effective_panel_tribe(panel_key)
    return label.casefold() in {
        "",
        DEFAULT_AGENT_TRIBE,
        f"@{DEFAULT_AGENT_TRIBE}",
        "(no tribe)",
        "no tribe",
        # Legacy renderer labels remain readable by cached runtime snapshots.
        "(untagged)",
        "untagged",
        "none",
        "null",
        "unknown",
        "—",
    }


def _number(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _replace_snapshot(
    entry: _TribeSnapshotCacheEntry,
    snapshot: TribeSectionSnapshot,
) -> _TribeSnapshotCacheEntry:
    return _TribeSnapshotCacheEntry(
        snapshot=snapshot,
        sources=entry.sources,
        disk_enriched_monotonic=entry.disk_enriched_monotonic,
        stats_enriched_monotonic=entry.stats_enriched_monotonic,
    )


def _tribe_snapshot_cache(
    widget: object,
) -> OrderedDict[TribePanelIdentity, _TribeSnapshotCacheEntry]:
    cache = getattr(widget, "_tribe_snapshot_cache", None)
    if cache is None:
        cache = OrderedDict()
        cast(Any, widget)._tribe_snapshot_cache = cache
    return cast(OrderedDict[TribePanelIdentity, _TribeSnapshotCacheEntry], cache)


def _trim_tribe_snapshot_cache(
    cache: OrderedDict[TribePanelIdentity, _TribeSnapshotCacheEntry],
) -> None:
    cache.move_to_end(next(reversed(cache)))
    while len(cache) > _TRIBE_SNAPSHOT_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


__all__ = [
    "TribeEnrichmentResult",
    "TribeEnrichmentSection",
    "TribeRuntimeStatistics",
    "TribeSectionSnapshot",
    "TribeSlowToolEntry",
    "TribeTextEntry",
    "TribeUnitSource",
    "build_tribe_enrichment",
    "cache_tribe_enrichment",
    "clear_tribe_snapshot_loading",
    "get_cached_tribe_section_snapshot",
    "get_cached_tribe_sources",
    "mark_tribe_snapshot_loading",
    "prepare_tribe_section_snapshot",
    "tribe_sections_to_refresh",
]
