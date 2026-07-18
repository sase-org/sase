"""Shared numbered member-roster rendering for container detail panels."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from rich.text import Text

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    status_bucket_for_values,
)

from ...models._agent_clan_sections import first_meaningful_line
from ...models.agent import AgentType
from ...models.fold_state import FoldLevel
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE
from ._helpers import append_section_heading

type MemberIdentity = tuple[AgentType, str, str | None]

MEMBER_ROSTER_SECTION_ID = "members"
MEMBER_ROSTER_LIMIT = 100

_ROSTER_RULE = "━" * 50
_MEMBER_KIND_STYLE = "italic #AF87FF"
_MEMBER_MODEL_STYLE = "#5FD7FF"
_MEMBER_DURATION_STYLE = "dim #D7D7FF"
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
    digest: _MemberRosterDigest | None = None


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
    digest: _MemberRosterDigest | None = None
    children: tuple[MemberRosterChild, ...] = ()


@dataclass(frozen=True, slots=True)
class _MemberJumpTarget:
    """The agent-list target represented by one rendered number chip."""

    number: str
    member_identity: MemberIdentity
    kind: str


@dataclass(frozen=True, slots=True)
class MemberJumpMap:
    """The exact number-to-member mapping published by a rendered roster."""

    container_identity: MemberIdentity
    targets: tuple[_MemberJumpTarget, ...]


def _member_roster_anchor_id(presented_name: str) -> str:
    """Return the stable section anchor for one presented member row."""
    return f"member:{presented_name}"


def append_member_roster(
    text: Text,
    *,
    container_identity: MemberIdentity,
    entries: Sequence[MemberRosterEntry],
    title: str,
    accent: str,
    panel_level: FoldLevel,
    section_fold_overrides: Mapping[str, FoldLevel] | None = None,
) -> MemberJumpMap:
    """Append a numbered roster and return the jump map rendered from it."""
    ordered_entries = tuple(entries)
    if not ordered_entries:
        return MemberJumpMap(container_identity=container_identity, targets=())

    overrides = section_fold_overrides or {}
    roster_level = overrides.get(MEMBER_ROSTER_SECTION_ID, panel_level)
    _append_roster_heading(
        text,
        title=title,
        count=len(ordered_entries),
        level=roster_level,
        accent=accent,
    )

    number_width = 1 if len(ordered_entries) <= 10 else 2
    targets: list[_MemberJumpTarget] = []
    for index, entry in enumerate(ordered_entries[:MEMBER_ROSTER_LIMIT]):
        number = f"{index:0{number_width}d}"
        anchor_id = _member_roster_anchor_id(entry.presented_name)
        entry_level = overrides.get(anchor_id, roster_level)
        _append_numbered_entry(
            text,
            number=number,
            entry=entry,
            anchor_id=anchor_id,
            level=entry_level,
            accent=accent,
        )
        targets.append(
            _MemberJumpTarget(
                number=number,
                member_identity=entry.identity,
                kind=entry.kind,
            )
        )

    hidden_count = len(ordered_entries) - MEMBER_ROSTER_LIMIT
    if hidden_count > 0:
        text.append(
            f"… +{hidden_count} more members (not numbered)\n",
            style="dim italic",
        )

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
) -> None:
    text.append("\n")
    text.append(_ROSTER_RULE + "\n", style=f"bold {accent}")
    heading = Text()
    heading.append(f"{_FOLD_CHARS[level]} ", style=_FOLD_STYLES[level])
    heading.append("❖ ", style=f"bold {accent}")
    heading.append(title, style=f"bold {accent} underline")
    heading.append(f" · {count}", style="dim")
    append_section_heading(
        text,
        heading,
        section_id=MEMBER_ROSTER_SECTION_ID,
    )


def _append_numbered_entry(
    text: Text,
    *,
    number: str,
    entry: MemberRosterEntry,
    anchor_id: str,
    level: FoldLevel,
    accent: str,
) -> None:
    line = Text()
    line.append(f" {number} ", style=f"bold black on {accent}")
    line.append(" ")
    _append_member_fields(
        line,
        label=entry.label,
        kind=entry.kind,
        status=entry.status,
        model=entry.model,
        duration=entry.duration,
        annotations=_member_annotations(entry.digest, level),
    )
    append_section_heading(text, line, section_id=anchor_id)

    for index, child in enumerate(entry.children):
        branch = "    └─ " if index == len(entry.children) - 1 else "    ├─ "
        text.append(branch, style="dim #808080")
        _append_member_fields(
            text,
            label=child.label,
            kind=child.kind,
            status=child.status,
            model=child.model,
            duration=child.duration,
            annotations=_member_annotations(child.digest, level),
        )
        text.append("\n")


def _append_member_fields(
    text: Text,
    *,
    label: str,
    kind: str,
    status: str,
    model: str,
    duration: str,
    annotations: Sequence[str],
) -> None:
    bucket = status_bucket_for_values(status)
    glyph = AGENT_STATUS_BUCKET_GLYPHS[bucket]
    text.append(label, style=_AGENT_NAME_ANNOTATION_STYLE)
    text.append(" · ", style="dim")
    text.append(kind, style=_MEMBER_KIND_STYLE)
    text.append(" · ", style="dim")
    text.append(f"{glyph} {status}", style=_MEMBER_STATUS_STYLES[bucket])
    text.append(" · ", style="dim")
    text.append(model, style=_MEMBER_MODEL_STYLE)
    text.append(" · ", style="dim")
    text.append(duration, style=_MEMBER_DURATION_STYLE)
    if annotations:
        text.append(" · ", style="dim")
        text.append(" · ".join(annotations), style="dim #BCAFD7")


def _member_annotations(
    digest: _MemberRosterDigest | None,
    level: FoldLevel,
) -> tuple[str, ...]:
    if digest is None or level == FoldLevel.COLLAPSED:
        return ()
    annotations: list[str] = []
    activity = first_meaningful_line(digest.activity or "", max_chars=64)
    if activity:
        annotations.append(activity)
    if digest.waiting:
        annotations.append("wait " + "; ".join(digest.waiting))
    if digest.retry:
        annotations.append("retry " + "; ".join(digest.retry))
    if level == FoldLevel.FULLY_EXPANDED:
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
    return tuple(annotations)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


__all__ = [
    "MEMBER_ROSTER_LIMIT",
    "MEMBER_ROSTER_SECTION_ID",
    "MemberJumpMap",
    "MemberRosterChild",
    "MemberRosterEntry",
    "append_member_roster",
    "member_jump_map_publisher_for",
]
