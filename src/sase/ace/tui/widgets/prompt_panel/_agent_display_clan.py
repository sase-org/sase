"""Aggregate detail rendering for synthetic agent-clan rows."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from datetime import datetime

from rich.errors import MarkupError
from rich.text import Text

from sase.agent.status_buckets import status_bucket_for_values

from ...agent_count_chip import format_agent_count_chip
from ...models._agent_clan import clan_member_counts
from ...models._agent_clan_sections import (
    ClanDiskSection,
    ClanSectionSnapshot,
    aggregate_clan_in_memory,
)
from ...models.agent import Agent, AgentType
from ...models.fold_scale import CLAN_FOLD_SCALE, effective_fold_level
from ...models.fold_state import FoldLevel
from .._agent_list_styling import _CLAN_IDENTITY_COLOR, _CLAN_NAME_STYLE
from ._agent_display_clan_roster import (
    clan_roster_entries,
    duration_label,
    family_children,
    family_rows,
    ordered_clan_members,
)
from ._agent_display_clan_sections import (
    append_context_section,
    append_errors_section,
    append_slow_tool_calls_section,
    append_text_section,
    append_variables_section,
    disk_section_loaded,
    minimal_context_lanes,
)
from ._fold_language import append_fold_header_line, append_scanning_tail
from ._member_roster import MemberJumpMap, append_member_roster

_CLAN_HEADING_STYLE = f"bold {_CLAN_IDENTITY_COLOR} underline"
_FIELD_LABEL_STYLE = "bold #87D7FF"
_MEMBER_STATUS_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #FFD700",
    "Queued": "bold #5F87FF",
    "Waiting": "bold #AF87FF",
    "Failed": "bold #FF5F5F",
    "Done": "bold #5FD75F",
}
_DISK_SECTION_IDS: dict[str, ClanDiskSection] = {
    "replies": "replies",
    "context": "context",
    "slow-tool-calls": "slow-tool-calls",
    "prompts": "prompts",
}


def _effective_fold_level(
    section_id: str,
    panel_level: FoldLevel,
    overrides: Mapping[str, FoldLevel],
) -> FoldLevel:
    return effective_fold_level(
        overrides.get(section_id, panel_level),
        CLAN_FOLD_SCALE,
    )


def clan_disk_sections_for_fold_state(
    panel_level: FoldLevel,
    overrides: Mapping[str, FoldLevel] | None = None,
) -> frozenset[ClanDiskSection]:
    """Return sections needed to discover presence or render open bodies.

    Even a collapsed clan summary needs one off-thread enrichment pass to
    distinguish represented disk-backed sections from known-empty ones.  The
    first paint remains pure: unknown sections stay hidden behind the shared
    scanning tail while the existing worker populates the mtime-keyed cache.
    """
    del panel_level, overrides
    return frozenset(_DISK_SECTION_IDS.values())


def panel_fold_state_from_widget(
    widget: object,
) -> tuple[FoldLevel, Mapping[str, FoldLevel]]:
    """Read shared detail-panel fold state without coupling renderers to App."""
    try:
        app = widget.app  # type: ignore[attr-defined]
    except Exception:
        return FoldLevel.COLLAPSED, {}
    panel_level = getattr(app, "panel_fold_level", FoldLevel.COLLAPSED)
    if not isinstance(panel_level, FoldLevel):
        panel_level = FoldLevel.COLLAPSED
    manager = getattr(app, "_panel_fold_overrides", None)
    snapshot = getattr(manager, "snapshot", None)
    overrides = snapshot() if callable(snapshot) else {}
    return panel_level, overrides


# Compatibility name retained for callers and tests from the clan-only era.
clan_fold_state_from_widget = panel_fold_state_from_widget


def build_clan_detail_text(
    agent: Agent,
    *,
    now: datetime | None = None,
    unread_ids: Collection[tuple[AgentType, str, str | None]] = (),
    snapshot: ClanSectionSnapshot | None = None,
    fold_level: FoldLevel = FoldLevel.COLLAPSED,
    section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    member_jump_map_publisher: Callable[[MemberJumpMap], None] | None = None,
) -> Text:
    """Build a fold-aware clan detail document without filesystem access."""
    fold_level = effective_fold_level(fold_level, CLAN_FOLD_SCALE)
    snapshot = snapshot or ClanSectionSnapshot(
        in_memory=aggregate_clan_in_memory(agent)
    )
    overrides = section_fold_overrides or {}
    members = ordered_clan_members(agent)
    family_members = tuple(member for member in members if family_children(member))
    agent_count = sum(
        max(1, len(family_rows(member, family_children(member))))
        if family_children(member)
        else 1
        for member in members
    )

    text = Text()
    text.append("CLAN\n", style=_CLAN_HEADING_STYLE)
    text.append("Name: ", style=_FIELD_LABEL_STYLE)
    text.append(
        f"{agent.agent_clan or agent.display_name}\n",
        style=_CLAN_NAME_STYLE,
    )

    if agent.clan_tribes:
        text.append("Tribes: ", style=_FIELD_LABEL_STYLE)
        for index, tribe in enumerate(agent.clan_tribes):
            if index:
                text.append(" ")
            text.append(f"@{tribe}", style="bold #FFD75F")
        text.append("\n")

    counts = clan_member_counts(agent, unread_ids)
    text.append("Status: ", style=_FIELD_LABEL_STYLE)
    status_bucket = status_bucket_for_values(agent.status)
    text.append(agent.display_status, style=_MEMBER_STATUS_STYLES[status_bucket])
    chip = format_agent_count_chip(
        stopped=counts.awaiting,
        running=counts.running,
        queued=counts.queued,
        waiting=counts.waiting,
        failed=counts.failed,
        unread=counts.unread,
        done=counts.done,
    )
    if chip.cell_len:
        text.append(" ")
        text.append_text(chip)
    text.append("\n")

    text.append("Runtime: ", style=_FIELD_LABEL_STYLE)
    text.append(f"{duration_label(agent, now=now)}\n", style="bold #BCBCBC")

    family_count = len(family_members)
    text.append("Members: ", style=_FIELD_LABEL_STYLE)
    member_parts = [f"{agent_count} agent{'s' if agent_count != 1 else ''}"]
    if family_count:
        member_parts.append(
            f"{family_count} famil{'ies' if family_count != 1 else 'y'}"
        )
    text.append(" · ".join(member_parts) + "\n", style="#D7D7FF")

    append_fold_header_line(text, level=fold_level, scale=CLAN_FOLD_SCALE)

    roster_entries = clan_roster_entries(
        agent,
        members,
        now=now,
        digests=snapshot.in_memory.members,
    )
    jump_map = append_member_roster(
        text,
        container_identity=agent.identity,
        entries=roster_entries,
        title="CLAN MEMBERS",
        accent=_CLAN_IDENTITY_COLOR,
        panel_level=fold_level,
        section_fold_overrides=overrides,
        fold_scale=CLAN_FOLD_SCALE,
    )
    if member_jump_map_publisher is not None:
        member_jump_map_publisher(jump_map)

    if agent.clan_summary:
        text.append("\n")
        try:
            summary = Text.from_markup(agent.clan_summary)
        except MarkupError:
            summary = Text(agent.clan_summary)
        text.append_text(summary)
        text.append("\n\n")

    errors = snapshot.in_memory.errors
    if errors:
        append_errors_section(
            text,
            errors,
            level=_effective_fold_level("errors", fold_level, overrides),
        )

    output_variables = snapshot.in_memory.output_variables
    if output_variables:
        append_variables_section(
            text,
            output_variables,
            title="OUTPUT VARIABLES",
            section_id="output-variables",
            level=_effective_fold_level(
                "output-variables",
                fold_level,
                overrides,
            ),
        )

    workflow_variables = snapshot.in_memory.workflow_variables
    if workflow_variables:
        append_variables_section(
            text,
            workflow_variables,
            title="WORKFLOW VARIABLES",
            section_id="workflow-variables",
            level=_effective_fold_level(
                "workflow-variables",
                fold_level,
                overrides,
            ),
        )

    required_disk_sections = clan_disk_sections_for_fold_state(
        fold_level,
        overrides,
    )
    disk = snapshot.disk

    replies = disk.replies if disk is not None else ()
    if replies and disk_section_loaded(snapshot, "replies"):
        append_text_section(
            text,
            replies,
            title="REPLIES",
            section_id="replies",
            level=_effective_fold_level("replies", fold_level, overrides),
        )

    context_loaded = disk_section_loaded(snapshot, "context")
    context_lanes = (
        disk.context_lanes
        if disk is not None and context_loaded
        else minimal_context_lanes(snapshot)
    )
    if context_lanes:
        append_context_section(
            text,
            context_lanes,
            level=_effective_fold_level("context", fold_level, overrides),
            count_known=context_loaded,
        )

    slow_tool_calls = disk.slow_tool_calls if disk is not None else ()
    if slow_tool_calls and disk_section_loaded(snapshot, "slow-tool-calls"):
        append_slow_tool_calls_section(
            text,
            slow_tool_calls,
            level=_effective_fold_level(
                "slow-tool-calls",
                fold_level,
                overrides,
            ),
        )

    prompts = disk.prompts if disk is not None else ()
    if prompts and disk_section_loaded(snapshot, "prompts"):
        append_text_section(
            text,
            prompts,
            title="PROMPTS",
            section_id="prompts",
            level=_effective_fold_level("prompts", fold_level, overrides),
        )
    loaded_disk_sections = disk.loaded_sections if disk is not None else frozenset()
    if snapshot.loading_sections.intersection(required_disk_sections) or not (
        required_disk_sections.issubset(loaded_disk_sections)
    ):
        append_scanning_tail(text)
    return text


__all__ = [
    "build_clan_detail_text",
    "clan_disk_sections_for_fold_state",
    "clan_fold_state_from_widget",
    "panel_fold_state_from_widget",
]
