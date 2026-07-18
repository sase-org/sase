"""Aggregate detail rendering for synthetic agent-clan rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Mapping
from copy import copy
from datetime import datetime

from rich.syntax import Syntax
from rich.text import Text

from sase.agent.status_buckets import status_bucket_for_values

from ...agent_count_chip import format_agent_count_chip
from ...models._agent_clan import (
    aggregate_clan_status,
    clan_member_counts,
    clan_members,
)
from ...models._agent_clan_sections import (
    ClanContextEntry,
    ClanContextLane,
    ClanDiskSection,
    ClanErrorEntry,
    ClanMemberDigest,
    ClanSectionSnapshot,
    ClanSlowToolEntry,
    ClanTextEntry,
    ClanVariableEntry,
    aggregate_clan_in_memory,
    first_meaningful_line,
)
from ...models.agent import Agent, AgentType, compute_row_runtime
from ...models.fold_state import FoldLevel
from ...tools.slow import format_long_duration
from .._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _CLAN_IDENTITY_COLOR,
    _CLAN_NAME_STYLE,
)
from ._helpers import (
    append_major_section_divider,
    append_section_heading,
)
from ._member_roster import (
    MemberJumpMap,
    MemberRosterChild,
    MemberRosterEntry,
    append_member_roster,
)

_CLAN_HEADING_STYLE = f"bold {_CLAN_IDENTITY_COLOR} underline"
_FIELD_LABEL_STYLE = "bold #87D7FF"
_MEMBER_STATUS_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #FFD700",
    "Waiting": "bold #AF87FF",
    "Failed": "bold #FF5F5F",
    "Done": "bold #5FD75F",
}
_FOLD_CHARS: dict[FoldLevel, str] = {
    FoldLevel.COLLAPSED: "▸",
    FoldLevel.EXPANDED: "▾",
    FoldLevel.FULLY_EXPANDED: "▼",
}
_FOLD_STYLES: dict[FoldLevel, str] = {
    FoldLevel.COLLAPSED: "#5F5F5F",
    FoldLevel.EXPANDED: "#00D7AF",
    FoldLevel.FULLY_EXPANDED: "bold #87FFD7",
}
_FOLD_NUMBERS: dict[FoldLevel, int] = {
    FoldLevel.COLLAPSED: 1,
    FoldLevel.EXPANDED: 2,
    FoldLevel.FULLY_EXPANDED: 3,
}
_DISK_SECTION_IDS: dict[str, ClanDiskSection] = {
    "replies": "replies",
    "context": "context",
    "slow-tool-calls": "slow-tool-calls",
    "prompts": "prompts",
}
_TRIAGE_ENTRY_LIMIT = 8
_TRIAGE_SLOW_TOOL_LIMIT = 5
_CLAN_SECTION_HEADING_STYLE = "bold #D7AF5F underline"
_CLAN_MEMBER_SUBHEADING_STYLE = "bold #D75FFF"
_CLAN_BODY_STYLE = "#D7D7FF"


def _effective_fold_level(
    section_id: str,
    panel_level: FoldLevel,
    overrides: Mapping[str, FoldLevel],
) -> FoldLevel:
    return overrides.get(section_id, panel_level)


def clan_disk_sections_for_fold_state(
    panel_level: FoldLevel,
    overrides: Mapping[str, FoldLevel] | None = None,
) -> frozenset[ClanDiskSection]:
    """Return sections needed to discover presence or render open bodies.

    Even a collapsed clan summary needs one off-thread enrichment pass to
    distinguish represented disk-backed sections from known-empty ones.  The
    first paint remains pure: it renders these still-unknown headings without
    counts while the existing worker populates the mtime-keyed cache.
    """
    del panel_level, overrides
    return frozenset(_DISK_SECTION_IDS.values())


def clan_fold_state_from_widget(
    widget: object,
) -> tuple[FoldLevel, Mapping[str, FoldLevel]]:
    """Read the generic panel fold state without coupling the renderer to App."""
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


def _append_fold_heading(
    text: Text,
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
    count: int | None,
) -> None:
    append_major_section_divider(text)
    heading = Text()
    heading.append(f"{_FOLD_CHARS[level]} ", style=_FOLD_STYLES[level])
    heading.append(title, style=_CLAN_SECTION_HEADING_STYLE)
    if count is not None:
        heading.append(f" · {count}", style="dim")
    append_section_heading(text, heading, section_id=section_id)


def _ordered_members(agent: Agent) -> tuple[Agent, ...]:
    """Return direct clan members in deterministic launch order."""
    return tuple(
        sorted(
            clan_members(agent),
            key=lambda member: (
                member.start_time is None,
                (
                    member.start_time.isoformat()
                    if member.start_time is not None
                    else ""
                ),
                member.agent_name or member.display_name,
            ),
        )
    )


def _family_children(member: Agent) -> tuple[Agent, ...]:
    """Return sequential family members nested below a direct clan member."""
    return tuple(
        child
        for child in member.runtime_children
        if child.is_family_member_child and not child.agent_family_parallel
    )


def _family_rows(member: Agent, children: tuple[Agent, ...]) -> tuple[Agent, ...]:
    """Return real agent rows represented by one family aggregate line.

    Rename-on-attach gives the first real family member a ``--role`` name and
    retains it as the row that owns later ``parent_timestamp`` children. A
    legacy/root-shaped row whose name is exactly the family container is not
    repeated as a child line.
    """
    family_name = member.agent_family
    include_member = bool(
        member.agent_name and (not family_name or member.agent_name != family_name)
    )
    if include_member:
        return (member, *children)
    return children


def _row_name(agent: Agent) -> str:
    return agent.agent_name or agent.step_name or agent.display_name


def _hood_suffix(agent: Agent, clan_name: str) -> str:
    """Render a member identity relative to its clan hood."""
    name = _row_name(agent)
    prefix = f"{clan_name}."
    if name.startswith(prefix):
        return name[len(clan_name) :]
    return name


def _family_suffix(member: Agent, clan_name: str) -> str:
    family_name = member.agent_family or _row_name(member)
    prefix = f"{clan_name}."
    if family_name.startswith(prefix):
        return family_name[len(clan_name) :]
    return family_name


def _nested_family_suffix(
    member: Agent,
    family: Agent,
    clan_name: str,
) -> str:
    name = _row_name(member)
    family_name = family.agent_family or _row_name(family)
    if name.startswith(family_name) and len(name) > len(family_name):
        return name[len(family_name) :]
    return _hood_suffix(member, clan_name)


def _member_kind(member: Agent) -> str:
    if member.is_workflow_step_child or (
        member.agent_type == AgentType.WORKFLOW and not member.appears_as_agent
    ):
        return "step"
    return "agent"


def _model_label(members: tuple[Agent, ...]) -> str:
    models = tuple(dict.fromkeys(member.model for member in members if member.model))
    if not models:
        return "default"
    if len(models) == 1:
        return models[0]
    return "mixed"


def _member_model_label(member: Agent) -> str:
    """Use a workflow member's loaded agent step when the parent has no model."""
    if member.model:
        return member.model
    child_agents = tuple(
        child
        for child in member.runtime_children
        if child.is_agent_entry and child.model
    )
    return _model_label(child_agents)


def _leaf_for_runtime(member: Agent) -> Agent:
    """Return a shallow row view whose own interval is not masked by children."""
    if not member.runtime_children:
        return member
    leaf = copy(member)
    leaf.runtime_children = []
    return leaf


def _duration_label(member: Agent, *, now: datetime | None) -> str:
    _timestamp, elapsed = compute_row_runtime(member, now=now)
    return elapsed or "—"


def _family_duration_label(
    family: Agent,
    rows: tuple[Agent, ...],
    *,
    now: datetime | None,
) -> str:
    if not rows:
        return _duration_label(family, now=now)
    aggregate = copy(family)
    aggregate.runtime_children = [_leaf_for_runtime(row) for row in rows]
    return _duration_label(aggregate, now=now)


def _clan_roster_entries(
    agent: Agent,
    members: tuple[Agent, ...],
    *,
    now: datetime | None,
    digests: tuple[ClanMemberDigest, ...],
) -> tuple[MemberRosterEntry, ...]:
    """Adapt deterministic clan rows into shared roster entries."""
    clan_name = agent.agent_clan or agent.display_name
    digest_by_identity = {digest.identity: digest for digest in digests}
    entries: list[MemberRosterEntry] = []
    for member in members:
        children = _family_children(member)
        if not children:
            entries.append(
                MemberRosterEntry(
                    identity=member.identity,
                    presented_name=member.presented_agent_name or _row_name(member),
                    label=_hood_suffix(member, clan_name),
                    kind=_member_kind(member),
                    status=member.display_status,
                    model=_member_model_label(member),
                    duration=_duration_label(member, now=now),
                    digest=digest_by_identity.get(member.identity),
                )
            )
            continue

        rows = _family_rows(member, children)
        family_status = (
            aggregate_clan_status(row.status for row in rows) or member.display_status
        )
        roster_children = tuple(
            MemberRosterChild(
                label=_nested_family_suffix(family_member, member, clan_name),
                kind=_member_kind(family_member),
                status=family_member.display_status,
                model=family_member.model or "default",
                duration=_duration_label(
                    _leaf_for_runtime(family_member),
                    now=now,
                ),
                digest=digest_by_identity.get(family_member.identity),
            )
            for family_member in rows
        )
        entries.append(
            MemberRosterEntry(
                identity=member.identity,
                presented_name=(
                    member.presented_agent_name
                    or member.agent_family
                    or _row_name(member)
                ),
                label=_family_suffix(member, clan_name),
                kind="family",
                status=family_status,
                model=_model_label(rows or (member,)),
                duration=_family_duration_label(member, rows, now=now),
                digest=digest_by_identity.get(member.identity),
                children=roster_children,
            )
        )
    return tuple(entries)


def _append_errors_section(
    text: Text,
    entries: tuple[ClanErrorEntry, ...],
    *,
    level: FoldLevel,
) -> None:
    """Render ERRORS as count-only, triage previews, or full diagnostics."""
    _append_fold_heading(
        text,
        title="ERRORS",
        section_id="errors",
        level=level,
        count=len(entries),
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        for entry in entries[:_TRIAGE_ENTRY_LIMIT]:
            _append_triage_line(text, entry.member_label, entry.preview)
        _append_more_tail(text, len(entries), _TRIAGE_ENTRY_LIMIT)
        return
    for entry in entries:
        _append_member_subheading(text, entry.member_label)
        _append_full_body(text, entry.message, style="#FF8787")
        if entry.traceback:
            text.append("  traceback\n", style="bold #FF5F5F")
            _append_traceback(text, entry.traceback)


def _append_variables_section(
    text: Text,
    entries: tuple[ClanVariableEntry, ...],
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
) -> None:
    """Render variables as count-only, one-line assignments, or full values."""
    _append_fold_heading(
        text,
        title=title,
        section_id=section_id,
        level=level,
        count=len(entries),
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        for entry in entries[:_TRIAGE_ENTRY_LIMIT]:
            value = first_meaningful_line(entry.value, max_chars=96) or "—"
            _append_triage_line(
                text,
                f"{entry.member_label}.{entry.name}",
                value,
                separator=" = ",
            )
        _append_more_tail(text, len(entries), _TRIAGE_ENTRY_LIMIT)
        return
    grouped: dict[str, list[ClanVariableEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        _append_member_subheading(text, member_label)
        for entry in member_entries:
            text.append(f"  {entry.name}\n", style="bold #87D7FF")
            _append_full_body(text, entry.value, style=_CLAN_BODY_STYLE, indent="    ")


def _append_text_section(
    text: Text,
    entries: tuple[ClanTextEntry, ...],
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
    loading: bool,
) -> None:
    """Render reply/prompt bodies as headings, previews, or full member bodies."""
    count = len(entries) if entries or not loading else None
    _append_fold_heading(
        text,
        title=title,
        section_id=section_id,
        level=level,
        count=count,
    )
    if level == FoldLevel.COLLAPSED:
        return
    if not entries:
        _append_loading(text)
        return
    if level == FoldLevel.EXPANDED:
        for entry in entries[:_TRIAGE_ENTRY_LIMIT]:
            label = entry.member_label
            if entry.kind == "AGENT XPROMPT":
                label += " [XPROMPT]"
            _append_triage_line(
                text,
                label,
                entry.preview or "—",
                kind=entry.kind,
            )
        _append_more_tail(text, len(entries), _TRIAGE_ENTRY_LIMIT)
        return
    grouped: dict[str, list[ClanTextEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        _append_member_subheading(text, member_label)
        for entry in member_entries:
            kind_style = (
                "bold #AF87FF" if entry.kind == "AGENT XPROMPT" else "bold #87D7FF"
            )
            text.append(f"  {entry.kind}\n", style=kind_style)
            _append_full_body(text, entry.body, indent="    ")


def _append_context_section(
    text: Text,
    lanes: tuple[ClanContextLane, ...],
    *,
    level: FoldLevel,
    loading: bool,
    count_known: bool,
) -> None:
    """Render SASE CONTEXT as headings, per-lane digests, or full lane items."""
    count = sum(len(lane.entries) for lane in lanes) if count_known else None
    _append_fold_heading(
        text,
        title="SASE CONTEXT",
        section_id="context",
        level=level,
        count=count,
    )
    if level == FoldLevel.COLLAPSED:
        return
    if not lanes:
        _append_loading(text)
        return
    if level == FoldLevel.EXPANDED:
        for lane in lanes:
            labels = [entry.label for entry in lane.entries[:4]]
            hidden = len(lane.entries) - len(labels)
            digest = ", ".join(labels)
            if hidden:
                digest += f", +{hidden} more"
            _append_triage_line(text, lane.label, digest or "—")
        if loading:
            _append_loading(text, prefix="more context ")
        return
    for lane in lanes:
        text.append(f"{lane.label}\n", style="bold #87D7FF")
        for entry in lane.entries:
            text.append("  • ", style="dim #D75FFF")
            text.append(entry.label, style=_CLAN_BODY_STYLE)
            if entry.count > 1:
                text.append(f" ×{entry.count}", style="dim")
            if entry.member_labels:
                text.append(
                    " · " + ", ".join(entry.member_labels),
                    style="dim #AF87FF",
                )
            text.append("\n")
    if loading:
        _append_loading(text, prefix="more context ")


def _append_slow_tool_calls_section(
    text: Text,
    entries: tuple[ClanSlowToolEntry, ...],
    *,
    level: FoldLevel,
    loading: bool,
) -> None:
    """Render slow tools as headings, top-five triage rows, or all grouped calls."""
    count = len(entries) if entries or not loading else None
    _append_fold_heading(
        text,
        title="SLOW TOOL CALLS",
        section_id="slow-tool-calls",
        level=level,
        count=count,
    )
    if level == FoldLevel.COLLAPSED:
        return
    if not entries:
        _append_loading(text)
        return
    if level == FoldLevel.EXPANDED:
        for entry in entries[:_TRIAGE_SLOW_TOOL_LIMIT]:
            _append_slow_tool_line(text, entry)
        _append_more_tail(text, len(entries), _TRIAGE_SLOW_TOOL_LIMIT)
        return
    grouped: dict[str, list[ClanSlowToolEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        _append_member_subheading(text, member_label)
        for entry in member_entries:
            _append_slow_tool_line(text, entry, indent="  ")


def _append_slow_tool_line(
    text: Text,
    entry: ClanSlowToolEntry,
    *,
    indent: str = "",
) -> None:
    call = entry.call
    raw = call.entry
    state = (
        "running" if call.is_running else "incomplete" if call.did_not_complete else ""
    )
    target = raw.compact_target or raw.detail
    text.append(f"{indent}• ", style="dim #D75FFF")
    if not indent:
        text.append(entry.member_label, style=_AGENT_NAME_ANNOTATION_STYLE)
        text.append(" · ", style="dim")
    text.append(raw.display_tool_name, style="bold #87D7FF")
    text.append(
        " · " + format_long_duration(call.effective_duration_ms),
        style="bold #FFAF5F",
    )
    if state:
        text.append(f" · {state}", style="dim #FFAF87")
    if target:
        text.append(" · " + first_meaningful_line(target, max_chars=96), style="dim")
    text.append("\n")


def _append_triage_line(
    text: Text,
    label: str,
    body: str,
    *,
    separator: str = " · ",
    kind: str | None = None,
) -> None:
    text.append("• ", style="dim #D75FFF")
    text.append(label, style=_AGENT_NAME_ANNOTATION_STYLE)
    if kind:
        text.append(f" · {kind}", style="italic #AF87FF")
    text.append(separator, style="dim")
    text.append(
        first_meaningful_line(body, max_chars=120) or "—",
        style=_CLAN_BODY_STYLE,
    )
    text.append("\n")


def _append_member_subheading(text: Text, label: str) -> None:
    text.append(f"{label}\n", style=_CLAN_MEMBER_SUBHEADING_STYLE)


def _append_full_body(
    text: Text,
    body: str,
    *,
    style: str = _CLAN_BODY_STYLE,
    indent: str = "  ",
) -> None:
    lines = body.splitlines() or ["—"]
    for line in lines:
        text.append(indent, style="dim")
        text.append(line or " ", style=style)
        text.append("\n")


def _append_traceback(text: Text, traceback: str) -> None:
    """Append traceback text with the regular agent panel's pytb highlighting."""
    highlighted = Syntax(
        traceback,
        "pytb",
        theme="monokai",
        word_wrap=True,
    ).highlight(traceback)
    for line in highlighted.split("\n", allow_blank=True):
        text.append("  ", style="dim")
        text.append_text(line)
        text.append("\n")


def _append_more_tail(text: Text, total: int, shown: int) -> None:
    hidden = total - min(total, shown)
    if hidden > 0:
        text.append(f"  +{hidden} more\n", style="dim italic")


def _append_loading(text: Text, *, prefix: str = "") -> None:
    text.append(f"  {prefix}loading…\n", style="dim italic")


def _disk_section_loaded(
    snapshot: ClanSectionSnapshot,
    section: ClanDiskSection,
) -> bool:
    return snapshot.disk is not None and section in snapshot.disk.loaded_sections


def _minimal_context_lanes(
    snapshot: ClanSectionSnapshot,
) -> tuple[ClanContextLane, ...]:
    in_memory = snapshot.in_memory
    lanes: list[ClanContextLane] = []
    if in_memory.bead_ids:
        lanes.append(
            ClanContextLane(
                label="BEAD",
                entries=tuple(
                    ClanContextEntry(key=value, label=value, member_labels=())
                    for value in in_memory.bead_ids
                ),
            )
        )
    if in_memory.plan_paths:
        lanes.append(
            ClanContextLane(
                label="PLAN",
                entries=tuple(
                    ClanContextEntry(key=value, label=value, member_labels=())
                    for value in in_memory.plan_paths
                ),
            )
        )
    if in_memory.workspace_numbers:
        lanes.append(
            ClanContextLane(
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
        )
    return tuple(lanes)


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
    snapshot = snapshot or ClanSectionSnapshot(
        in_memory=aggregate_clan_in_memory(agent)
    )
    overrides = section_fold_overrides or {}
    members = _ordered_members(agent)
    family_rows = tuple(member for member in members if _family_children(member))
    agent_count = sum(
        max(1, len(_family_rows(member, _family_children(member))))
        if _family_children(member)
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

    text.append("Tribes: ", style=_FIELD_LABEL_STYLE)
    if agent.clan_tags:
        for index, tag in enumerate(agent.clan_tags):
            if index:
                text.append(" ")
            text.append(f"@{tag}", style="bold #FFD75F")
    else:
        text.append("—", style="dim")
    text.append("\n")

    counts = clan_member_counts(agent, unread_ids)
    text.append("Status: ", style=_FIELD_LABEL_STYLE)
    status_bucket = status_bucket_for_values(agent.status)
    text.append(agent.display_status, style=_MEMBER_STATUS_STYLES[status_bucket])
    chip = format_agent_count_chip(
        stopped=counts.awaiting,
        running=counts.running,
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
    text.append(f"{_duration_label(agent, now=now)}\n", style="bold #BCBCBC")

    family_count = len(family_rows)
    text.append("Members: ", style=_FIELD_LABEL_STYLE)
    text.append(
        f"{agent_count} agent{'s' if agent_count != 1 else ''}"
        f" · {family_count} famil{'ies' if family_count != 1 else 'y'}\n",
        style="#D7D7FF",
    )

    text.append("Fold: ", style=_FIELD_LABEL_STYLE)
    text.append(f"{_FOLD_NUMBERS[fold_level]}/3\n", style="dim #D75FFF")

    roster_entries = _clan_roster_entries(
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
    )
    if member_jump_map_publisher is not None:
        member_jump_map_publisher(jump_map)

    errors = snapshot.in_memory.errors
    if errors:
        _append_errors_section(
            text,
            errors,
            level=_effective_fold_level("errors", fold_level, overrides),
        )

    output_variables = snapshot.in_memory.output_variables
    if output_variables:
        _append_variables_section(
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
        _append_variables_section(
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
    replies_loading = "replies" in snapshot.loading_sections or (
        "replies" in required_disk_sections
        and not _disk_section_loaded(snapshot, "replies")
    )
    if replies or replies_loading:
        _append_text_section(
            text,
            replies,
            title="REPLIES",
            section_id="replies",
            level=_effective_fold_level("replies", fold_level, overrides),
            loading=replies_loading,
        )

    context_loaded = _disk_section_loaded(snapshot, "context")
    context_lanes = (
        disk.context_lanes
        if disk is not None and context_loaded
        else _minimal_context_lanes(snapshot)
    )
    context_loading = "context" in snapshot.loading_sections or (
        "context" in required_disk_sections and not context_loaded
    )
    if context_lanes or context_loading:
        _append_context_section(
            text,
            context_lanes,
            level=_effective_fold_level("context", fold_level, overrides),
            loading=context_loading,
            count_known=context_loaded,
        )

    slow_tool_calls = disk.slow_tool_calls if disk is not None else ()
    slow_tools_loading = "slow-tool-calls" in snapshot.loading_sections or (
        "slow-tool-calls" in required_disk_sections
        and not _disk_section_loaded(snapshot, "slow-tool-calls")
    )
    if slow_tool_calls or slow_tools_loading:
        _append_slow_tool_calls_section(
            text,
            slow_tool_calls,
            level=_effective_fold_level(
                "slow-tool-calls",
                fold_level,
                overrides,
            ),
            loading=slow_tools_loading,
        )

    prompts = disk.prompts if disk is not None else ()
    prompts_loading = "prompts" in snapshot.loading_sections or (
        "prompts" in required_disk_sections
        and not _disk_section_loaded(snapshot, "prompts")
    )
    if prompts or prompts_loading:
        _append_text_section(
            text,
            prompts,
            title="PROMPTS",
            section_id="prompts",
            level=_effective_fold_level("prompts", fold_level, overrides),
            loading=prompts_loading,
        )
    return text


__all__ = [
    "build_clan_detail_text",
    "clan_disk_sections_for_fold_state",
    "clan_fold_state_from_widget",
]
