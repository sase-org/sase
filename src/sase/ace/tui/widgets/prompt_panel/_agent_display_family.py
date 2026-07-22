"""Fold-aware family-container helpers for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import copy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich.text import Text

from ...models._agent_clan_sections import first_meaningful_line
from ...models.agent import Agent
from ...models.agent_family_members import (
    concrete_family_member_rows as family_member_rows,
    family_member_status_buckets,
)
from ...models.agent_time import compute_row_runtime
from ...models.fold_state import FoldLevel
from ...models.fold_scale import (
    FAMILY_FOLD_SCALE,
    effective_fold_level,
)
from ._agent_display_content import get_phase_label
from ._fold_language import append_fold_glyph, fold_count_style
from ._helpers import append_section_heading
from ._member_roster import (
    MemberJumpMap,
    MemberRosterEntry,
    append_member_roster,
)

FAMILY_IDENTITY_COLOR = "#00AFFF"
_FAMILY_ROSTER_TITLE = "FAMILY MEMBERS"

FAMILY_XPROMPT_SECTION_ID = "agent-xprompt"
FAMILY_PROMPT_SECTION_ID = "agent-prompt"
FAMILY_REPLY_SECTION_ID = "agent-reply"

_FAMILY_PREVIEW_LINE_LIMIT = 12
_FAMILY_REPLY_TAIL_LINE_LIMIT = 4


@dataclass(frozen=True, slots=True)
class _FamilyMemberDigest:
    """In-memory family-member facts consumed by the shared roster."""

    activity: str | None
    waiting: tuple[str, ...]
    retry: tuple[str, ...]
    workspace_num: int | None
    start_time: datetime | None
    run_start_time: datetime | None
    stop_time: datetime | None
    attempt_count: int


def effective_family_fold_level(
    section_id: str,
    panel_level: FoldLevel,
    overrides: Mapping[str, FoldLevel] | None = None,
) -> FoldLevel:
    """Resolve a family section override against the shared panel level."""
    level = (overrides or {}).get(section_id, panel_level)
    return effective_fold_level(level, FAMILY_FOLD_SCALE)


def append_family_fold_heading(
    text: Any,
    title: str,
    *,
    section_id: str,
    level: FoldLevel,
    count: int | None = None,
    style: str = "bold #D7AF5F underline",
) -> None:
    """Append one family-section heading carrying its effective fold glyph."""
    level = effective_fold_level(level, FAMILY_FOLD_SCALE)
    heading = Text()
    append_fold_glyph(heading, level)
    heading.append(title, style=style)
    if count is not None:
        heading.append(f" · {count}", style=fold_count_style(title))
    append_section_heading(text, heading, section_id=section_id)


def _family_roster_entries(
    agent: Agent,
    *,
    now: datetime | None = None,
) -> tuple[MemberRosterEntry, ...]:
    """Adapt a family chain into shared numbered roster entries."""
    family_name = agent.presented_agent_name or ""
    members = family_member_rows(agent)
    buckets = family_member_status_buckets(members)
    entries: list[MemberRosterEntry] = []
    for member, bucket in zip(members, buckets, strict=True):
        phase_label = get_phase_label(member)
        kind = "agent" if phase_label == "AGENT" else phase_label
        entries.append(
            MemberRosterEntry(
                identity=member.identity,
                presented_name=(
                    member.agent_name
                    or member.presented_agent_name
                    or member.role_suffix
                    or member.display_name
                ),
                label=_family_member_label(member, family_name),
                kind=kind,
                status=member.display_status,
                effective_bucket=bucket,
                model=member.model or "default",
                duration=_member_duration(member, now=now),
                digest=_family_member_digest(member),
            )
        )
    return tuple(entries)


def append_family_member_roster(
    text: Text,
    agent: Agent,
    *,
    panel_level: FoldLevel,
    section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    now: datetime | None = None,
    member_jump_map_publisher: Callable[[MemberJumpMap], None] | None = None,
) -> MemberJumpMap:
    """Render and optionally publish a family container's numbered roster."""
    jump_map = append_member_roster(
        text,
        container_identity=agent.identity,
        entries=_family_roster_entries(agent, now=now),
        title=_FAMILY_ROSTER_TITLE,
        accent=FAMILY_IDENTITY_COLOR,
        panel_level=panel_level,
        section_fold_overrides=section_fold_overrides,
        fold_scale=FAMILY_FOLD_SCALE,
    )
    if member_jump_map_publisher is not None:
        member_jump_map_publisher(jump_map)
    return jump_map


def bounded_content_preview(
    content: str,
    *,
    line_limit: int = _FAMILY_PREVIEW_LINE_LIMIT,
) -> Text:
    """Return a bounded leading preview with an explicit remaining-line tail."""
    lines = content.splitlines()
    visible = lines[:line_limit]
    preview = Text("\n".join(visible))
    if visible:
        preview.append("\n")
    hidden = len(lines) - len(visible)
    if hidden > 0:
        preview.append(
            f"… +{hidden} more line{'s' if hidden != 1 else ''}\n",
            style="dim italic",
        )
    return preview


def reply_tail_preview(
    content: str,
    *,
    line_limit: int = _FAMILY_REPLY_TAIL_LINE_LIMIT,
) -> Text:
    """Return the last meaningful reply lines with an earlier-lines tail."""
    meaningful = [line for line in content.splitlines() if line.strip()]
    visible = meaningful[-line_limit:]
    preview = Text()
    hidden = len(meaningful) - len(visible)
    if hidden > 0:
        preview.append(
            f"… +{hidden} earlier line{'s' if hidden != 1 else ''}\n",
            style="dim italic",
        )
    if visible:
        preview.append("\n".join(visible) + "\n")
    else:
        preview.append("No response content yet.\n", style="dim italic")
    return preview


def _family_member_label(member: Agent, family_name: str) -> str:
    name = member.presented_agent_name or member.step_name or member.display_name
    if family_name and name.startswith(family_name) and len(name) > len(family_name):
        return name[len(family_name) :]
    if member.role_suffix:
        return member.role_suffix
    return name


def _member_duration(member: Agent, *, now: datetime | None) -> str:
    leaf = member
    if member.runtime_children:
        leaf = copy(member)
        leaf.runtime_children = []
    _timestamp, elapsed = compute_row_runtime(leaf, now=now)
    return elapsed or "—"


def _family_member_digest(member: Agent) -> _FamilyMemberDigest:
    return _FamilyMemberDigest(
        activity=member.activity,
        waiting=_waiting_digest(member),
        retry=_retry_digest(member),
        workspace_num=member.effective_workspace_num,
        start_time=member.start_time,
        run_start_time=member.run_start_time,
        stop_time=member.stop_time,
        attempt_count=len(member.attempt_history),
    )


def _waiting_digest(member: Agent) -> tuple[str, ...]:
    parts: list[str] = []
    if member.waiting_for:
        parts.append("for " + ", ".join(member.waiting_for))
    if member.waiting_for_beads:
        parts.append("for beads " + ", ".join(member.waiting_for_beads))
    if member.wait_duration is not None:
        parts.append(f"{member.wait_duration:g}s")
    if member.wait_until:
        parts.append(f"until {member.wait_until}")
    if member.wait_runners is not None:
        parts.append(f"runners≤{member.wait_runners}")
    return tuple(parts)


def _retry_digest(member: Agent) -> tuple[str, ...]:
    parts: list[str] = []
    if member.retry_count or member.max_retries:
        parts.append(f"{member.retry_count}/{member.max_retries}")
    if member.retry_status:
        parts.append(member.retry_status.replace("_", " "))
    if member.using_fallback:
        parts.append(f"via {member.fallback_model or 'fallback'}")
    return tuple(parts)


__all__ = [
    "FAMILY_IDENTITY_COLOR",
    "FAMILY_PROMPT_SECTION_ID",
    "FAMILY_REPLY_SECTION_ID",
    "FAMILY_XPROMPT_SECTION_ID",
    "append_family_fold_heading",
    "append_family_member_roster",
    "bounded_content_preview",
    "effective_family_fold_level",
    "family_member_rows",
    "reply_tail_preview",
]
