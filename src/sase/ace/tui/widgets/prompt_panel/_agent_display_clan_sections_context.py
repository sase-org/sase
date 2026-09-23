"""Fold-aware SASE CONTEXT section for clan detail rows."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.glossary_reads import GlossaryReadDisplayEvent
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent

from ...models._agent_clan_sections import (
    CLAN_CONTEXT_LANE_ORDER,
    ClanContextEntry,
    ClanContextLane,
    ClanDiskSection,
    ClanSectionSnapshot,
    clan_section_member_rows,
)
from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from ._agent_clan_commits import aggregate_clan_commit_lane
from ._agent_display_clan_context import clan_context_entry_hint_target
from ._agent_display_clan_sections_common import (
    append_fold_heading,
    append_triage_line,
    _CLAN_BODY_STYLE,
)
from ._agent_display_state import CommitViewSpec, HeaderHintState
from ._agent_glossary_reads import register_glossary_read_report_hint
from ._agent_memory_reads import register_memory_read_report_hint


def append_context_section(
    text: Text,
    lanes: tuple[ClanContextLane, ...],
    *,
    level: FoldLevel,
    count_known: bool,
    hint_state: HeaderHintState | None = None,
    member_workspaces: dict[str, str | None] | None = None,
    fallback_workspace: str | None = None,
) -> None:
    """Render SASE CONTEXT as headings, per-lane digests, or full lane items."""
    count = sum(len(lane.entries) for lane in lanes) if count_known else None
    append_fold_heading(
        text,
        title="SASE CONTEXT",
        section_id="context",
        level=level,
        count=count,
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        for lane in lanes:
            labels = [entry.label for entry in lane.entries[:4]]
            hidden = len(lane.entries) - len(labels)
            digest = ", ".join(labels)
            if hidden:
                digest += f", +{hidden} more"
            append_triage_line(text, lane.label, digest or "—")
        return
    for lane in lanes:
        text.append(f"{lane.label}\n", style="bold #87D7FF")
        for entry in lane.entries:
            text.append("  • ", style="dim #D75FFF")
            commit_spec = (
                next(
                    (
                        value
                        for value in entry.values
                        if isinstance(value, CommitViewSpec)
                    ),
                    None,
                )
                if lane.label == "COMMITS"
                else None
            )
            glossary_display = (
                next(
                    (
                        value
                        for value in entry.values
                        if isinstance(value, GlossaryReadDisplayEvent)
                    ),
                    None,
                )
                if lane.label == "GLOSSARY"
                else None
            )
            memory_display = (
                next(
                    (
                        value
                        for value in entry.values
                        if isinstance(value, MemoryReadDisplayEvent)
                    ),
                    None,
                )
                if lane.label == "MEMORY"
                else None
            )
            hint_target = (
                clan_context_entry_hint_target(
                    lane.label,
                    entry,
                    member_workspaces=member_workspaces or {},
                    fallback_workspace=fallback_workspace,
                )
                if hint_state is not None
                and commit_spec is None
                and glossary_display is None
                and memory_display is None
                else None
            )
            if commit_spec is not None and hint_state is not None:
                hint_number = hint_state.hint_counter
                text.append(f"[{hint_number}] ", style="bold #FFFF00")
                hint_state.commit_views[hint_number] = commit_spec
                hint_state.hint_counter += 1
            elif glossary_display is not None and hint_state is not None:
                marker = register_glossary_read_report_hint(
                    glossary_display, hint_state=hint_state
                )
                if marker is not None:
                    text.append(f"{marker} ", style="bold #FFFF00")
            elif memory_display is not None and hint_state is not None:
                marker = register_memory_read_report_hint(
                    memory_display, hint_state=hint_state
                )
                if marker is not None:
                    text.append(f"{marker} ", style="bold #FFFF00")
            elif hint_target is not None and hint_state is not None:
                hint_number = hint_state.hint_counter
                text.append(f"[{hint_number}] ", style="bold #FFFF00")
                hint_state.hint_mappings[hint_number] = hint_target
                hint_state.hint_counter += 1
            text.append(entry.label, style=_CLAN_BODY_STYLE)
            if entry.count > 1:
                text.append(f" ×{entry.count}", style="dim")
            if entry.member_labels:
                text.append(
                    " · " + ", ".join(entry.member_labels),
                    style="dim #AF87FF",
                )
            text.append("\n")


def disk_section_loaded(
    snapshot: ClanSectionSnapshot,
    section: ClanDiskSection,
) -> bool:
    """Return whether the disk snapshot contains a requested clan section."""
    return snapshot.disk is not None and section in snapshot.disk.loaded_sections


def minimal_context_lanes(
    snapshot: ClanSectionSnapshot,
    agent: Agent,
) -> tuple[ClanContextLane, ...]:
    """Build context lanes available before disk enrichment completes."""
    in_memory = snapshot.in_memory
    lanes_by_label: dict[str, ClanContextLane] = {}
    if in_memory.bead_ids:
        lanes_by_label["BEAD"] = ClanContextLane(
            label="BEAD",
            entries=tuple(
                ClanContextEntry(key=value, label=value, member_labels=())
                for value in in_memory.bead_ids
            ),
        )
    if in_memory.plan_paths:
        lanes_by_label["PLAN"] = ClanContextLane(
            label="PLAN",
            entries=tuple(
                ClanContextEntry(
                    key=value,
                    label=value,
                    member_labels=(),
                    values=(value,),
                )
                for value in in_memory.plan_paths
            ),
        )
    commit_lane = aggregate_clan_commit_lane(
        clan_section_member_rows(agent),
        labels={member.identity: member.label for member in in_memory.members},
    )
    if commit_lane is not None:
        lanes_by_label["COMMITS"] = commit_lane
    if in_memory.workspace_numbers:
        lanes_by_label["WORKSPACES"] = ClanContextLane(
            label="WORKSPACES",
            entries=tuple(
                ClanContextEntry(
                    key=f"workspace:{value}",
                    label=f"workspace {value}",
                    member_labels=(),
                )
                for value in in_memory.workspace_numbers
            ),
        )
    return tuple(
        lanes_by_label[label]
        for label in CLAN_CONTEXT_LANE_ORDER
        if label in lanes_by_label
    )
