"""Fold-aware family-container helpers for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from rich.text import Text

from sase.monitor_state import MONITOR_GLYPH

from ...models._agent_clan_sections import first_meaningful_line
from ...models.agent import Agent
from ...models.agent_family_members import (
    concrete_family_shell_rows as family_shell_rows,
    family_member_status_buckets,
    monitor_row_is_settled,
)
from ...models.fold_scale import (
    FAMILY_FOLD_SCALE,
    FoldScale,
    effective_fold_level,
)
from ...models.fold_state import FoldLevel
from ._agent_display_content import MONITOR_PHASE_LABEL, get_phase_label
from ._fold_language import append_fold_section_heading
from ._member_roster import (
    MemberJumpMap,
    MemberJumpNumbering,
    MemberRosterEntry,
    append_member_roster,
)
from ._member_roster_digest import agent_roster_digest, agent_roster_duration

FAMILY_IDENTITY_COLOR = "#00AFFF"
_FAMILY_ROSTER_TITLE = "FAMILY SHELLS"
_MONITOR_DESCRIPTOR_MAX_CHARS = 40
_MONITOR_FAILURE_STATES = frozenset({"failed", "timeout", "lost"})
_MONITOR_COMMAND_FALLBACK = "command"


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
    append_fold_section_heading(
        text,
        title,
        section_id=section_id,
        level=level,
        scale=FAMILY_FOLD_SCALE,
        count=count,
        style=style,
    )


def _monitor_roster_descriptor(member: Agent) -> str:
    """Return a bounded one-line monitor descriptor for the roster model slot."""
    label = first_meaningful_line(
        member.monitor_label or "",
        max_chars=_MONITOR_DESCRIPTOR_MAX_CHARS,
    )
    if label:
        return label
    command = first_meaningful_line(
        member.monitor_command or "",
        max_chars=_MONITOR_DESCRIPTOR_MAX_CHARS,
    )
    return command or _MONITOR_COMMAND_FALLBACK


def _monitor_roster_bucket(member: Agent) -> str:
    """Return the agent-status bucket used to style one monitor roster row."""
    if member.monitor_state in _MONITOR_FAILURE_STATES:
        return "Failed"
    if monitor_row_is_settled(member):
        return "Done"
    return "Running"


def family_roster_entries(
    agent: Agent,
    *,
    now: datetime | None = None,
    exclude: Agent | None = None,
) -> tuple[MemberRosterEntry, ...]:
    """Adapt a family chain into shared numbered roster entries."""
    family_name = agent.presented_agent_name or ""
    shells = family_shell_rows(agent)
    agent_shells = tuple(shell for shell in shells if not shell.is_monitor)
    agent_buckets = {
        shell.identity: bucket
        for shell, bucket in zip(
            agent_shells,
            family_member_status_buckets(agent_shells),
            strict=True,
        )
    }
    entries: list[MemberRosterEntry] = []
    for member in shells:
        if exclude is not None and (
            member is exclude or member.identity == exclude.identity
        ):
            continue
        if member.is_monitor:
            kind = f"{MONITOR_GLYPH} {MONITOR_PHASE_LABEL}"
            model = _monitor_roster_descriptor(member)
            bucket = _monitor_roster_bucket(member)
        else:
            phase_label = get_phase_label(member)
            kind = "agent" if phase_label == "AGENT" else phase_label
            model = member.model or "default"
            bucket = agent_buckets[member.identity]
        entries.append(
            MemberRosterEntry(
                identity=member.identity,
                presented_name=(
                    member.agent_name
                    or member.presented_agent_name
                    or member.role_suffix
                    or member.display_name
                ),
                label=family_member_label(member, family_name),
                kind=kind,
                status=member.display_status,
                effective_bucket=bucket,
                model=model,
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
    fold_scale: FoldScale = FAMILY_FOLD_SCALE,
    heading_suffix: Text | None = None,
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
        fold_scale=fold_scale,
        numbering=numbering,
        hidden_tail_label="shells",
        heading_suffix=heading_suffix,
    )


def family_roster_heading_suffix(container: Agent) -> Text:
    """Return the ` · <family name>` suffix naming a member panel's family."""
    suffix = Text()
    suffix.append(" · ", style="dim")
    suffix.append(
        container.presented_agent_name or "",
        style=FAMILY_IDENTITY_COLOR,
    )
    return suffix


def family_member_label(member: Agent, family_name: str) -> str:
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
    "family_member_label",
    "family_roster_entries",
    "family_roster_heading_suffix",
    "family_shell_rows",
]
