"""Cached off-thread enrichment for agent-clan section snapshots."""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Lock
from typing import Any, cast

from sase.ace.tui.tools._constants import SLOW_TOOL_CALL_THRESHOLD_MS

from ...models._agent_clan_sections import (
    ClanAgentIdentity,
    ClanDiskMemberSnapshot,
    ClanDiskSection,
    ClanDiskSnapshot,
    ClanInMemorySnapshot,
    ClanSectionSnapshot,
    aggregate_clan_in_memory,
    clan_section_member_rows,
)
from ...models.agent import Agent
from ._agent_clan_disk_aggregation import (
    aggregate_clan_context_lanes as _aggregate_clan_context_lanes,
    aggregate_clan_slow_tool_calls as _aggregate_clan_slow_tool_calls,
)
from ._agent_display_clan_context import clan_context_entry_hint_target
from ._file_path_hints import resolve_agent_workspace_dir
from ._agent_clan_member_content import (
    clan_member_source_token as _clan_member_source_token,
    load_clan_disk_member_snapshot as _load_clan_disk_member_snapshot,
)

_CLAN_MEMBER_CACHE_MAX_ENTRIES = 512
_CLAN_SNAPSHOT_CACHE_MAX_ENTRIES = 128
_CLAN_SNAPSHOT_REFRESH_SECONDS = 10.0
_LOGICAL_PLAN_REFERENCE_RE = re.compile(r"(?<![\w])@?([A-Za-z][\w-]*:[\w.+\-/]+)")


@dataclass(frozen=True, slots=True)
class _ClanMemberCacheEntry:
    source_token: tuple[object, ...]
    snapshot: ClanDiskMemberSnapshot


@dataclass(frozen=True, slots=True)
class _ClanSnapshotCacheEntry:
    snapshot: ClanSectionSnapshot
    enriched_monotonic: float | None = None


class _ClanDiskContentCache:
    """Bounded per-member cache keyed by identity and source mtimes."""

    def __init__(self, *, max_entries: int = _CLAN_MEMBER_CACHE_MAX_ENTRIES) -> None:
        self._entries: OrderedDict[ClanAgentIdentity, _ClanMemberCacheEntry] = (
            OrderedDict()
        )
        self._max_entries = max_entries
        self._lock = Lock()

    def load(
        self,
        member: Agent,
        *,
        member_label: str,
        sections: frozenset[ClanDiskSection],
        loader: Callable[
            [Agent, str, frozenset[ClanDiskSection]], ClanDiskMemberSnapshot
        ]
        | None = None,
    ) -> ClanDiskMemberSnapshot:
        """Return cached member content or load the required section union."""
        source_token = _clan_member_source_token(member)
        with self._lock:
            cached = self._entries.get(member.identity)
            if cached is not None and cached.source_token == source_token:
                loaded = cached.snapshot.loaded_sections
                if sections.issubset(loaded):
                    self._entries.move_to_end(member.identity)
                    return cached.snapshot
                sections = frozenset((*loaded, *sections))

        snapshot = (
            loader(member, member_label, sections)
            if loader is not None
            else _load_clan_disk_member_snapshot(
                member,
                member_label=member_label,
                sections=sections,
            )
        )
        with self._lock:
            self._entries[member.identity] = _ClanMemberCacheEntry(
                source_token=source_token,
                snapshot=snapshot,
            )
            self._entries.move_to_end(member.identity)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return snapshot

    def clear(self) -> None:
        """Clear all cached member content."""
        with self._lock:
            self._entries.clear()


def prepare_clan_section_snapshot(widget: object, agent: Agent) -> ClanSectionSnapshot:
    """Refresh the cheap portion of a widget-local clan snapshot."""
    in_memory = aggregate_clan_in_memory(agent)
    cache = _clan_snapshot_cache(widget)
    cached = cache.get(agent.identity)
    disk = None
    loading_sections: frozenset[ClanDiskSection] = frozenset()
    enriched_monotonic = None
    if (
        cached is not None
        and cached.snapshot.in_memory.member_identities == in_memory.member_identities
    ):
        disk = cached.snapshot.disk
        loading_sections = cached.snapshot.loading_sections
        revision = cached.snapshot.revision
        enriched_monotonic = cached.enriched_monotonic
    else:
        revision = 0
    snapshot = ClanSectionSnapshot(
        in_memory=in_memory,
        disk=disk,
        loading_sections=loading_sections,
        revision=revision,
    )
    cache[agent.identity] = _ClanSnapshotCacheEntry(
        snapshot=snapshot,
        enriched_monotonic=enriched_monotonic,
    )
    _trim_snapshot_cache(cache)
    return snapshot


def get_cached_clan_section_snapshot(
    widget: object,
    agent: Agent,
) -> ClanSectionSnapshot | None:
    """Return the current renderer-facing clan snapshot without doing I/O."""
    cache = _clan_snapshot_cache(widget)
    entry = cache.get(agent.identity)
    if entry is None:
        return None
    cache.move_to_end(agent.identity)
    return entry.snapshot


def should_refresh_clan_disk_snapshot(
    widget: object,
    agent: Agent,
    sections: Collection[ClanDiskSection],
) -> bool:
    """Check cache coverage/freshness without probing any source paths."""
    requested = frozenset(sections)
    if not requested:
        return False
    entry = _clan_snapshot_cache(widget).get(agent.identity)
    if entry is None or entry.snapshot.disk is None:
        return True
    if not requested.issubset(entry.snapshot.disk.loaded_sections):
        return True
    if entry.enriched_monotonic is None:
        return True
    return (time.monotonic() - entry.enriched_monotonic) >= (
        _CLAN_SNAPSHOT_REFRESH_SECONDS
    )


def mark_clan_snapshot_loading(
    widget: object,
    agent: Agent,
    sections: Collection[ClanDiskSection],
) -> None:
    """Publish loading state for requested sections without disturbing cache."""
    cache = _clan_snapshot_cache(widget)
    entry = cache.get(agent.identity)
    if entry is None:
        prepare_clan_section_snapshot(widget, agent)
        entry = cache.get(agent.identity)
    assert entry is not None
    snapshot = ClanSectionSnapshot(
        in_memory=entry.snapshot.in_memory,
        disk=entry.snapshot.disk,
        loading_sections=frozenset(sections),
        revision=entry.snapshot.revision,
    )
    cache[agent.identity] = _ClanSnapshotCacheEntry(
        snapshot=snapshot,
        enriched_monotonic=entry.enriched_monotonic,
    )


def clear_clan_snapshot_loading(widget: object, agent: Agent) -> None:
    """Clear loading flags after a worker reaches a terminal state."""
    cache = _clan_snapshot_cache(widget)
    entry = cache.get(agent.identity)
    if entry is None or not entry.snapshot.loading_sections:
        return
    cache[agent.identity] = _ClanSnapshotCacheEntry(
        snapshot=ClanSectionSnapshot(
            in_memory=entry.snapshot.in_memory,
            disk=entry.snapshot.disk,
            revision=entry.snapshot.revision,
        ),
        enriched_monotonic=entry.enriched_monotonic,
    )


def cache_clan_disk_snapshot(
    widget: object,
    agent: Agent,
    disk: ClanDiskSnapshot,
) -> ClanSectionSnapshot | None:
    """Merge a worker result only when it still matches the member projection."""
    cache = _clan_snapshot_cache(widget)
    entry = cache.get(agent.identity)
    if entry is None:
        return None
    disk_identities = tuple(member.member_identity for member in disk.members)
    if disk_identities != entry.snapshot.in_memory.member_identities:
        return None
    snapshot = ClanSectionSnapshot(
        in_memory=entry.snapshot.in_memory,
        disk=disk,
        revision=entry.snapshot.revision + 1,
    )
    cache[agent.identity] = _ClanSnapshotCacheEntry(
        snapshot=snapshot,
        enriched_monotonic=time.monotonic(),
    )
    cache.move_to_end(agent.identity)
    return snapshot


def build_clan_disk_snapshot(
    widget: object,
    agent: Agent,
    in_memory: ClanInMemorySnapshot,
    *,
    sections: Collection[ClanDiskSection],
    now: datetime | None = None,
    slow_tool_threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS,
) -> ClanDiskSnapshot:
    """Load and aggregate requested disk sections; call only off-thread."""
    rows = clan_section_member_rows(agent)
    label_by_identity = {member.identity: member.label for member in in_memory.members}
    disk = build_agent_group_disk_snapshot(
        widget,
        rows,
        labels=label_by_identity,
        sections=sections,
        in_memory=in_memory,
        now=now,
        slow_tool_threshold_ms=slow_tool_threshold_ms,
    )
    return replace(
        disk,
        hint_paths=_build_clan_hint_paths(
            agent,
            rows=rows,
            labels=label_by_identity,
            disk=disk,
        ),
    )


def _build_clan_hint_paths(
    agent: Agent,
    *,
    rows: tuple[Agent, ...],
    labels: dict[ClanAgentIdentity, str],
    disk: ClanDiskSnapshot,
) -> dict[str, str]:
    """Build worker-only aliases from displayed path tokens to real targets."""
    hint_paths: dict[str, str] = {}
    fallback_workspace, workspace_num = _clan_hint_workspace_context(rows)
    member_workspaces = {
        labels[row.identity]: resolve_agent_workspace_dir(
            row.effective_workspace_num,
            row.project_file,
            row.workspace_dir,
        )
        for row in rows
        if row.identity in labels
    }

    for lane in disk.context_lanes:
        for entry in lane.entries:
            target = clan_context_entry_hint_target(
                lane.label,
                entry,
                member_workspaces=member_workspaces,
                fallback_workspace=fallback_workspace,
            )
            if target is None:
                continue
            _index_hint_path(hint_paths, entry.label, target)
            _index_hint_path(hint_paths, entry.key, target)
            _index_hint_path(hint_paths, target, target)

    if fallback_workspace is None:
        return hint_paths

    from sase.sdd.plan_refs import parse_plan_reference, resolve_plan_reference

    for match in _LOGICAL_PLAN_REFERENCE_RE.finditer(agent.clan_summary or ""):
        reference = match.group(1)
        try:
            parsed = parse_plan_reference(reference)
            resolution = resolve_plan_reference(
                reference,
                workspace_dir=fallback_workspace,
                workspace_num=workspace_num,
            )
        except Exception:
            continue
        if resolution.resolved_path is None:
            continue
        target = str(resolution.resolved_path)
        _index_hint_path(hint_paths, reference, target)
        _index_hint_path(hint_paths, parsed.path, target)
        _index_hint_path(hint_paths, target, target)
    return hint_paths


def _clan_hint_workspace_context(rows: tuple[Agent, ...]) -> tuple[str | None, int]:
    """Return the first addressable clan member workspace and its number."""
    for row in rows:
        workspace_num = row.effective_workspace_num
        if not row.workspace_dir and not (
            workspace_num is not None and workspace_num > 0
        ):
            continue
        workspace_dir = resolve_agent_workspace_dir(
            workspace_num,
            row.project_file,
            row.workspace_dir,
        )
        if workspace_dir is not None:
            return (
                workspace_dir,
                workspace_num if workspace_num and workspace_num > 0 else 1,
            )
    return None, 1


def _index_hint_path(index: dict[str, str], displayed: str, target: str) -> None:
    """Index a displayed path plus each path-component suffix, first wins."""
    value = displayed.strip().lstrip("@")
    if not value:
        return
    index.setdefault(value, target)
    path_value = value
    if not value.startswith("/") and ":" in value:
        _kind, remainder = value.split(":", 1)
        if remainder:
            path_value = remainder
            index.setdefault(remainder, target)
    parts = tuple(part for part in path_value.split("/") if part and part != ".")
    for offset in range(len(parts)):
        index.setdefault("/".join(parts[offset:]), target)


def build_agent_group_disk_snapshot(
    widget: object,
    rows: Collection[Agent],
    *,
    labels: dict[ClanAgentIdentity, str],
    sections: Collection[ClanDiskSection],
    in_memory: ClanInMemorySnapshot | None = None,
    now: datetime | None = None,
    slow_tool_threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS,
) -> ClanDiskSnapshot:
    """Load disk sections for an arbitrary ordered group of real rows.

    This is the shared worker-only primitive used by clan and tribe
    enrichment.  It deliberately retains the clan snapshot vocabulary so
    every caller shares the same mtime-keyed per-member content cache.
    """
    requested = frozenset(sections)
    member_cache = _clan_disk_content_cache(widget)
    members = tuple(
        member_cache.load(
            row,
            member_label=labels.get(row.identity, row.display_name),
            sections=requested,
        )
        for row in rows
    )
    loaded_sections = frozenset(
        section for member in members for section in member.loaded_sections
    )
    replies = (
        tuple(entry for member in members for entry in member.replies)
        if "replies" in loaded_sections
        else ()
    )
    prompts = (
        tuple(entry for member in members for entry in member.prompts)
        if "prompts" in loaded_sections
        else ()
    )
    context_lanes = (
        _aggregate_clan_context_lanes(
            in_memory,
            members,
            member_rows=rows,
        )
        if "context" in loaded_sections and in_memory is not None
        else ()
    )
    slow_tool_calls = (
        _aggregate_clan_slow_tool_calls(
            members,
            now=now or datetime.now(tz=UTC),
            threshold_ms=slow_tool_threshold_ms,
        )
        if "slow-tool-calls" in loaded_sections
        else ()
    )
    return ClanDiskSnapshot(
        loaded_sections=loaded_sections,
        members=members,
        replies=replies,
        prompts=prompts,
        context_lanes=context_lanes,
        slow_tool_calls=slow_tool_calls,
    )


def _clan_snapshot_cache(
    widget: object,
) -> OrderedDict[ClanAgentIdentity, _ClanSnapshotCacheEntry]:
    cache = getattr(widget, "_clan_section_snapshot_cache", None)
    if cache is None:
        cache = OrderedDict()
        cast(Any, widget)._clan_section_snapshot_cache = cache
    return cast(OrderedDict[ClanAgentIdentity, _ClanSnapshotCacheEntry], cache)


def _clan_disk_content_cache(widget: object) -> _ClanDiskContentCache:
    cache = getattr(widget, "_clan_disk_content_cache", None)
    if cache is None:
        cache = _ClanDiskContentCache()
        cast(Any, widget)._clan_disk_content_cache = cache
    return cast(_ClanDiskContentCache, cache)


def _trim_snapshot_cache(
    cache: OrderedDict[ClanAgentIdentity, _ClanSnapshotCacheEntry],
) -> None:
    cache.move_to_end(next(reversed(cache)))
    while len(cache) > _CLAN_SNAPSHOT_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


__all__ = [
    "build_agent_group_disk_snapshot",
    "build_clan_disk_snapshot",
    "cache_clan_disk_snapshot",
    "clear_clan_snapshot_loading",
    "get_cached_clan_section_snapshot",
    "mark_clan_snapshot_loading",
    "prepare_clan_section_snapshot",
    "should_refresh_clan_disk_snapshot",
]
