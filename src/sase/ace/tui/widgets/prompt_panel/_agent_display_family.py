"""Fold-aware family-container helpers for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from rich.text import Text

from ...models.agent import Agent
from ...models.agent_family_members import (
    concrete_family_member_rows as family_member_rows,
    family_member_status_buckets,
)
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
    MemberJumpNumbering,
    MemberRosterEntry,
    append_member_roster,
)
from ._member_roster_digest import agent_roster_digest, agent_roster_duration

FAMILY_IDENTITY_COLOR = "#00AFFF"
_FAMILY_ROSTER_TITLE = "FAMILY MEMBERS"


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


def family_roster_entries(
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
                duration=agent_roster_duration(member, now=now),
                digest=agent_roster_digest(member),
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
    entries: Sequence[MemberRosterEntry] | None = None,
    numbering: MemberJumpNumbering | None = None,
) -> MemberJumpMap:
    """Render a family container's numbered roster."""
    return append_member_roster(
        text,
        container_identity=agent.identity,
        entries=entries
        if entries is not None
        else family_roster_entries(agent, now=now),
        title=_FAMILY_ROSTER_TITLE,
        accent=FAMILY_IDENTITY_COLOR,
        panel_level=panel_level,
        section_fold_overrides=section_fold_overrides,
        fold_scale=FAMILY_FOLD_SCALE,
        numbering=numbering,
    )


def _family_member_label(member: Agent, family_name: str) -> str:
    name = member.presented_agent_name or member.step_name or member.display_name
    if family_name and name.startswith(family_name) and len(name) > len(family_name):
        return name[len(family_name) :]
    if member.role_suffix:
        return member.role_suffix
    return name


__all__ = [
    "FAMILY_IDENTITY_COLOR",
    "append_family_fold_heading",
    "append_family_member_roster",
    "effective_family_fold_level",
    "family_member_rows",
    "family_roster_entries",
]
