"""Shared numbered member-roster rendering for container detail panels."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from rich.text import Text

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    status_bucket_for_values,
)
from sase.core.time import format_local

from ...models._agent_clan_sections import first_meaningful_line
from ...models.agent import AgentType
from ...models.agent_panels import PanelKey
from ...models.fold_scale import (
    CLAN_FOLD_SCALE,
    FoldScale,
    TRIBE_FOLD_SCALE,
    effective_fold_level,
)
from ...models.fold_state import FoldLevel
from ...agent_count_chip import format_agent_count_chip
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE
from ._fold_language import append_fold_glyph, fold_count_style
from ._helpers import append_fold_anchor, append_section_heading

type MemberIdentity = tuple[AgentType, str, str | None]
type MemberJumpContainerIdentity = MemberIdentity | tuple[Literal["panel"], PanelKey]
type MemberJumpRole = Literal["member", "neighbor", "dismissed"]

MEMBER_ROSTER_SECTION_ID = "members"
MEMBER_ROSTER_LIMIT = 100
MEMBER_ENTRY_CURSOR_GLYPH = "❯"
MEMBER_ENTRY_CURSOR_STYLE = "bold #FFFFFF"

_ROSTER_RULE = "━" * 50
_MEMBER_KIND_STYLE = "italic #AF87FF"
_MEMBER_MODEL_STYLE = "#5FD7FF"
_MEMBER_DURATION_STYLE = "dim #D7D7FF"
_MEMBER_STATUS_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #FFD700",
    "Queued": "bold #5F87FF",
    "Waiting": "bold #AF87FF",
    "Failed": "bold #FF5F5F",
    "Done": "bold #5FD75F",
}


class _MemberRosterDigest(Protocol):
    """In-memory member facts consumed by the shared roster renderer."""

    @property
    def activity(self) -> str | None: ...

    @property
    def waiting(self) -> tuple[str, ...]: ...

    @property
    def retry(self) -> tuple[str, ...]: ...

    @property
    def workspace_num(self) -> int | None: ...

    @property
    def start_time(self) -> datetime | None: ...

    @property
    def run_start_time(self) -> datetime | None: ...

    @property
    def stop_time(self) -> datetime | None: ...

    @property
    def attempt_count(self) -> int: ...


@dataclass(frozen=True, slots=True)
class MemberRosterChild:
    """An unnumbered detail row nested beneath one roster entry."""

    label: str
    kind: str
    status: str
    model: str
    duration: str
    effective_bucket: str | None = None
    digest: _MemberRosterDigest | None = None
    is_marked: bool = False
    is_unread: bool = False


@dataclass(frozen=True, slots=True)
class MemberRosterStatusCounts:
    """Optional aggregate count chip rendered beside a roster unit."""

    stopped: int = 0
    running: int = 0
    queued: int = 0
    waiting: int = 0
    failed: int = 0
    unread: int = 0
    done: int = 0


@dataclass(frozen=True, slots=True)
class MemberRosterEntry:
    """One numbered, independently foldable member-roster entry."""

    identity: MemberIdentity
    presented_name: str
    label: str
    kind: str
    status: str
    model: str
    duration: str
    effective_bucket: str | None = None
    digest: _MemberRosterDigest | None = None
    children: tuple[MemberRosterChild, ...] = ()
    status_counts: MemberRosterStatusCounts | None = None
    is_marked: bool = False
    is_unread: bool = False
    group_label: str | None = None
    is_dismissed: bool = False
    target_role: MemberJumpRole | None = None
    is_entry_target: bool = False


@dataclass(slots=True)
class MemberJumpNumbering:
    """Digit allocator shared by every numbered roster in one panel document."""

    total: int
    capacity: int = MEMBER_ROSTER_LIMIT
    _taken: int = 0

    @property
    def width(self) -> int:
        """Return the shared number width for this document."""
        return 1 if self.total <= 10 else 2

    def take(self) -> str | None:
        """Return the next zero-padded number, or None when capacity is spent."""
        if self._taken >= self.capacity:
            return None
        number = f"{self._taken:0{self.width}d}"
        self._taken += 1
        return number


@dataclass(frozen=True, slots=True)
class _MemberJumpTarget:
    """The agent-list target represented by one rendered number chip."""

    number: str
    member_identity: MemberIdentity
    kind: str
    role: MemberJumpRole = "member"


@dataclass(frozen=True, slots=True)
class MemberJumpMap:
    """The exact number-to-member mapping published by a rendered roster."""

    container_identity: MemberJumpContainerIdentity
    targets: tuple[_MemberJumpTarget, ...]


def append_member_roster(
    text: Text,
    *,
    container_identity: MemberJumpContainerIdentity,
    entries: Sequence[MemberRosterEntry],
    title: str,
    accent: str,
    panel_level: FoldLevel,
    section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    fold_scale: FoldScale = CLAN_FOLD_SCALE,
    section_id: str = MEMBER_ROSTER_SECTION_ID,
    member_anchor_prefix: str = "member:",
    children_from_level: FoldLevel | None = None,
    full_annotations_from_level: FoldLevel = FoldLevel.FULLY_EXPANDED,
    numbering: MemberJumpNumbering | None = None,
    entry_limit: int | None = None,
    hidden_tail_label: str = "members",
    hidden_tail_hint: str = "not numbered",
    extra_tail: str | None = None,
    target_role: MemberJumpRole = "member",
    entry_cursor: bool = False,
    heading_suffix: Text | None = None,
) -> MemberJumpMap:
    """Append a numbered roster and return the jump map rendered from it."""
    ordered_entries = tuple(entries)
    if not ordered_entries:
        return MemberJumpMap(container_identity=container_identity, targets=())
    overrides = section_fold_overrides or {}
    roster_level = effective_fold_level(
        overrides.get(section_id, panel_level),
        fold_scale,
    )
    _append_roster_heading(
        text,
        title=title,
        count=len(ordered_entries),
        level=roster_level,
        accent=accent,
        section_id=section_id,
        suffix=heading_suffix,
    )
    numbering = numbering or MemberJumpNumbering(total=len(ordered_entries))
    limited_entries = (
        ordered_entries if entry_limit is None else ordered_entries[:entry_limit]
    )
    targets: list[_MemberJumpTarget] = []
    rendered_count = 0
    previous_group_label: str | None = None
    for entry in limited_entries:
        number = numbering.take()
        if number is None:
            break
        if entry.group_label is not None and entry.group_label != previous_group_label:
            text.append(f"  {entry.group_label}\n", style="dim italic #8787AF")
        previous_group_label = entry.group_label
        anchor_id = f"{member_anchor_prefix}{entry.presented_name}"
        entry_level = effective_fold_level(
            overrides.get(anchor_id, roster_level),
            fold_scale,
        )
        _append_numbered_entry(
            text,
            number=number,
            entry=entry,
            anchor_id=anchor_id,
            level=entry_level,
            accent=accent,
            children_from_level=children_from_level,
            full_annotations_from_level=full_annotations_from_level,
            entry_cursor=entry_cursor,
        )
        targets.append(
            _MemberJumpTarget(
                number=number,
                member_identity=entry.identity,
                kind=entry.kind,
                role=entry.target_role or target_role,
            )
        )
        rendered_count += 1

    hidden_count = len(ordered_entries) - rendered_count
    if hidden_count > 0:
        text.append(
            f"… +{hidden_count} more {hidden_tail_label} ({hidden_tail_hint})\n",
            style="dim italic",
        )
    if extra_tail is not None:
        text.append(extra_tail + "\n", style="dim italic")

    return MemberJumpMap(
        container_identity=container_identity,
        targets=tuple(targets),
    )


def merged_member_jump_map(
    container_identity: MemberJumpContainerIdentity,
    *maps: MemberJumpMap | None,
) -> MemberJumpMap:
    """Concatenate same-container maps into the one map a document publishes."""
    targets: list[_MemberJumpTarget] = []
    for jump_map in maps:
        if jump_map is None:
            continue
        if jump_map.container_identity != container_identity:
            raise ValueError("Cannot merge member jump maps for different containers")
        targets.extend(jump_map.targets)
    return MemberJumpMap(
        container_identity=container_identity,
        targets=tuple(targets),
    )


def _publish_member_jump_map(owner: object, jump_map: MemberJumpMap) -> None:
    """Publish one rendered jump map on its UI owner, keyed by container."""
    registry = getattr(owner, "_member_jump_maps", None)
    if not isinstance(registry, dict):
        return
    registry[jump_map.container_identity] = jump_map


def member_jump_map_publisher_for(
    owner: object | None,
) -> Callable[[MemberJumpMap], None] | None:
    """Return a render callback that publishes jump maps on ``owner``."""
    if owner is None:
        return None

    def _publish(jump_map: MemberJumpMap) -> None:
        _publish_member_jump_map(owner, jump_map)

    return _publish


def _append_roster_heading(
    text: Text,
    *,
    title: str,
    count: int,
    level: FoldLevel,
    accent: str,
    section_id: str,
    suffix: Text | None,
) -> None:
    text.append("\n")
    text.append(_ROSTER_RULE + "\n", style=f"bold {accent}")
    heading = Text()
    append_fold_glyph(heading, level)
    heading.append("❖ ", style=f"bold {accent}")
    heading.append(title, style=f"bold {accent} underline")
    heading.append(f" · {count}", style=fold_count_style(title))
    if suffix is not None:
        heading.append_text(suffix)
    append_section_heading(
        text,
        heading,
        section_id=section_id,
    )


def _append_numbered_entry(
    text: Text,
    *,
    number: str,
    entry: MemberRosterEntry,
    anchor_id: str,
    level: FoldLevel,
    accent: str,
    children_from_level: FoldLevel | None,
    full_annotations_from_level: FoldLevel,
    entry_cursor: bool,
) -> None:
    line = Text()
    if entry_cursor:
        if entry.is_entry_target:
            line.append(
                MEMBER_ENTRY_CURSOR_GLYPH + " ",
                style=MEMBER_ENTRY_CURSOR_STYLE,
            )
        else:
            line.append("  ")
    line.append(f" {number} ", style=f"bold black on {accent}")
    line.append(" ")
    _append_member_fields(
        line,
        label=entry.label,
        kind=entry.kind,
        status=entry.status,
        effective_bucket=entry.effective_bucket,
        model=entry.model,
        duration=entry.duration,
        annotations=_member_annotations(
            entry.digest,
            level,
            full_annotations_from_level=full_annotations_from_level,
        ),
        status_counts=entry.status_counts,
        is_marked=entry.is_marked,
        is_unread=entry.is_unread,
        is_dismissed=entry.is_dismissed,
    )
    append_fold_anchor(text, line, section_id=anchor_id)

    if children_from_level is not None and not _level_at_least(
        level,
        children_from_level,
    ):
        return
    for index, child in enumerate(entry.children):
        branch = "    └─ " if index == len(entry.children) - 1 else "    ├─ "
        if entry_cursor:
            text.append("  ")
        text.append(branch, style="dim #808080")
        _append_member_fields(
            text,
            label=child.label,
            kind=child.kind,
            status=child.status,
            effective_bucket=child.effective_bucket,
            model=child.model,
            duration=child.duration,
            annotations=_member_annotations(
                child.digest,
                level,
                full_annotations_from_level=full_annotations_from_level,
            ),
            status_counts=None,
            is_marked=child.is_marked,
            is_unread=child.is_unread,
            is_dismissed=False,
        )
        text.append("\n")


def _append_member_fields(
    text: Text,
    *,
    label: str,
    kind: str,
    status: str,
    effective_bucket: str | None,
    model: str,
    duration: str,
    annotations: Sequence[str],
    status_counts: MemberRosterStatusCounts | None,
    is_marked: bool,
    is_unread: bool,
    is_dismissed: bool,
) -> None:
    bucket = effective_bucket or status_bucket_for_values(status)
    glyph = AGENT_STATUS_BUCKET_GLYPHS[bucket]
    if is_marked:
        text.append("[✓] ", style="bold #00D700")
    if is_unread:
        text.append("❌ " if bucket == "Failed" else "✅ ", style="#5FD7FF")
    if is_dismissed:
        text.append("⊘ ", style="dim #FFAF00")
    text.append(label, style=_AGENT_NAME_ANNOTATION_STYLE)
    text.append(" · ", style="dim")
    text.append(kind, style=_MEMBER_KIND_STYLE)
    text.append(" · ", style="dim")
    text.append(f"{glyph} {status}", style=_MEMBER_STATUS_STYLES[bucket])
    text.append(" · ", style="dim")
    text.append(model, style=_MEMBER_MODEL_STYLE)
    text.append(" · ", style="dim")
    text.append(duration, style=_MEMBER_DURATION_STYLE)
    if status_counts is not None:
        chip = format_agent_count_chip(
            stopped=status_counts.stopped,
            running=status_counts.running,
            queued=status_counts.queued,
            waiting=status_counts.waiting,
            failed=status_counts.failed,
            unread=status_counts.unread,
            done=status_counts.done,
        )
        if chip.cell_len:
            text.append(" ")
            text.append_text(chip)
    rendered_annotations = (
        (*annotations, "dismissed") if is_dismissed else tuple(annotations)
    )
    if rendered_annotations:
        text.append(" · ", style="dim")
        text.append(" · ".join(rendered_annotations), style="dim #BCAFD7")


def _member_annotations(
    digest: _MemberRosterDigest | None,
    level: FoldLevel,
    *,
    full_annotations_from_level: FoldLevel,
) -> tuple[str, ...]:
    if digest is None:
        return ()
    extra_annotations = tuple(getattr(digest, "extra_annotations", ()))
    if level == FoldLevel.COLLAPSED:
        return extra_annotations
    annotations: list[str] = []
    activity = first_meaningful_line(digest.activity or "", max_chars=64)
    if activity:
        annotations.append(activity)
    if digest.waiting:
        annotations.append("wait " + "; ".join(digest.waiting))
    if digest.retry:
        annotations.append("retry " + "; ".join(digest.retry))
    if _level_at_least(level, full_annotations_from_level):
        if digest.workspace_num is not None:
            annotations.append(f"ws {digest.workspace_num}")
        if digest.start_time is not None:
            annotations.append("start " + _format_timestamp(digest.start_time))
        if digest.run_start_time is not None:
            annotations.append("run " + _format_timestamp(digest.run_start_time))
        if digest.stop_time is not None:
            annotations.append("stop " + _format_timestamp(digest.stop_time))
        annotations.append(
            f"{digest.attempt_count} attempt{'s' if digest.attempt_count != 1 else ''}"
        )
    annotations.extend(extra_annotations)
    return tuple(annotations)


def _level_at_least(level: FoldLevel, threshold: FoldLevel) -> bool:
    return TRIBE_FOLD_SCALE.index(level) >= TRIBE_FOLD_SCALE.index(threshold)


def _format_timestamp(value: datetime) -> str:
    return format_local(value, "%Y-%m-%d %H:%M:%S")


__all__ = [
    "MEMBER_ENTRY_CURSOR_GLYPH",
    "MEMBER_ENTRY_CURSOR_STYLE",
    "MEMBER_ROSTER_LIMIT",
    "MEMBER_ROSTER_SECTION_ID",
    "MemberJumpMap",
    "MemberJumpContainerIdentity",
    "MemberJumpNumbering",
    "MemberJumpRole",
    "MemberRosterChild",
    "MemberRosterEntry",
    "MemberRosterStatusCounts",
    "append_member_roster",
    "member_jump_map_publisher_for",
    "merged_member_jump_map",
]
