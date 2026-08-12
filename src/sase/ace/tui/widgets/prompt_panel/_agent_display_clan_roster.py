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
from ...models.agent_family_members import family_member_status_buckets
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


def family_children(member: Agent) -> tuple[Agent, ...]:
    """Return sequential family members nested below a direct clan member."""
    return tuple(
        child
        for child in member.runtime_children
        if child.is_family_member_child and not child.agent_family_parallel
    )


def family_rows(member: Agent, children: tuple[Agent, ...]) -> tuple[Agent, ...]:
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
    return agent.presented_agent_name or agent.step_name or agent.display_name


def _hood_suffix(agent: Agent, clan_name: str) -> str:
    """Render a member identity relative to its clan hood."""
    name = _row_name(agent)
    prefix = f"{clan_name}."
    if name.startswith(prefix):
        return name[len(clan_name) :]
    return name


def _family_suffix(member: Agent, clan_name: str) -> str:
    family_name = _presented_family_name(member)
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
    family_name = _presented_family_name(family)
    if name.startswith(family_name) and len(name) > len(family_name):
        return name[len(family_name) :]
    return _hood_suffix(member, clan_name)


def _presented_family_name(agent: Agent) -> str:
    """Derive a family container from raw relations and presented identity."""
    return agent.presented_family_reference_name() or _row_name(agent)


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


def _family_duration_label(
    family: Agent,
    rows: tuple[Agent, ...],
    *,
    now: datetime | None,
) -> str:
    if not rows:
        return duration_label(family, now=now)
    aggregate = copy(family)
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
        children = family_children(member)
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

        rows = family_rows(member, children)
        family_buckets = family_member_status_buckets(rows)
        family_status_entries = tuple(
            (row.status, bucket)
            for row, bucket in zip(rows, family_buckets, strict=True)
        )
        family_status = (
            aggregate_agent_group_effective_status(family_status_entries)
            or member.display_status
        )
        family_bucket = aggregate_agent_group_bucket(family_status_entries)
        roster_children = tuple(
            MemberRosterChild(
                label=_nested_family_suffix(family_member, member, clan_name),
                kind=_member_kind(family_member),
                status=family_member.display_status,
                effective_bucket=bucket,
                model=family_member.model or "default",
                duration=duration_label(
                    _leaf_for_runtime(family_member),
                    now=now,
                ),
                digest=digest_by_identity.get(family_member.identity),
            )
            for family_member, bucket in zip(rows, family_buckets, strict=True)
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
                effective_bucket=family_bucket,
                model=_model_label(rows or (member,)),
                duration=_family_duration_label(member, rows, now=now),
                digest=digest_by_identity.get(member.identity),
                children=roster_children,
            )
        )
    return tuple(entries)
