"""Cached off-thread enrichment for agent-clan section snapshots."""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, cast

from sase.agent.artifact_files_cache import get_global_cache
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.ace.tui.tools import SlowToolSource, build_slow_tool_sources
from sase.ace.tui.tools._constants import SLOW_TOOL_CALL_THRESHOLD_MS
from sase.ace.tui.tools.slow import select_slow_tool_calls
from sase.main.init_memory.config import project_memory_name
from sase.memory.read_log import memory_read_log_path
from sase.skills.use_log import skill_use_log_path

from ...models._agent_clan_sections import (
    CLAN_CONTEXT_LANE_ORDER,
    ClanAgentIdentity,
    ClanContextEntry,
    ClanContextLane,
    ClanDiskMemberSnapshot,
    ClanDiskSection,
    ClanDiskSnapshot,
    ClanInMemorySnapshot,
    ClanSectionSnapshot,
    ClanSlowToolEntry,
    ClanTextEntry,
    aggregate_clan_in_memory,
    clan_section_member_rows,
    first_meaningful_line,
)
from ...models.agent import Agent
from ._agent_display_content import get_prompt_content
from ._agent_display_header_summary import build_detail_header_summary
from ._agent_display_state import DetailHeaderSummary
from ._helpers import format_output

_CLAN_MEMBER_CACHE_MAX_ENTRIES = 512
_CLAN_SNAPSHOT_CACHE_MAX_ENTRIES = 128
_CLAN_SNAPSHOT_REFRESH_SECONDS = 10.0


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
        enriched_monotonic = cached.enriched_monotonic
    snapshot = ClanSectionSnapshot(
        in_memory=in_memory,
        disk=disk,
        loading_sections=loading_sections,
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
    return build_agent_group_disk_snapshot(
        widget,
        rows,
        labels=label_by_identity,
        sections=sections,
        in_memory=in_memory,
        now=now,
        slow_tool_threshold_ms=slow_tool_threshold_ms,
    )


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
        _aggregate_clan_context_lanes(in_memory, members)
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


def _load_clan_disk_member_snapshot(
    member: Agent,
    member_label: str,
    sections: frozenset[ClanDiskSection],
) -> ClanDiskMemberSnapshot:
    """Load requested content for one real member outside the event loop."""
    replies = (
        _load_member_replies(member, member_label) if "replies" in sections else ()
    )
    prompts = (
        _load_member_prompts(member, member_label) if "prompts" in sections else ()
    )
    needs_context = "context" in sections
    needs_slow_tools = "slow-tool-calls" in sections
    context: DetailHeaderSummary | None = None
    slow_tool_sources: tuple[SlowToolSource, ...] | None = None
    if needs_context:
        context = build_detail_header_summary(
            member,
            include_slow_tools=needs_slow_tools,
        )
        slow_tool_sources = context.slow_tool_sources
    elif needs_slow_tools:
        slow_tool_sources = build_slow_tool_sources(member)
    return ClanDiskMemberSnapshot(
        member_identity=member.identity,
        member_label=member_label,
        loaded_sections=sections,
        replies=replies,
        prompts=prompts,
        context=context,
        slow_tool_sources=slow_tool_sources,
    )


def _aggregate_clan_context_lanes(
    in_memory: ClanInMemorySnapshot,
    members: tuple[ClanDiskMemberSnapshot, ...],
) -> tuple[ClanContextLane, ...]:
    """De-duplicate context entries while preserving lane and member order."""
    accumulators: dict[str, OrderedDict[str, _ContextAccumulator]] = {
        label: OrderedDict() for label in CLAN_CONTEXT_LANE_ORDER
    }

    for bead_id in in_memory.bead_ids:
        _add_context(accumulators, "BEAD", bead_id, bead_id, None, bead_id)
    for plan_path in in_memory.plan_paths:
        _add_context(
            accumulators,
            "PLAN",
            _path_key(plan_path),
            plan_path,
            None,
            plan_path,
        )
    for workspace_num in in_memory.workspace_numbers:
        key = f"workspace:{workspace_num}"
        _add_context(
            accumulators,
            "WORKSPACES",
            key,
            f"workspace {workspace_num}",
            None,
            workspace_num,
        )

    for member in members:
        summary = member.context
        if summary is None:
            continue
        member_label = member.member_label
        if summary.phase_bead is not None:
            phase = summary.phase_bead
            label = phase.id
            if phase.description:
                preview = first_meaningful_line(phase.description)
                if preview:
                    label += f" · {preview}"
            _add_context(
                accumulators,
                "BEAD",
                phase.id,
                label,
                member_label,
                phase,
            )
        if summary.associated_plan is not None:
            plan = summary.associated_plan
            _add_context(
                accumulators,
                "PLAN",
                _path_key(plan.actual_path),
                plan.display_path,
                member_label,
                plan,
            )
        for artifact in summary.artifact_file_paths or ():
            _add_context(
                accumulators,
                "ARTIFACTS",
                _path_key(artifact.actual_path),
                artifact.display_path,
                member_label,
                artifact,
            )
        for delta in summary.delta_entries or ():
            _add_context(
                accumulators,
                "ARTIFACTS",
                _path_key(delta.path),
                delta.path,
                member_label,
                delta,
            )
        for group in summary.linked_delta_groups:
            for delta in group.entries:
                key = f"{_path_key(group.workspace_dir)}:{delta.path}"
                _add_context(
                    accumulators,
                    "ARTIFACTS",
                    key,
                    f"{group.repo_name}/{delta.path}",
                    member_label,
                    delta,
                )
        for memory_display in summary.memory_reads:
            memory_event = cast(MemoryReadDisplayEvent, memory_display).event
            _add_context(
                accumulators,
                "MEMORY",
                memory_event.canonical_path,
                memory_event.canonical_path,
                member_label,
                memory_display,
            )
        for skill_display in summary.skill_uses:
            skill_event = cast(SkillUseDisplayEvent, skill_display).event
            _add_context(
                accumulators,
                "SKILLS",
                skill_event.skill_name,
                skill_event.skill_name,
                member_label,
                skill_display,
            )
        for workspace_display in summary.opened_workspaces:
            workspace_event = cast(OpenedWorkspaceDisplayEvent, workspace_display)
            key = (
                _path_key(workspace_event.workspace_dir)
                if workspace_event.workspace_dir
                else workspace_event.name
            )
            _add_context(
                accumulators,
                "WORKSPACES",
                key,
                workspace_event.name,
                member_label,
                workspace_event,
            )

    lanes: list[ClanContextLane] = []
    for lane_label in CLAN_CONTEXT_LANE_ORDER:
        entries = tuple(
            accumulator.freeze() for accumulator in accumulators[lane_label].values()
        )
        if entries:
            lanes.append(ClanContextLane(label=lane_label, entries=entries))
    return tuple(lanes)


def _aggregate_clan_slow_tool_calls(
    members: tuple[ClanDiskMemberSnapshot, ...],
    *,
    now: datetime,
    threshold_ms: int,
) -> tuple[ClanSlowToolEntry, ...]:
    """Select, de-duplicate, and rank slow calls across the clan."""
    entries: list[ClanSlowToolEntry] = []
    seen: set[tuple[object, ...]] = set()
    member_order = {
        member.member_identity: index for index, member in enumerate(members)
    }
    for member in members:
        for source in member.slow_tool_sources or ():
            for call in select_slow_tool_calls(
                source.entries,
                now=now,
                agent_is_active=source.agent_is_active,
                agent_end_reference=source.end_reference,
                threshold_ms=threshold_ms,
            ):
                raw = call.entry
                key = (
                    raw.artifact_dir,
                    raw.source_path,
                    raw.line_number,
                    raw.tool_use_id,
                    raw.recorded_at,
                    raw.tool_name,
                )
                if key in seen:
                    continue
                seen.add(key)
                entries.append(
                    ClanSlowToolEntry(
                        member_identity=member.member_identity,
                        member_label=member.member_label,
                        source_label=source.label,
                        call=call,
                    )
                )
    return tuple(
        sorted(
            entries,
            key=lambda item: (
                -item.call.effective_duration_ms,
                member_order[item.member_identity],
                item.call.started_at,
                item.call.entry.line_number,
            ),
        )
    )


def _clan_member_source_token(member: Agent) -> tuple[object, ...]:
    """Return the member's in-memory inputs plus disk source mtimes.

    This function intentionally performs filesystem work and must only be
    called by the clan worker.  Direct artifact-file signatures cover prompt,
    reply, context-marker, and tool-call sources without any render-time glob.
    """
    source_paths: list[Path] = []
    rows = (member, *member.runtime_children, *member.followup_agents)
    seen_rows: set[ClanAgentIdentity] = set()
    for row in rows:
        if row.identity in seen_rows:
            continue
        seen_rows.add(row.identity)
        artifacts_dir = row.get_artifacts_dir()
        if artifacts_dir:
            artifact_root = Path(artifacts_dir).expanduser()
            source_paths.extend(_direct_artifact_sources(artifact_root))
            source_paths.extend(_chat_source_paths(artifact_root))
        for path_value in (
            row.response_path,
            row.plan_path,
            row.archived_plan_path,
            row.sdd_plan_path,
        ):
            if path_value:
                source_paths.append(Path(path_value).expanduser())
        source_paths.extend(_audit_log_paths(row))

    path_token = tuple(
        sorted(
            (_path_signature(path) for path in source_paths),
            key=lambda item: item[0],
        )
    )
    state_token = (
        member.status,
        member.stop_time.isoformat() if member.stop_time is not None else None,
        member.response_path,
        member.artifacts_dir,
        member.plan_path,
        member.archived_plan_path,
        member.sdd_plan_path,
        member.epic_bead_id,
        member.phase_bead_id,
        member.workspace_dir,
        member.workspace_num,
        json.dumps(member.step_output, sort_keys=True, default=str)
        if member.step_output is not None
        else None,
    )
    return (member.identity, state_token, path_token)


def _load_member_replies(
    member: Agent,
    member_label: str,
) -> tuple[ClanTextEntry, ...]:
    if not member.is_agent_entry and member.step_output is not None:
        body = format_output(member.step_output).strip()
        if body:
            return (_text_entry(member, member_label, "STEP OUTPUT", body),)

    chunks = member.get_timestamped_reply_chunks()
    if chunks:
        body = "\n\n".join(chunk.strip() for _, chunk in chunks if chunk.strip())
        if body:
            return (_text_entry(member, member_label, "AGENT CHAT", body),)
    live_reply = member.get_live_reply_content()
    if live_reply:
        return (_text_entry(member, member_label, "AGENT CHAT", live_reply),)
    response = member.get_response_content()
    if response:
        return (_text_entry(member, member_label, "AGENT REPLY", response),)
    chat = member.get_chat_response_content()
    if chat:
        return (_text_entry(member, member_label, "AGENT CHAT", chat),)
    return ()


def _load_member_prompts(
    member: Agent,
    member_label: str,
) -> tuple[ClanTextEntry, ...]:
    entries: list[ClanTextEntry] = []
    raw_xprompt = member.get_raw_xprompt_content()
    if raw_xprompt:
        entries.append(_text_entry(member, member_label, "AGENT XPROMPT", raw_xprompt))
    prompt = get_prompt_content(member)
    if prompt:
        entries.append(_text_entry(member, member_label, "AGENT PROMPT", prompt))
    return tuple(entries)


def _text_entry(
    member: Agent,
    member_label: str,
    kind: str,
    body: str,
) -> ClanTextEntry:
    normalized = body.strip()
    return ClanTextEntry(
        member_identity=member.identity,
        member_label=member_label,
        kind=kind,
        preview=first_meaningful_line(normalized),
        body=normalized,
    )


@dataclass(slots=True)
class _ContextAccumulator:
    key: str
    label: str
    member_labels: list[str]
    values: list[object]
    count: int = 0

    def add(self, member_label: str | None, value: object) -> None:
        if member_label and member_label not in self.member_labels:
            self.member_labels.append(member_label)
        if value not in self.values:
            self.values.append(value)
        self.count += 1

    def freeze(self) -> ClanContextEntry:
        return ClanContextEntry(
            key=self.key,
            label=self.label,
            member_labels=tuple(self.member_labels),
            count=self.count,
            values=tuple(self.values),
        )


def _add_context(
    accumulators: dict[str, OrderedDict[str, _ContextAccumulator]],
    lane: str,
    key: str,
    label: str,
    member_label: str | None,
    value: object,
) -> None:
    entries = accumulators[lane]
    accumulator = entries.get(key)
    if accumulator is None:
        accumulator = _ContextAccumulator(
            key=key,
            label=label,
            member_labels=[],
            values=[],
        )
        entries[key] = accumulator
    elif len(label) > len(accumulator.label):
        # Prefer an enriched label over the path/id-only in-memory seed.
        accumulator.label = label
    accumulator.add(member_label, value)


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


def _direct_artifact_sources(artifact_root: Path) -> tuple[Path, ...]:
    paths = [artifact_root]
    try:
        paths.extend(
            entry
            for entry in artifact_root.iterdir()
            if entry.is_file() or entry.is_dir()
        )
    except OSError:
        pass
    return tuple(paths)


def _chat_source_paths(artifact_root: Path) -> tuple[Path, ...]:
    meta_path = artifact_root / "agent_meta.json"
    data = get_global_cache().read_json(str(meta_path))
    if not isinstance(data, dict):
        return ()
    chat_path = data.get("chat_path")
    if not isinstance(chat_path, str) or not chat_path:
        return ()
    return (Path(os.path.expanduser(chat_path)),)


def _audit_log_paths(member: Agent) -> tuple[Path, ...]:
    try:
        context_path = (
            Path(member.workspace_dir) if member.workspace_dir else Path.cwd()
        )
        project = project_memory_name(context_path)
    except Exception:
        return ()
    return (memory_read_log_path(project), skill_use_log_path(project))


def _path_signature(path: Path) -> tuple[str, int, int]:
    try:
        normalized = path.resolve(strict=False)
    except OSError:
        normalized = path.absolute()
    try:
        stat = normalized.stat()
    except OSError:
        return (str(normalized), 0, 0)
    return (str(normalized), stat.st_mtime_ns, stat.st_size)


def _path_key(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve(strict=False))
    except OSError:
        return os.path.normpath(os.path.expanduser(path))


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
