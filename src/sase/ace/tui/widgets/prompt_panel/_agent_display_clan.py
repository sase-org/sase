"""Aggregate detail rendering for synthetic agent-clan rows."""

from __future__ import annotations

from collections.abc import Collection
from copy import copy
from datetime import datetime

from rich.text import Text

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    status_bucket_for_values,
)

from ...agent_count_chip import format_agent_count_chip
from ...models._agent_clan import (
    aggregate_clan_status,
    clan_member_counts,
    clan_members,
)
from ...models.agent import Agent, AgentType, compute_row_runtime
from .._agent_list_styling import (
    _AGENT_NAME_ANNOTATION_STYLE,
    _CLAN_IDENTITY_COLOR,
    _CLAN_NAME_STYLE,
)
from ._helpers import (
    append_major_section_divider,
    append_section_heading,
)

_CLAN_HEADING_STYLE = f"bold {_CLAN_IDENTITY_COLOR} underline"
_FIELD_LABEL_STYLE = "bold #87D7FF"
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


def _append_member_line(
    text: Text,
    *,
    label: str,
    kind: str,
    status: str,
    model: str,
    duration: str,
    indent: str = "",
) -> None:
    bucket = status_bucket_for_values(status)
    glyph = AGENT_STATUS_BUCKET_GLYPHS[bucket]
    status_style = _MEMBER_STATUS_STYLES[bucket]

    if indent:
        text.append(indent, style="dim #808080")
    text.append(label, style=_AGENT_NAME_ANNOTATION_STYLE)
    text.append(" · ", style="dim")
    text.append(kind, style=_MEMBER_KIND_STYLE)
    text.append(" · ", style="dim")
    text.append(f"{glyph} {status}", style=status_style)
    text.append(" · ", style="dim")
    text.append(model, style=_MEMBER_MODEL_STYLE)
    text.append(" · ", style="dim")
    text.append(f"{duration}\n", style=_MEMBER_DURATION_STYLE)


def _append_members_section(
    text: Text,
    agent: Agent,
    members: tuple[Agent, ...],
    *,
    now: datetime | None,
) -> None:
    if not members:
        return

    append_major_section_divider(text)
    heading = Text("MEMBERS", style="bold #D7AF5F underline")
    heading.append(f" · {len(members)}", style="dim")
    append_section_heading(text, heading, section_id="members")

    clan_name = agent.agent_clan or agent.display_name
    for member in members:
        children = _family_children(member)
        if not children:
            _append_member_line(
                text,
                label=_hood_suffix(member, clan_name),
                kind=_member_kind(member),
                status=member.display_status,
                model=_member_model_label(member),
                duration=_duration_label(member, now=now),
            )
            continue

        rows = _family_rows(member, children)
        family_status = (
            aggregate_clan_status(row.status for row in rows) or member.display_status
        )
        _append_member_line(
            text,
            label=_family_suffix(member, clan_name),
            kind="family",
            status=family_status,
            model=_model_label(rows or (member,)),
            duration=_family_duration_label(member, rows, now=now),
        )
        for index, family_member in enumerate(rows):
            branch = "  └─ " if index == len(rows) - 1 else "  ├─ "
            _append_member_line(
                text,
                label=_nested_family_suffix(family_member, member, clan_name),
                kind=_member_kind(family_member),
                status=family_member.display_status,
                model=family_member.model or "default",
                duration=_duration_label(
                    _leaf_for_runtime(family_member),
                    now=now,
                ),
                indent=branch,
            )


def build_clan_detail_text(
    agent: Agent,
    *,
    now: datetime | None = None,
    unread_ids: Collection[tuple[AgentType, str, str | None]] = (),
) -> Text:
    """Build the complete in-memory detail document for a clan container."""
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

    _append_members_section(text, agent, members, now=now)
    return text


__all__ = ["build_clan_detail_text"]
