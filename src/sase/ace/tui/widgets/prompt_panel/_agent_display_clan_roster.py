"""Member-roster adaptation for synthetic agent-clan detail rows."""

from __future__ import annotations

from copy import copy
from datetime import datetime

from sase.agent.status_buckets import (
    agent_status_bucket,
    aggregate_agent_group_bucket,
    aggregate_agent_group_effective_status,
)

from ...models._agent_clan import clan_members
from ...models._agent_clan_sections import ClanMemberDigest
from ...models.agent import Agent, AgentType, compute_row_runtime
from ...models.agent_session_members import agent_session_member_status_buckets
from ._member_roster import MemberRosterChild, MemberRosterEntry


def ordered_clan_members(agent: Agent) -> tuple[Agent, ...]:
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
                member.presented_agent_name or member.display_name,
            ),
        )
    )


def agent_session_children(member: Agent) -> tuple[Agent, ...]:
    """Return sequential agent_session members nested below a direct clan member."""
    return tuple(
        child
        for child in member.runtime_children
        if child.is_agent_session_member_child and not child.agent_session_parallel
    )


def agent_session_rows(member: Agent, children: tuple[Agent, ...]) -> tuple[Agent, ...]:
    """Return real agent rows represented by one agent_session aggregate line.

    Rename-on-attach gives the first real agent_session member a ``--role`` name and
    retains it as the row that owns later ``parent_timestamp`` children. A
    legacy/root-shaped row whose name is exactly the agent_session container is not
    repeated as a child line.
    """
    agent_session_name = member.agent_session
    include_member = bool(
        member.agent_name
        and (not agent_session_name or member.agent_name != agent_session_name)
    )
    if include_member:
        return (member, *children)
    return children


def _row_name(agent: Agent) -> str:
    return agent.presented_agent_name or agent.step_name or agent.display_name


def _hood_suffix(agent: Agent, clan_name: str) -> str:
    """Render a member identity relative to its clan hood."""
    name = _row_name(agent)
    prefix = f"{clan_name}."
    if name.startswith(prefix):
        return name[len(clan_name) :]
    return name


def _agent_session_suffix(member: Agent, clan_name: str) -> str:
    agent_session_name = _presented_agent_session_name(member)
    prefix = f"{clan_name}."
    if agent_session_name.startswith(prefix):
        return agent_session_name[len(clan_name) :]
    return agent_session_name


def _nested_agent_session_suffix(
    member: Agent,
    agent_session: Agent,
    clan_name: str,
) -> str:
    name = _row_name(member)
    agent_session_name = _presented_agent_session_name(agent_session)
    if name.startswith(agent_session_name) and len(name) > len(agent_session_name):
        return name[len(agent_session_name) :]
    return _hood_suffix(member, clan_name)


def _presented_agent_session_name(agent: Agent) -> str:
    """Derive a agent_session container from raw relations and presented identity."""
    return agent.presented_agent_session_reference_name() or _row_name(agent)


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


def duration_label(member: Agent, *, now: datetime | None) -> str:
    """Return the display duration for a clan member or aggregate."""
    _timestamp, elapsed = compute_row_runtime(member, now=now)
    return elapsed or "—"


def _agent_session_duration_label(
    agent_session: Agent,
    rows: tuple[Agent, ...],
    *,
    now: datetime | None,
) -> str:
    if not rows:
        return duration_label(agent_session, now=now)
    aggregate = copy(agent_session)
    aggregate.runtime_children = [_leaf_for_runtime(row) for row in rows]
    return duration_label(aggregate, now=now)


def clan_roster_entries(
    agent: Agent,
    members: tuple[Agent, ...],
    *,
    now: datetime | None,
    digests: tuple[ClanMemberDigest, ...],
) -> tuple[MemberRosterEntry, ...]:
    """Adapt deterministic clan rows into shared roster entries."""
    clan_name = agent.presented_agent_name or agent.display_name
    digest_by_identity = {digest.identity: digest for digest in digests}
    entries: list[MemberRosterEntry] = []
    for member in members:
        children = agent_session_children(member)
        if not children:
            entries.append(
                MemberRosterEntry(
                    identity=member.identity,
                    presented_name=member.presented_agent_name or _row_name(member),
                    label=_hood_suffix(member, clan_name),
                    kind=_member_kind(member),
                    status=member.display_status,
                    effective_bucket=agent_status_bucket(member),
                    model=_member_model_label(member),
                    duration=duration_label(member, now=now),
                    digest=digest_by_identity.get(member.identity),
                )
            )
            continue

        rows = agent_session_rows(member, children)
        agent_session_buckets = agent_session_member_status_buckets(rows)
        agent_session_status_entries = tuple(
            (row.status, bucket)
            for row, bucket in zip(rows, agent_session_buckets, strict=True)
        )
        agent_session_status = (
            aggregate_agent_group_effective_status(agent_session_status_entries)
            or member.display_status
        )
        agent_session_bucket = aggregate_agent_group_bucket(
            agent_session_status_entries
        )
        roster_children = tuple(
            MemberRosterChild(
                label=_nested_agent_session_suffix(
                    agent_session_member, member, clan_name
                ),
                kind=_member_kind(agent_session_member),
                status=agent_session_member.display_status,
                effective_bucket=bucket,
                model=agent_session_member.model or "default",
                duration=duration_label(
                    _leaf_for_runtime(agent_session_member),
                    now=now,
                ),
                digest=digest_by_identity.get(agent_session_member.identity),
            )
            for agent_session_member, bucket in zip(
                rows, agent_session_buckets, strict=True
            )
        )
        entries.append(
            MemberRosterEntry(
                identity=member.identity,
                presented_name=(
                    member.presented_agent_name
                    or member.agent_session
                    or _row_name(member)
                ),
                label=_agent_session_suffix(member, clan_name),
                kind="session",
                status=agent_session_status,
                effective_bucket=agent_session_bucket,
                model=_model_label(rows or (member,)),
                duration=_agent_session_duration_label(member, rows, now=now),
                digest=digest_by_identity.get(member.identity),
                children=roster_children,
            )
        )
    return tuple(entries)
