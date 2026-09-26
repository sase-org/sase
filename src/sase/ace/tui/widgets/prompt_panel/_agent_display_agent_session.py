"""Fold-aware agent-session container helpers for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from rich.text import Text

from sase.agent.status_buckets import agent_status_bucket
from sase.gate_turn.state import GATE_GLYPH
from sase.monitor_state import MONITOR_GLYPH, MONITOR_GLYPH_COLOR

from ...models._agent_clan_sections import first_meaningful_line
from ...models.agent import Agent
from ...models.agent_owner_badge import agent_owner_badge_label
from ...models.agent_session_members import (
    concrete_agent_session_shell_rows as agent_session_shell_rows,
    agent_session_member_status_buckets,
    gate_row_is_settled,
    monitor_row_is_settled,
)
from ...models.fold_scale import (
    AGENT_SESSION_FOLD_SCALE,
    FoldScale,
    effective_fold_level,
)
from ...models.fold_state import FoldLevel
from dataclasses import dataclass

from ._agent_display_content import (
    GATE_PHASE_LABEL,
    MONITOR_PHASE_LABEL,
    PHASE_DIVIDER_ACCENT,
    get_phase_label,
)
from ._fold_language import append_fold_section_heading
from ._member_roster import (
    MemberJumpMap,
    MemberJumpNumbering,
    MemberRosterEntry,
    append_member_roster,
)
from ._member_roster_digest import agent_roster_digest, agent_roster_duration

SESSION_IDENTITY_COLOR = "#00AFFF"
_AGENT_SESSION_ROSTER_TITLE = "SESSION SHELLS"
_MONITOR_DESCRIPTOR_MAX_CHARS = 40
_MONITOR_FAILURE_STATES = frozenset({"failed", "timeout", "lost"})
_MONITOR_COMMAND_FALLBACK = "command"
_GATE_DESCRIPTOR_MAX_CHARS = 40
_GATE_FAILURE_STATES = frozenset({"failed", "timeout", "lost"})
_GATE_TITLE_FALLBACK = "decision"


def effective_agent_session_fold_level(
    section_id: str,
    panel_level: FoldLevel,
    overrides: Mapping[str, FoldLevel] | None = None,
) -> FoldLevel:
    """Resolve an agent-session section override against the shared panel level."""
    level = (overrides or {}).get(section_id, panel_level)
    return effective_fold_level(level, AGENT_SESSION_FOLD_SCALE)


def append_agent_session_fold_heading(
    text: Any,
    title: str,
    *,
    section_id: str,
    level: FoldLevel,
    count: int | None = None,
    style: str = "bold #D7AF5F underline",
) -> None:
    """Append one agent-session heading carrying its effective fold glyph."""
    append_fold_section_heading(
        text,
        title,
        section_id=section_id,
        level=level,
        scale=AGENT_SESSION_FOLD_SCALE,
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


def _gate_roster_descriptor(member: Agent) -> str:
    """Return a bounded one-line gate descriptor for the roster model slot."""
    label = first_meaningful_line(
        member.gate_label or "",
        max_chars=_GATE_DESCRIPTOR_MAX_CHARS,
    )
    if label:
        return label
    kind = first_meaningful_line(
        member.gate_kind or "",
        max_chars=_GATE_DESCRIPTOR_MAX_CHARS,
    )
    return kind or _GATE_TITLE_FALLBACK


def _gate_roster_bucket(member: Agent) -> str:
    """Return the agent-status bucket used to style one gate roster row."""
    if member.gate_state in _GATE_FAILURE_STATES:
        return "Failed"
    if gate_row_is_settled(member):
        return "Done"
    return "Stopped"


@dataclass(frozen=True, slots=True)
class AgentSessionShellFacts:
    """Per-shell display facts shared by the JUMP roster and card blocks."""

    member: Agent
    label: str
    kind: str
    glyph: str
    accent: str
    status_bucket: str


def agent_session_shell_facts(agent: Agent) -> tuple[AgentSessionShellFacts, ...]:
    """Return one facts row per concrete shell, in chronological shell order.

    The JUMP roster numbers shells by chronological index, so card blocks
    built from these facts match the roster by construction.
    """
    agent_session_name = agent.presented_agent_name or ""
    shells = agent_session_shell_rows(agent)
    agent_shells = tuple(
        shell for shell in shells if not (shell.is_monitor or shell.is_gate)
    )
    agent_buckets = {
        shell.identity: bucket
        for shell, bucket in zip(
            agent_shells,
            agent_session_member_status_buckets(agent_shells),
            strict=True,
        )
    }
    facts: list[AgentSessionShellFacts] = []
    for member in shells:
        if member.is_monitor:
            facts.append(
                AgentSessionShellFacts(
                    member=member,
                    label=agent_session_member_label(member, agent_session_name),
                    kind="monitor",
                    glyph=MONITOR_GLYPH,
                    accent=MONITOR_GLYPH_COLOR,
                    status_bucket=_monitor_roster_bucket(member),
                )
            )
        elif member.is_gate:
            facts.append(
                AgentSessionShellFacts(
                    member=member,
                    label=agent_session_member_label(member, agent_session_name),
                    kind="gate",
                    glyph=GATE_GLYPH,
                    accent=member.gate_accent or "#0BCDEC",
                    status_bucket=_gate_roster_bucket(member),
                )
            )
        else:
            facts.append(
                AgentSessionShellFacts(
                    member=member,
                    label=agent_session_member_label(member, agent_session_name),
                    kind="agent",
                    glyph="",
                    accent=PHASE_DIVIDER_ACCENT,
                    status_bucket=agent_buckets[member.identity],
                )
            )
    return tuple(facts)


def agent_session_roster_entries(
    agent: Agent,
    *,
    now: datetime | None = None,
    exclude: Agent | None = None,
) -> tuple[MemberRosterEntry, ...]:
    """Adapt an agent-session chain into shared numbered roster entries."""
    entries: list[MemberRosterEntry] = []
    for facts in agent_session_shell_facts(agent):
        member = facts.member
        if exclude is not None and (
            member is exclude or member.identity == exclude.identity
        ):
            continue
        if member.is_monitor:
            kind = f"{MONITOR_GLYPH} {MONITOR_PHASE_LABEL}"
            model = _monitor_roster_descriptor(member)
            bucket = facts.status_bucket
        elif member.is_gate:
            kind = f"{GATE_GLYPH} {GATE_PHASE_LABEL}"
            model = _gate_roster_descriptor(member)
            bucket = facts.status_bucket
        else:
            phase_label = get_phase_label(member)
            kind = "agent" if phase_label == "AGENT" else phase_label
            model = member.model or "default"
            bucket = facts.status_bucket
        entries.append(
            MemberRosterEntry(
                identity=member.identity,
                presented_name=(
                    member.agent_name
                    or member.presented_agent_name
                    or member.role_suffix
                    or member.display_name
                ),
                label=facts.label,
                kind=kind,
                status=member.display_status,
                effective_bucket=bucket,
                model=model,
                duration=agent_roster_duration(member, now=now),
                digest=agent_roster_digest(member),
                owner_badge=agent_owner_badge_label(member),
            )
        )
    return tuple(entries)


def append_agent_session_member_roster(
    text: Text,
    agent: Agent,
    *,
    panel_level: FoldLevel,
    section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    now: datetime | None = None,
    entries: Sequence[MemberRosterEntry] | None = None,
    numbering: MemberJumpNumbering | None = None,
    fold_scale: FoldScale = AGENT_SESSION_FOLD_SCALE,
    heading_suffix: Text | None = None,
) -> MemberJumpMap:
    """Render an agent-session container's numbered roster."""
    return append_member_roster(
        text,
        container_identity=agent.identity,
        entries=entries
        if entries is not None
        else agent_session_roster_entries(agent, now=now),
        title=_AGENT_SESSION_ROSTER_TITLE,
        accent=SESSION_IDENTITY_COLOR,
        panel_level=panel_level,
        section_fold_overrides=section_fold_overrides,
        fold_scale=fold_scale,
        numbering=numbering,
        hidden_tail_label="shells",
        heading_suffix=heading_suffix,
    )


def agent_session_roster_heading_suffix(container: Agent) -> Text:
    """Return the ` · <agent-session name>` suffix naming a member panel's session."""
    suffix = Text()
    suffix.append(" · ", style="dim")
    suffix.append(
        container.presented_agent_name or "",
        style=SESSION_IDENTITY_COLOR,
    )
    return suffix


def agent_session_member_label(member: Agent, agent_session_name: str) -> str:
    name = member.presented_agent_name or member.step_name or member.display_name
    if (
        agent_session_name
        and name.startswith(agent_session_name)
        and len(name) > len(agent_session_name)
    ):
        return name[len(agent_session_name) :]
    if member.role_suffix:
        return member.role_suffix
    return name


def legacy_followup_shell_facts(
    agent: Agent,
) -> tuple[AgentSessionShellFacts, ...]:
    """Return one facts row per legacy ``followup_agents`` phase.

    The legacy non-session Reply path has no session roster, so labels fall
    back to the role-suffix phase labels and plain phases keep the global
    agent status bucket. Chronological order is root first, then followups,
    which is also the card-block numbering.
    """
    facts: list[AgentSessionShellFacts] = []
    for member in (agent, *agent.followup_agents):
        if member.is_monitor:
            facts.append(
                AgentSessionShellFacts(
                    member=member,
                    label=get_phase_label(member),
                    kind="monitor",
                    glyph=MONITOR_GLYPH,
                    accent=MONITOR_GLYPH_COLOR,
                    status_bucket=_monitor_roster_bucket(member),
                )
            )
        elif member.is_gate:
            facts.append(
                AgentSessionShellFacts(
                    member=member,
                    label=get_phase_label(member),
                    kind="gate",
                    glyph=GATE_GLYPH,
                    accent=member.gate_accent or "#0BCDEC",
                    status_bucket=_gate_roster_bucket(member),
                )
            )
        else:
            facts.append(
                AgentSessionShellFacts(
                    member=member,
                    label=get_phase_label(member),
                    kind="agent",
                    glyph="",
                    accent=PHASE_DIVIDER_ACCENT,
                    status_bucket=agent_status_bucket(member),
                )
            )
    return tuple(facts)


__all__ = [
    "SESSION_IDENTITY_COLOR",
    "AgentSessionShellFacts",
    "append_agent_session_fold_heading",
    "append_agent_session_member_roster",
    "effective_agent_session_fold_level",
    "agent_session_member_label",
    "agent_session_roster_entries",
    "agent_session_roster_heading_suffix",
    "agent_session_shell_facts",
    "agent_session_shell_rows",
    "legacy_followup_shell_facts",
]
