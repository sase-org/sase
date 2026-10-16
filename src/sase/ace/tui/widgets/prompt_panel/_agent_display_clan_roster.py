"""Member-roster adaptation for synthetic agent-clan detail rows."""

from __future__ import annotations

from collections.abc import Mapping
from copy import copy
from dataclasses import replace
from datetime import datetime

from sase.agent.status_buckets import (
    agent_status_bucket,
    aggregate_agent_group_bucket,
    aggregate_agent_group_effective_status,
)

from ...models._agent_clan import clan_members
from ...models._agent_clan_sections import ClanMemberDigest
from ...models.agent import Agent, AgentType, compute_row_runtime
from ...models.agent_session_members import (
    agent_session_lane_status_entries,
    agent_session_member_status_buckets,
)
from ._member_roster import MemberRosterChild, MemberRosterEntry

CLAN_NEIGHBORS_SECTION_ID = "clan-neighbors"
CLAN_NEIGHBORS_ROSTER_TITLE = "CLAN NEIGHBORS"
CLAN_NEIGHBORS_IDENTITY_COLOR = "#00D7AF"


def _predecessor_summary(
    predecessor_identities: tuple[str, ...],
    *,
    entries_by_identity: dict[str, MemberRosterEntry],
    wave_by_identity: Mapping[str, object],
    kind: str = "number",
    is_epic_seal: bool = False,
) -> str:
    """Describe the members or waves that precede one roster group."""
    # Deferred so the clan-wave modules stay off the TUI startup import path;
    # after first use this is only a ``sys.modules`` hit.
    from .._clan_wave_presentation import format_wave_after_phrase

    labels = tuple(
        entries_by_identity[identity].label
        for identity in predecessor_identities
        if identity in entries_by_identity
    )
    predecessor_waves = tuple(
        wave_index
        for identity in predecessor_identities
        if (member := wave_by_identity.get(identity)) is not None
        and (wave_index := getattr(member, "wave_index", None)) is not None
    )
    return format_wave_after_phrase(
        kind=kind,
        predecessor_labels=labels,
        predecessor_waves=predecessor_waves,
        is_epic_seal=is_epic_seal,
    )


def _layered_group_labels(
    agent: Agent,
    entries: tuple[MemberRosterEntry, ...],
) -> tuple[dict[tuple[AgentType, str, str | None], str], str | None]:
    """Return JUMP group labels and the optional layered-clan title suffix."""
    # Deferred so the clan-wave modules stay off the TUI startup import path;
    # after first use this is only a ``sys.modules`` hit.
    from ...models._agent_clan_waves import clan_wave_identity_key
    from .._clan_wave_presentation import format_wave_after_phrase

    summary = agent.clan_waves
    if summary is None or not summary.layered:
        return {}, None

    entries_by_agent_identity = {entry.identity: entry for entry in entries}
    entries_by_identity = {
        clan_wave_identity_key(member): entries_by_agent_identity[member.identity]
        for member in clan_members(agent)
        if member.identity in entries_by_agent_identity
    }
    wave_by_identity = {member.identity: member for member in summary.members}
    member_rows = {
        clan_wave_identity_key(member): member for member in clan_members(agent)
    }
    group_by_identity: dict[tuple[AgentType, str, str | None], str] = {}
    for wave in summary.waves:
        if wave.kind == "seal":
            epic_land = any(
                (row := member_rows.get(identity)) is not None
                and row.epic_bead_id
                and not row.phase_bead_id
                for identity in wave.member_identities
            )
            phrase = format_wave_after_phrase(
                kind="seal",
                predecessor_labels=(),
                predecessor_waves=(),
                is_epic_seal=epic_land,
            )
            label = f"land · {phrase}"
        elif wave.kind == "unresolved":
            label = "unresolved · wait cycle"
        else:
            label = f"wave {wave.number} · " + _predecessor_summary(
                wave.predecessor_identities,
                entries_by_identity=entries_by_identity,
                wave_by_identity=wave_by_identity,
            )
        for identity in wave.member_identities:
            if identity in entries_by_identity:
                group_by_identity[entries_by_identity[identity].identity] = label

    if summary.numbered_wave_count == 0:
        return group_by_identity, None
    wave_noun = "WAVE" if summary.numbered_wave_count == 1 else "WAVES"
    title_suffix = f"{summary.numbered_wave_count} {wave_noun}"
    if summary.has_seal:
        title_suffix += " + LAND"
    return group_by_identity, title_suffix


def ordered_clan_members(agent: Agent) -> tuple[Agent, ...]:
    """Return direct members in wave order for layered clans, launch order otherwise."""
    members = clan_members(agent)
    if agent.clan_waves is not None and agent.clan_waves.layered:
        return tuple(
            sorted(
                members,
                key=lambda member: (
                    member.clan_wave_slot is None,
                    (
                        member.clan_wave_slot.rank
                        if member.clan_wave_slot is not None
                        else 0
                    ),
                ),
            )
        )
    return tuple(
        sorted(
            members,
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
        agent_session_status_entries = agent_session_lane_status_entries(rows)
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
    roster_entries = tuple(entries)
    group_labels, _title_suffix = _layered_group_labels(agent, roster_entries)
    if not group_labels:
        return roster_entries
    return tuple(
        replace(
            entry,
            group_label=group_labels.get(entry.identity),
            legend_group=group_labels.get(entry.identity),
        )
        for entry in roster_entries
    )


def clan_roster_title_suffix(agent: Agent) -> str | None:
    """Return the layered-clan wave count for the collapsed JUMP title."""
    _groups, title_suffix = _layered_group_labels(agent, ())
    return title_suffix


def clan_neighbor_roster_entries(
    targets: tuple[Agent, ...],
    *,
    now: datetime | None,
) -> tuple[MemberRosterEntry, ...]:
    """Adapt clan neighbor containers into shared roster entries."""
    entries: list[MemberRosterEntry] = []
    for target in targets:
        full_name = (
            target.presented_agent_name or target.agent_clan or _row_name(target)
        )
        model = target.model or _model_label(
            tuple(child for child in target.runtime_children if child.model)
        )
        entries.append(
            MemberRosterEntry(
                identity=target.identity,
                presented_name=full_name,
                label=full_name,
                kind="clan",
                status=target.display_status,
                effective_bucket=agent_status_bucket(target),
                model=model,
                duration=duration_label(target, now=now),
                target_role="clan_neighbor",
            )
        )
    return tuple(entries)
