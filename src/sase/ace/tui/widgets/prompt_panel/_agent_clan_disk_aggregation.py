"""Cross-member aggregation for disk-backed clan detail sections."""

from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.ace.tui.tools.slow import select_slow_tool_calls

from ...models._agent_clan_sections import (
    CLAN_CONTEXT_LANE_ORDER,
    ClanContextEntry,
    ClanContextLane,
    ClanDiskMemberSnapshot,
    ClanInMemorySnapshot,
    ClanSlowToolEntry,
    first_meaningful_line,
)
from ...models.agent import Agent
from ..file_panel._linked_deltas import LinkedDeltaGroup
from ._agent_clan_commits import aggregate_clan_commit_lane


def aggregate_clan_context_lanes(
    in_memory: ClanInMemorySnapshot,
    members: tuple[ClanDiskMemberSnapshot, ...],
    *,
    member_rows: Collection[Agent] = (),
) -> tuple[ClanContextLane, ...]:
    """De-duplicate context entries while preserving lane and member order."""
    accumulators: dict[str, OrderedDict[str, _ContextAccumulator]] = {
        label: OrderedDict() for label in CLAN_CONTEXT_LANE_ORDER
    }
    member_labels = {member.identity: member.label for member in in_memory.members}
    commit_lane = aggregate_clan_commit_lane(member_rows, labels=member_labels)

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
        if summary.bead_summary is not None:
            bead = summary.bead_summary
            label = bead.id
            preview = first_meaningful_line(bead.title or bead.description or "")
            if preview:
                label += f" · {preview}"
            _add_context(
                accumulators,
                "BEAD",
                bead.id,
                label,
                member_label,
                bead,
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
                delta_group = LinkedDeltaGroup(
                    repo_name=group.repo_name,
                    workspace_dir=group.workspace_dir,
                    entries=(delta,),
                    kind=group.kind,
                )
                _add_context(
                    accumulators,
                    "ARTIFACTS",
                    key,
                    f"{group.repo_name}/{delta.path}",
                    member_label,
                    delta_group,
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
        entries = (
            commit_lane.entries
            if lane_label == "COMMITS" and commit_lane is not None
            else tuple(
                accumulator.freeze()
                for accumulator in accumulators[lane_label].values()
            )
        )
        if entries:
            lanes.append(ClanContextLane(label=lane_label, entries=entries))
    return tuple(lanes)


def aggregate_clan_slow_tool_calls(
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


def _path_key(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve(strict=False))
    except OSError:
        return os.path.normpath(os.path.expanduser(path))
